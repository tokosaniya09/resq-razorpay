"""Policy engine tests — one rule fires per input, and it's the right one."""

from __future__ import annotations

from app.models.domain import Action, RouteState
from app.services.classifier.service import classify
from app.services.policy.engine import PolicyEngine
from app.services.policy.guardrails import Guardrails


def _decide(settings, event, route_state):
    g = Guardrails(settings)
    return PolicyEngine(g).decide(event, classify(event), route_state)


def test_down_route_technical_holds(settings, make_event):
    e = make_event(error_code="GATEWAY_TIMEOUT")
    d = _decide(settings, e, RouteState.DOWN)
    assert d.action is Action.HOLD
    assert d.rule_fired == "R1_hold_route_down"


def test_degrading_route_technical_holds(settings, make_event):
    e = make_event(error_code="NETWORK_TIMEOUT")
    d = _decide(settings, e, RouteState.DEGRADING)
    assert d.action is Action.HOLD
    assert d.rule_fired == "R2_hold_route_degrading"


def test_business_failure_issues_link(settings, make_event):
    e = make_event(error_code="INSUFFICIENT_FUNDS")
    d = _decide(settings, e, RouteState.HEALTHY)
    assert d.action is Action.RECOVERY_LINK
    assert d.rule_fired == "R3_business_recovery_link"


def test_soft_technical_healthy_retries(settings, make_event):
    e = make_event(error_code="GATEWAY_TIMEOUT")
    d = _decide(settings, e, RouteState.HEALTHY)
    assert d.action is Action.RETRY
    assert d.rule_fired == "R4_safe_retry"


def test_unknown_is_stopped_not_retried(settings, make_event):
    e = make_event(error_code="MYSTERY")
    d = _decide(settings, e, RouteState.HEALTHY)
    assert d.action is Action.STOP
    assert d.rule_fired == "R6_unrecoverable"


def test_business_failure_never_retried_even_when_healthy(settings, make_event):
    # A hard failure on a perfectly healthy route must NOT be a retry.
    e = make_event(error_code="CARD_EXPIRED")
    d = _decide(settings, e, RouteState.HEALTHY)
    assert d.action is not Action.RETRY
