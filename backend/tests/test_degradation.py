"""Degradation detector tests — the differentiator's state machine."""

from __future__ import annotations

from app.models.domain import RouteState
from app.services.degradation.detector import DegradationDetector


def _feed(det, route, failures, successes, start=0):
    last = None
    i = start
    for _ in range(failures):
        last = _obs(det, route, True, i); i += 1
    for _ in range(successes):
        last = _obs(det, route, False, i); i += 1
    return last, i


def _obs(det, route, is_failure, idx):
    from app.models.domain import EventSource, PaymentEvent

    e = PaymentEvent(
        event_id=f"e{idx}",
        source=EventSource.SYNTHETIC,
        transaction_id=f"t{idx}",
        amount=50000,
        currency="INR",
        status="failed" if is_failure else "captured",
        error_code="GATEWAY_TIMEOUT" if is_failure else None,
        route=route,
    )
    return det.observe(e)


def test_starts_healthy(settings):
    det = DegradationDetector(settings)
    snap = _obs(det, "UPI-HDFC", False, 0)
    assert snap.state is RouteState.HEALTHY


def test_min_samples_prevents_overreaction(settings):
    det = DegradationDetector(settings)
    # Two failures only — below min_samples (4). Must not flip to DOWN.
    s1 = _obs(det, "R", True, 0)
    s2 = _obs(det, "R", True, 1)
    assert s1.state is RouteState.HEALTHY
    assert s2.state is RouteState.HEALTHY


def test_flood_of_failures_goes_down(settings):
    det = DegradationDetector(settings)
    last, _ = _feed(det, "R", failures=9, successes=0)
    assert last.state is RouteState.DOWN
    assert last.failure_rate >= settings.degradation_critical_threshold


def test_degrading_between_thresholds(settings):
    det = DegradationDetector(settings)
    # 5 failures / 5 successes = 0.50 -> between warn(0.4) and crit(0.65)
    last, _ = _feed(det, "R", failures=5, successes=5)
    assert last.state is RouteState.DEGRADING


def test_recovers_after_down(settings):
    det = DegradationDetector(settings)
    _feed(det, "R", failures=9, successes=0)
    # drain the window with successes; with drain_after=0 it can reach HEALTHY
    last, _ = _feed(det, "R", failures=0, successes=12, start=100)
    assert last.state in (RouteState.RECOVERING, RouteState.HEALTHY)


def test_routes_are_independent(settings):
    det = DegradationDetector(settings)
    _feed(det, "UPI-A", failures=9, successes=0)
    healthy, _ = _feed(det, "UPI-B", failures=0, successes=6, start=200)
    assert det.state_of("UPI-A") is RouteState.DOWN
    assert healthy.state is RouteState.HEALTHY
