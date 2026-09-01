"""Recovery policy engine (§6.4).

Given a classified failure + current route health + transaction history,
choose exactly ONE bounded action. The rules are explicit and ordered so
that, for any input, you can point at the single rule that fired and explain
it in one sentence. That explainability is the whole reason this is code and
not a model: every money decision must be justifiable to a reviewer, an
auditor, or a customer.

Rule order (first match wins):

  R1  Route DOWN + technical failure        -> HOLD   (protect against dup charge)
  R2  Route DEGRADING + technical failure   -> HOLD   (be cautious near an outage)
  R3  Business (user-side) failure          -> LINK   (fresh bounded link + outreach)
  R4  Soft technical + healthy + under cap   -> RETRY  (safe re-attempt)
  R5  Retry cap reached                      -> STOP   (bounded, logged honestly)
  R6  Anything else / UNKNOWN                -> STOP   (never blind-retry the unknown)
"""

from __future__ import annotations

from app.models.domain import (
    Action,
    Classification,
    Decision,
    FailureClass,
    PaymentEvent,
    RouteState,
)
from app.services.policy.guardrails import Guardrails


class PolicyEngine:
    def __init__(self, guardrails: Guardrails) -> None:
        self._g = guardrails

    def decide(
        self,
        event: PaymentEvent,
        classification: Classification,
        route_state: RouteState,
    ) -> Decision:
        txn = event.transaction_id
        attempt = self._g.next_attempt_number(txn)
        key = self._g.idempotency_key(txn, attempt)

        action, rule, reason = self._select(event, classification, route_state)

        return Decision(
            event_id=event.event_id,
            transaction_id=txn,
            action=action,
            rule_fired=rule,
            reason=reason,
            attempt_number=attempt,
            idempotency_key=key,
            route_state=route_state,
        )

    # ----------------------------------------------------------------------- #
    def _select(
        self,
        event: PaymentEvent,
        cls: Classification,
        route: RouteState,
    ) -> tuple[Action, str, str]:
        txn = event.transaction_id
        is_technical = cls.failure_class == FailureClass.TECHNICAL
        is_business = cls.failure_class == FailureClass.BUSINESS

        # R1 — never fire money into a dead rail. This is the differentiator:
        # the naive baseline retries here and risks duplicate charges.
        if route == RouteState.DOWN and is_technical:
            return (
                Action.HOLD,
                "R1_hold_route_down",
                f"Route {event.route} is DOWN; holding to avoid a duplicate "
                f"charge and wasted fees. Will recover when the rail is healthy.",
            )

        # R2 — degrading rail: still cautious with technical failures.
        if route in (RouteState.DEGRADING, RouteState.RECOVERING) and is_technical:
            return (
                Action.HOLD,
                "R2_hold_route_degrading",
                f"Route {event.route} is {route.value}; holding technical "
                f"failures until it stabilises.",
            )

        # R3 — user-side failure: a fresh, bounded link is the right recovery.
        if is_business:
            return (
                Action.RECOVERY_LINK,
                "R3_business_recovery_link",
                f"User-side failure ({cls.mapped_reason}); issuing a fresh "
                f"bounded payment link with a clear customer message.",
            )

        # R4 — soft technical on a healthy rail, under the cap: safe retry.
        if is_technical and cls.is_soft and route == RouteState.HEALTHY:
            if self._g.retry_cap_reached(txn):
                return (
                    Action.STOP,
                    "R5_retry_cap_reached",
                    f"Retry cap ({self._g._s.max_retry_attempts}) reached for "
                    f"{txn}; stopping and logging as unrecoverable.",
                )
            return (
                Action.RETRY,
                "R4_safe_retry",
                f"Soft technical failure ({cls.mapped_reason}) on a healthy "
                f"route; safe retry attempt {self._g.next_attempt_number(txn)}.",
            )

        # R5 — cap reached in any other technical case.
        if is_technical and self._g.retry_cap_reached(txn):
            return (
                Action.STOP,
                "R5_retry_cap_reached",
                f"Retry cap reached for {txn}; stopping honestly.",
            )

        # R6 — unknown / unhandled: do nothing risky.
        return (
            Action.STOP,
            "R6_unrecoverable",
            f"No safe bounded recovery for {cls.failure_class.value} "
            f"({cls.mapped_reason}); marking unrecoverable rather than "
            f"guessing.",
        )
