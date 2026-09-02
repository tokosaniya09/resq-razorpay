"""Merchant escalation notes (advisory) — the "compliant escalation" bar.

When the deterministic engine STOPs on a payment — retries exhausted, or an
unrecoverable failure — a human on the merchant side may need to act (dunning,
manual follow-up, write-off). This drafts a short, factual escalation note for
that human. Like every other AI feature here it is text-only and advisory: it
summarizes a decision the engine already made and recommends a next step; it
never moves money or overrides a stopping rule.

Fails safe: with no LLM (or on error) it emits a deterministic templated note
from the same facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.domain import Decision, PaymentEvent
from app.services.llm.client import LLMClient

_SYSTEM = (
    "You write short internal escalation notes for a merchant's finance/ops "
    "team about a payment that could not be auto-recovered. 2-3 sentences, "
    "factual, plain English, no markdown, no emoji. State what was tried, why "
    "it stopped, and the recommended human next step (e.g. manual follow-up, "
    "dunning, or write-off). Do not promise anything to the customer."
)


@dataclass(frozen=True)
class Escalation:
    decision_event_id: str
    transaction_id: str
    body: str
    generated_by: str  # "llm" or "template"


class EscalationService:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self._s = settings
        self._llm = llm or LLMClient(settings)

    def draft(
        self, event: PaymentEvent, decision: Decision, reason_plain: str
    ) -> Escalation:
        amount = f"\u20b9{event.amount / 100:,.0f}"
        prompt = (
            f"Transaction: {event.transaction_id}\n"
            f"Amount: {amount}\n"
            f"Rail: {event.route}\n"
            f"Failure reason: {reason_plain}\n"
            f"Attempts made: {decision.attempt_number}\n"
            f"Stopping rule: {decision.rule_fired}\n"
            f"Engine decision: {decision.action.value} — {decision.reason}\n"
        )
        body = self._llm.complete(_SYSTEM, prompt, max_tokens=160)
        generated_by = "llm"
        if not body:
            body = self._template(event, decision, reason_plain, amount)
            generated_by = "template"
        return Escalation(
            decision_event_id=event.event_id,
            transaction_id=event.transaction_id,
            body=body,
            generated_by=generated_by,
        )

    def _template(self, event, decision, reason_plain, amount) -> str:
        return (
            f"Payment {event.transaction_id} ({amount} on {event.route}) could "
            f"not be auto-recovered after {decision.attempt_number} attempt(s); "
            f"stopped by rule {decision.rule_fired} ({reason_plain}). "
            f"Recommend manual follow-up or dunning; do not auto-retry."
        )
