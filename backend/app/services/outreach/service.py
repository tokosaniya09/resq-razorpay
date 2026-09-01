"""Isolated outreach service (§6.7).

Turns a structured recovery context into a short, clear customer message.
It calls the model only through the shared LLMClient, and returns only text —
it has no authority to move money. If the LLM is off or fails, it falls back
to a deterministic template, so recovery is never affected.

This is the original "AI in the right place" boundary: natural-language
generation on a side branch, walled off from the deterministic money path.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.domain import Decision, Outreach, PaymentEvent
from app.services.llm.client import LLMClient

_SYSTEM = (
    "You write short, warm payment-failure SMS messages for an Indian fintech. "
    "Plain Indian English, under 40 words, no emoji, no markdown. Always "
    "reassure the customer no money was deducted. Return only the message text."
)


@dataclass(frozen=True)
class OutreachContext:
    customer_first_name: str
    amount_rupees: str
    reason_plain: str          # e.g. "insufficient balance"
    link_url: str | None
    ttl_minutes: int


def _template_message(ctx: OutreachContext) -> str:
    link = (
        f" Here's a fresh, secure link to try again "
        f"(valid {ctx.ttl_minutes} min): {ctx.link_url}"
        if ctx.link_url
        else ""
    )
    return (
        f"Hi {ctx.customer_first_name}, your ₹{ctx.amount_rupees} payment "
        f"didn't go through ({ctx.reason_plain}).{link} "
        f"No amount was deducted."
    )


class OutreachService:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self._s = settings
        self._llm = llm or LLMClient(settings)

    def generate(
        self, event: PaymentEvent, decision: Decision, ctx: OutreachContext
    ) -> Outreach:
        prompt = (
            f"Name: {ctx.customer_first_name}\n"
            f"Amount: \u20b9{ctx.amount_rupees}\n"
            f"Reason (plain): {ctx.reason_plain}\n"
            f"Link: {ctx.link_url or 'none'} (valid {ctx.ttl_minutes}m)"
        )
        body = self._llm.complete(_SYSTEM, prompt, max_tokens=120)
        if body:
            return Outreach(
                decision_event_id=event.event_id,
                channel="simulated",
                body=body,
                generated_by="llm",
            )
        return Outreach(
            decision_event_id=event.event_id,
            channel="simulated",  # generated + displayed, not delivered (Non-Goal N2)
            body=_template_message(ctx),
            generated_by="template",
        )
