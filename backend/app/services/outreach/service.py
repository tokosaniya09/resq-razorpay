"""Customer outreach (§6.7).

Turns a recovery context into a short, clear customer message.

Deliberate design choice: this uses a **deterministic template**, not an LLM.
The message is a fixed factual notice — "your payment failed, here's a fresh
link, no money was deducted" — and a good template says everything it needs to.
Spending an LLM call (latency, cost, a rate-limit risk on a live demo) to
reword a sentence that is already correct would add nothing. So we don't.

This is the same principle as the rest of the system, applied honestly to our
own feature: use AI only where it adds judgment or adaptation, not everywhere.
The one place AI *would* help here is writing the message in the customer's
language (Hinglish / regional). That is left as a clearly-marked seam below,
off by default — if turned on, it is the only case that calls the model.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.models.domain import Decision, Outreach, PaymentEvent
from app.services.llm.client import LLMClient


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
        f"Hi {ctx.customer_first_name}, your \u20b9{ctx.amount_rupees} payment "
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
        # Only reach for the model when a non-English target language is
        # configured — the sole case where an LLM beats the template here.
        target_lang = getattr(self._s, "outreach_language", "en")
        if self._llm.enabled and target_lang != "en":
            body = self._llm.complete(
                f"Translate this payment-failure SMS into {target_lang}. Keep it "
                f"under 40 words, plain, no emoji, no markdown. Return only the "
                f"message.",
                _template_message(ctx),
                max_tokens=120,
            )
            if body:
                return Outreach(
                    decision_event_id=event.event_id,
                    channel="simulated",
                    body=body,
                    generated_by="llm",
                )

        # Default path: deterministic template. No LLM call, no tokens spent.
        return Outreach(
            decision_event_id=event.event_id,
            channel="simulated",  # generated + displayed, not delivered (Non-Goal N2)
            body=_template_message(ctx),
            generated_by="template",
        )
