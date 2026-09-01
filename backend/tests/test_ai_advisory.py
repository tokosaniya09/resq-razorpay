"""Tests for the advisory AI services (diagnosis + escalation).

With the LLM disabled these use deterministic fallbacks, so we can assert on
their output exactly. The key guarantees: they produce sensible, grounded text
from real statistics, and — critically — they are advisory only (they never
return or alter a money Action).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.domain import (
    Action,
    Decision,
    EventSource,
    PaymentEvent,
    RouteState,
)
from app.services.diagnosis.service import DiagnosisService
from app.services.escalation.service import EscalationService


@pytest.fixture
def settings():
    return Settings(degradation_window_size=20, llm_enabled=False)


def _fail(idx, code, route="UPI-SBI", amount=99900):
    return PaymentEvent(
        event_id=f"e{idx}",
        source=EventSource.SYNTHETIC,
        transaction_id=f"t{idx}",
        amount=amount,
        currency="INR",
        status="failed",
        error_code=code,
        route=route,
    )


def test_diagnosis_identifies_technical_outage(settings):
    svc = DiagnosisService(settings)
    # a cluster of technical timeouts across varied amounts
    for i in range(10):
        svc.observe(_fail(i, "GATEWAY_TIMEOUT", amount=10000 * (i + 1)))
    d = svc.diagnose("UPI-SBI", RouteState.DOWN, failure_rate=0.9)
    assert d.generated_by == "heuristic"  # no LLM in tests
    assert "acquirer-side outage" in d.body.lower() or "technical" in d.body.lower()
    assert "hold" in d.body.lower()
    assert d.sample_size == 10


def test_diagnosis_identifies_customer_side(settings):
    svc = DiagnosisService(settings)
    for i in range(8):
        svc.observe(_fail(i, "INSUFFICIENT_FUNDS"))
    d = svc.diagnose("UPI-SBI", RouteState.DEGRADING, failure_rate=0.5)
    assert "customer-side" in d.body.lower() or "link" in d.body.lower()


def test_diagnosis_ignores_captured_events(settings):
    svc = DiagnosisService(settings)
    ok = PaymentEvent(
        event_id="ok",
        source=EventSource.SYNTHETIC,
        transaction_id="tok",
        amount=1000,
        currency="INR",
        status="captured",
        error_code=None,
        route="UPI-SBI",
    )
    svc.observe(ok)
    d = svc.diagnose("UPI-SBI", RouteState.DEGRADING, failure_rate=0.4)
    assert d.sample_size == 0  # captured events are not part of the failure cluster


def test_escalation_note_is_advisory_text_only(settings):
    svc = EscalationService(settings)
    event = _fail(1, "MYSTERY")
    decision = Decision(
        event_id="e1",
        transaction_id="t1",
        action=Action.STOP,
        rule_fired="R6_unrecoverable",
        reason="no safe recovery",
        attempt_number=1,
        idempotency_key="k",
        route_state=RouteState.HEALTHY,
    )
    esc = svc.draft(event, decision, "Unmapped error code")
    assert esc.generated_by == "template"
    assert esc.transaction_id == "t1"
    # it references the facts and recommends a human step
    assert "t1" in esc.body
    assert "follow-up" in esc.body.lower() or "dunning" in esc.body.lower()
    # advisory: an Escalation has no Action field at all
    assert not hasattr(esc, "action")


# --------------------------------------------------------------------------- #
# Ledger assistant (Feature #4) — answers only from verified facts.
# --------------------------------------------------------------------------- #
def test_ledger_assistant_answers_from_facts(settings):
    from app.services.assistant.service import LedgerAssistant
    import app.services.ledger.metrics as mm

    class _M:
        rupees_rescued = 41966.0
        recovered = 40
        recovery_rate = 0.71
        links_issued = 21
        retries_avoided_degraded = 47
        wasted_retries_avoided = 21
        unrecoverable = 3
        total_events = 90

    mm.compute = lambda repo: _M()  # type: ignore

    class _D:
        def __init__(self, a, r):
            self.action, self.rule_fired = a, r

    class _Repo:
        def all_decisions(self):
            return [_D("HOLD", "R1_hold_route_down")] * 47

    class _Snap:
        def __init__(self, route, state, rate, n):
            self.route = route
            self.state = type("S", (), {"value": state})
            self.failure_rate = rate
            self.samples = n

    class _Det:
        def snapshot_all(self):
            return [_Snap("UPI-SBI", "RECOVERING", 0.2, 20)]

    a = LedgerAssistant(settings, _Det())  # llm disabled -> deterministic

    ans = a.answer("How much did we rescue?", _Repo())
    assert "41,966" in ans.answer and ans.generated_by == "deterministic"

    ans2 = a.answer("How many were unrecoverable?", _Repo())
    assert "3" in ans2.answer  # the specific branch wins, not the money branch

    # the snapshot it used is real, inspectable facts
    assert ans.snapshot["totals"]["payments_recovered"] == 40
