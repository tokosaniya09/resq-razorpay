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

    def process(self, event: PaymentEvent, ledger: LedgerRepository) -> dict[str, Any]:
        # 1) classify (deterministic)
        classification = classify(event)

        # feed the diagnosis buffer with every event (tracks recent failures)
        self.diagnosis.observe(event)

        # 2) observe stream health for this route (successes AND failures both
        #    count toward a rail's health).
        health = self.detector.observe(event)

        # --- Successful payments need no recovery. --------------------------- #
        # A captured payment has nothing to classify, decide, or escalate — it
        # already succeeded. We only record it and let it improve the rail's
        # health (which may push the rail back to HEALTHY and trigger a drain of
        # previously held payments). Running the decision logic on successes was
        # a bug: they'd classify as UNKNOWN -> STOP and be miscounted as
        # "unrecoverable" (and fire escalation notes).
        if event.status.lower() != "failed":
            ledger.record_event(event)
            ledger.record_health(health)
            ledger.commit()
            drain_frames = self._maybe_drain(event.route, health, ledger)
            primary = self._captured_frame(event, health)
            return {"primary": primary, "drained": drain_frames}

        # --- Failed payments: the full recovery pipeline. ------------------- #
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
        #  - diagnosis ONCE when a rail first degrades (enters DEGRADING/DOWN
        #    from a healthy state), not on every threshold wiggle within the
        #    same outage — one root-cause analysis per episode is enough, and
        #    it keeps LLM usage low.
        #  - escalation note when we STOP (unrecoverable / cap reached)
        diagnosis = None
        entered_bad_state = (
            health.changed
            and health.state in (RouteState.DEGRADING, RouteState.DOWN)
            and health.previous_state in (RouteState.HEALTHY, RouteState.RECOVERING)
        )
        if entered_bad_state:
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
                "diagnosis",
                diagnosis.body,
                diagnosis.generated_by,
                route=diagnosis.route,
            )
        if escalation:
            ledger.record_ai_note(
                "escalation",
                escalation.body,
                escalation.generated_by,
                route=event.route,
                ref_id=event.transaction_id,
            )
        ledger.commit()

        # 6b) if this route is now healthy again, drain its held queue.
        drain_frames = self._maybe_drain(event.route, health, ledger)

        # 7) build the broadcast frame(s) for the dashboards
        primary = self._frame(
            event,
            classification,
            health,
            decision,
            outcome,
            outreach,
            diagnosis=diagnosis,
            escalation=escalation,
        )
        return {"primary": primary, "drained": drain_frames}

    # --------------------------------------------------------------------- #
    def _maybe_drain(
        self, current_route: str, health: HealthSnapshot, ledger: LedgerRepository
    ) -> list[dict[str, Any]]:
        """Re-attempt held payments for any rail that has recovered.

        Two design points that make this actually work in a live stream:

        * We check EVERY route that has a held queue on each event, not just
          the route of the current event — otherwise a rail that recovered
          would never drain if the next events happened to be for other rails.
        * We drain once a rail is HEALTHY *or* RECOVERING. RECOVERING means the
          failure rate has already dropped below the recovering threshold — the
          rail is materially working again — so this matches the design doc's
          "drain the hold queue gradually as it recovers" rather than waiting
          for a full return to HEALTHY (which a short window may never reach).

        Each re-attempt still goes through the SAME guardrails (idempotency +
        cap), so nothing can double-charge.
        """
        frames: list[dict[str, Any]] = []
        drainable = (RouteState.HEALTHY, RouteState.RECOVERING)

        for route in list(self._held.keys()):
            if self.detector.state_of(route) not in drainable:
                continue
            queued = self._held.pop(route, [])
            for held_event in queued:
                classification = classify(held_event)
                # Force the decision at HEALTHY: we've judged the rail recovered
                # enough to re-attempt, so this yields a RETRY (not another hold).
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
        if frames:
            ledger.commit()
        return frames

    # --------------------------------------------------------------------- #
    def _captured_frame(
        self, event: PaymentEvent, health: HealthSnapshot
    ) -> dict[str, Any]:
        """Frame for a successful payment: shown in the event stream, but with
        no decision/outcome (nothing was recovered — it simply succeeded)."""
        return {
            "type": "pipeline_event",
            "drained": False,
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
            "classification": None,
            "health": {
                "route": health.route,
                "state": health.state.value,
                "previous_state": health.previous_state.value,
                "failure_rate": health.failure_rate,
                "samples": health.samples,
                "changed": health.changed,
            },
            "decision": None,
            "outcome": None,
            "outreach": None,
            "diagnosis": None,
            "escalation": None,
        }

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
