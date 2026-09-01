"""The pipeline — orchestrates the whole money path.

This is the single place the stages are wired together, in order:

    ingest -> classify -> detect health -> decide (policy+guardrails)
           -> execute -> (outreach, if a link) -> persist to ledger
           -> broadcast to dashboards

Every stage is a pure-ish service that was built and tested in isolation; the
pipeline just sequences them and records the trail. Keeping orchestration
here (and out of the API layer) means the exact same logic runs whether an
event arrives via webhook, the synthetic generator, or a test — no server
required to exercise the money path.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.integrations.razorpay_client import RazorpayClient
from app.models.domain import (
    Action,
    Decision,
    Outcome,
    PaymentEvent,
    RouteState,
)
from app.services.classifier.service import classify
from app.services.degradation.detector import DegradationDetector, HealthSnapshot
from app.services.diagnosis.service import DiagnosisService
from app.services.escalation.service import EscalationService
from app.services.executors.executors import Executors
from app.services.ledger.repository import LedgerRepository
from app.services.llm.client import LLMClient
from app.services.outreach.service import OutreachContext, OutreachService
from app.services.policy.engine import PolicyEngine
from app.services.policy.guardrails import Guardrails


class Pipeline:
    """Holds the long-lived stateful services (detector, guardrails). The
    ledger repository is passed per-event because it wraps a DB session."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self.detector = DegradationDetector(settings)
        self.guardrails = Guardrails(settings)
        self.gateway = RazorpayClient(settings)
        self.policy = PolicyEngine(self.guardrails)
        self.executors = Executors(self.gateway, self.guardrails)
        # One shared LLM boundary for all advisory features (outreach,
        # diagnosis, escalation). None of them can touch the money path.
        self.llm = LLMClient(settings)
        self.outreach = OutreachService(settings, self.llm)
        self.diagnosis = DiagnosisService(settings, self.llm)
        self.escalation = EscalationService(settings, self.llm)
        # Payments we HELD because their route was unhealthy, keyed by route.
        # When the route recovers we re-attempt them (the RECOVERING state
        # doing its job live). This is what makes "held now, recovered later"
        # real in the running app, not just in the offline baseline.
        self._held: dict[str, list[PaymentEvent]] = {}

    def process(
        self, event: PaymentEvent, ledger: LedgerRepository
    ) -> dict[str, Any]:
        # 1) classify (deterministic)
        classification = classify(event)

        # feed the diagnosis buffer with every event (tracks recent failures)
        self.diagnosis.observe(event)

        # 2) observe stream health for this route
        health = self.detector.observe(event)

        # 3) decide exactly one bounded action
        decision = self.policy.decide(event, classification, health.state)

        # 4) execute
        outcome = self._execute(event, decision)

        # 5) outreach only for user-side recovery links (side branch, text only)
        outreach = None
        if decision.action == Action.RECOVERY_LINK:
            outreach = self._make_outreach(event, decision, classification, outcome)

        # 5b) if we held this payment, remember it so we can retry on recovery.
        if decision.action == Action.HOLD and classification.is_soft:
            self._held.setdefault(event.route, []).append(event)

        # 5c) ADVISORY AI (text only, never gates money):
        #  - diagnosis when a rail transitions into DEGRADING/DOWN
        #  - escalation note when we STOP (unrecoverable / cap reached)
        diagnosis = None
        if health.changed and health.state in (
            RouteState.DEGRADING, RouteState.DOWN
        ):
            diagnosis = self.diagnosis.diagnose(
                event.route, health.state, health.failure_rate
            )
        escalation = None
        if decision.action == Action.STOP:
            escalation = self.escalation.draft(
                event, decision, classification.mapped_reason
            )

        # 6) persist the full trail
        ledger.record_event(event)
        ledger.record_decision(decision)
        ledger.record_outcome(outcome)
        ledger.record_health(health)
        if outreach:
            ledger.record_outreach(outreach)
        if diagnosis:
            ledger.record_ai_note(
                "diagnosis", diagnosis.body, diagnosis.generated_by,
                route=diagnosis.route,
            )
        if escalation:
            ledger.record_ai_note(
                "escalation", escalation.body, escalation.generated_by,
                route=event.route, ref_id=event.transaction_id,
            )
        ledger.commit()

        # 6b) if this route is now healthy again, drain its held queue.
        drain_frames = self._maybe_drain(event.route, health, ledger)

        # 7) build the broadcast frame(s) for the dashboards
        primary = self._frame(
            event, classification, health, decision, outcome, outreach,
            diagnosis=diagnosis, escalation=escalation,
        )
        return {"primary": primary, "drained": drain_frames}

    # --------------------------------------------------------------------- #
    def _maybe_drain(
        self, route: str, health: HealthSnapshot, ledger: LedgerRepository
    ) -> list[dict[str, Any]]:
        """When a route returns to HEALTHY, re-attempt the payments we held
        during its outage. Each re-attempt goes through the SAME guardrails
        (idempotency + cap), so nothing can double-charge. Returns a frame per
        drained payment so the dashboard can show ₹ recovered climbing."""
        if health.state != RouteState.HEALTHY:
            return []
        queued = self._held.pop(route, [])
        if not queued:
            return []

        frames: list[dict[str, Any]] = []
        for held_event in queued:
            classification = classify(held_event)
            # Decide again now that the route is healthy — this yields RETRY.
            decision = self.policy.decide(
                held_event, classification, RouteState.HEALTHY
            )
            if decision.action != Action.RETRY:
                continue  # cap reached etc.; leave it alone, honestly
            outcome = self.executors.retry(held_event, decision)

            ledger.record_decision(decision)
            ledger.record_outcome(outcome)
            frames.append(
                self._frame(
                    held_event,
                    classification,
                    health,
                    decision,
                    outcome,
                    None,
                    drained=True,
                )
            )
        ledger.commit()
        return frames

    # --------------------------------------------------------------------- #
    def _execute(self, event: PaymentEvent, decision: Decision) -> Outcome:
        if decision.action == Action.RETRY:
            return self.executors.retry(event, decision)
        if decision.action == Action.RECOVERY_LINK:
            return self.executors.recovery_link(event, decision)
        if decision.action == Action.HOLD:
            return self.executors.hold(event, decision)
        return self.executors.stop(event, decision)

    def _make_outreach(self, event, decision, classification, outcome):
        # Pull the link URL out of the outcome detail for the message context.
        link = None
        if "https://" in outcome.detail:
            link = outcome.detail.split("(", 1)[-1].split(")", 1)[0]
        ctx = OutreachContext(
            customer_first_name=event.raw_payload.get("customer_name", "there"),
            amount_rupees=f"{event.amount / 100:,.0f}",
            reason_plain=classification.mapped_reason.lower(),
            link_url=link,
            ttl_minutes=self._s.recovery_link_ttl_minutes,
        )
        return self.outreach.generate(event, decision, ctx)

    def _frame(
        self,
        event: PaymentEvent,
        classification,
        health: HealthSnapshot,
        decision: Decision,
        outcome: Outcome,
        outreach,
        drained: bool = False,
        diagnosis=None,
        escalation=None,
    ) -> dict[str, Any]:
        return {
            "type": "pipeline_event",
            "drained": drained,  # True = a held payment re-attempted on recovery
            "event": {
                "event_id": event.event_id,
                "transaction_id": event.transaction_id,
                "amount": event.amount,
                "route": event.route,
                "status": event.status,
                "error_code": event.error_code,
                "source": event.source.value,
                "received_at": event.received_at.isoformat(),
            },
            "classification": {
                "class": classification.failure_class.value,
                "is_soft": classification.is_soft,
                "reason": classification.mapped_reason,
            },
            "health": {
                "route": health.route,
                "state": health.state.value,
                "previous_state": health.previous_state.value,
                "failure_rate": health.failure_rate,
                "samples": health.samples,
                "changed": health.changed,
            },
            "decision": {
                "action": decision.action.value,
                "rule_fired": decision.rule_fired,
                "reason": decision.reason,
                "attempt_number": decision.attempt_number,
                "route_state": decision.route_state.value,
            },
            "outcome": {
                "result": outcome.result.value,
                "amount_recovered": outcome.amount_recovered,
                "detail": outcome.detail,
            },
            "outreach": (
                {
                    "body": outreach.body,
                    "generated_by": outreach.generated_by,
                    "channel": outreach.channel,
                }
                if outreach
                else None
            ),
            "diagnosis": (
                {
                    "route": diagnosis.route,
                    "state": diagnosis.state,
                    "body": diagnosis.body,
                    "generated_by": diagnosis.generated_by,
                    "failure_rate": diagnosis.failure_rate,
                    "sample_size": diagnosis.sample_size,
                }
                if diagnosis
                else None
            ),
            "escalation": (
                {
                    "transaction_id": escalation.transaction_id,
                    "body": escalation.body,
                    "generated_by": escalation.generated_by,
                }
                if escalation
                else None
            ),
        }
