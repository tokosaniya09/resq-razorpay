"""Action executors (§6.6).

One small executor per action. Each is isolated and independently testable.
Every executor that moves money re-checks idempotency at execution time via
the guardrails — a second line of defence after the policy engine, so a
duplicated decision physically cannot execute twice.

An executor never *decides* anything; it only carries out the single action
the policy engine already chose, and reports a structured Outcome.
"""

from __future__ import annotations

from app.integrations.razorpay_client import RazorpayClient
from app.models.domain import (
    Decision,
    Outcome,
    OutcomeResult,
    PaymentEvent,
    RouteState,
)
from app.services.policy.guardrails import Guardrails


class Executors:
    def __init__(self, gateway: RazorpayClient, guardrails: Guardrails) -> None:
        self._gw = gateway
        self._g = guardrails

    # --- RETRY ------------------------------------------------------------- #
    def retry(self, event: PaymentEvent, decision: Decision) -> Outcome:
        # Hard idempotency stop: register the execution first. If the key was
        # already used, we refuse — this is the "never double-charge" gate.
        if not self._g.register_execution(event.transaction_id, decision.idempotency_key):
            return Outcome(
                decision_event_id=event.event_id,
                result=OutcomeResult.STOPPED,
                amount_recovered=0,
                detail="Duplicate idempotency key — execution refused.",
            )

        healthy = decision.route_state == RouteState.HEALTHY
        res = self._gw.retry_payment(
            transaction_id=event.transaction_id,
            amount_paise=event.amount,
            idempotency_key=decision.idempotency_key,
            route_healthy=healthy,
        )
        if res.ok:
            return Outcome(
                decision_event_id=event.event_id,
                result=OutcomeResult.RECOVERED,
                amount_recovered=event.amount,
                detail=f"Retry captured ({res.reference}).",
            )
        return Outcome(
            decision_event_id=event.event_id,
            result=OutcomeResult.FAILED,
            amount_recovered=0,
            detail=f"Retry did not capture: {res.detail}.",
        )

    # --- RECOVERY LINK ----------------------------------------------------- #
    def recovery_link(self, event: PaymentEvent, decision: Decision) -> Outcome:
        if not self._g.amount_within_cap(event.amount):
            return Outcome(
                decision_event_id=event.event_id,
                result=OutcomeResult.STOPPED,
                amount_recovered=0,
                detail="Amount exceeds recovery-link cap — refused.",
            )
        if not self._g.register_execution(event.transaction_id, decision.idempotency_key):
            return Outcome(
                decision_event_id=event.event_id,
                result=OutcomeResult.STOPPED,
                amount_recovered=0,
                detail="Duplicate idempotency key — link not re-issued.",
            )

        link = self._gw.create_payment_link(
            transaction_id=event.transaction_id,
            amount_paise=event.amount,
            idempotency_key=decision.idempotency_key,
        )
        if link.ok:
            # The link is issued; the *actual* recovery happens when the user
            # pays. We record it as HELD (awaiting customer action), honestly —
            # we do not claim revenue we haven't captured.
            return Outcome(
                decision_event_id=event.event_id,
                result=OutcomeResult.HELD,
                amount_recovered=0,
                detail=f"Recovery link issued ({link.url}), TTL "
                f"{self._g._s.recovery_link_ttl_minutes}m, awaiting customer.",
            )
        return Outcome(
            decision_event_id=event.event_id,
            result=OutcomeResult.FAILED,
            amount_recovered=0,
            detail="Failed to issue recovery link.",
        )

    # --- HOLD -------------------------------------------------------------- #
    def hold(self, event: PaymentEvent, decision: Decision) -> Outcome:
        # No gateway call. Enqueue for re-evaluation when the route recovers.
        return Outcome(
            decision_event_id=event.event_id,
            result=OutcomeResult.HELD,
            amount_recovered=0,
            detail="Held — will re-evaluate when the route returns to HEALTHY.",
        )

    # --- STOP -------------------------------------------------------------- #
    def stop(self, event: PaymentEvent, decision: Decision) -> Outcome:
        return Outcome(
            decision_event_id=event.event_id,
            result=OutcomeResult.STOPPED,
            amount_recovered=0,
            detail=decision.reason,
        )
