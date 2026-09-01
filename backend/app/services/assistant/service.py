"""Natural-language ledger assistant (Feature #4).

A plain-English question box over the audit trail: "how much did we rescue
during the outage?", "why did we hold payments on UPI-SBI?", "which rail is
least reliable?".

The safety design is the whole point, and mirrors the rest of the system:

    the CODE computes the facts; the LLM only phrases them.

We never let the model invent numbers or touch the database. Instead we build
a compact, verified snapshot of the ledger in code (metrics + recent decisions
+ current route health) and pass it to the model as the ONLY ground truth it
may use, with an explicit instruction not to state anything not in the data.
So every figure in the answer is real and traceable to the ledger; the AI
contributes wording, not facts. It can read and explain — never change or
decide.

If the LLM is disabled or fails, a deterministic responder answers the most
common questions directly from the same snapshot, so the box still works with
no key (just more terse).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from app.core.config import Settings
from app.services.degradation.detector import DegradationDetector
from app.services.ledger import metrics as metrics_mod
from app.services.ledger.repository import LedgerRepository
from app.services.llm.client import LLMClient

_SYSTEM = (
    "You are a read-only analyst for a payment-recovery system. Answer the "
    "user's question ONLY from the JSON ledger snapshot provided. Every number "
    "you state must come from that JSON — never invent or estimate figures. If "
    "the snapshot doesn't contain the answer, say so plainly. Be concise (2-4 "
    "sentences), plain English, no markdown, rupee amounts as \u20b9. You have no "
    "power to change anything; you only explain what the system recorded."
)


@dataclass(frozen=True)
class AssistantAnswer:
    question: str
    answer: str
    generated_by: str          # "llm" or "deterministic"
    snapshot: dict             # the exact facts used, for transparency


class LedgerAssistant:
    def __init__(
        self,
        settings: Settings,
        detector: DegradationDetector,
        llm: LLMClient | None = None,
    ) -> None:
        self._s = settings
        self._detector = detector
        self._llm = llm or LLMClient(settings)

    def answer(self, question: str, repo: LedgerRepository) -> AssistantAnswer:
        snapshot = self._snapshot(repo)
        prompt = (
            f"Ledger snapshot (the only facts you may use):\n"
            f"{json.dumps(snapshot, indent=2)}\n\n"
            f"Question: {question}"
        )
        body = self._llm.complete(_SYSTEM, prompt, max_tokens=250)
        if body:
            return AssistantAnswer(question, body, "llm", snapshot)
        return AssistantAnswer(
            question, self._deterministic(question, snapshot), "deterministic",
            snapshot,
        )

    # -- build the verified fact snapshot ---------------------------------- #
    def _snapshot(self, repo: LedgerRepository) -> dict:
        m = metrics_mod.compute(repo)
        decisions = repo.all_decisions()

        by_action = Counter(d.action for d in decisions)
        by_rule = Counter(d.rule_fired for d in decisions)

        routes = [
            {
                "route": h.route,
                "state": h.state.value,
                "failure_rate_pct": round(h.failure_rate * 100),
                "samples": h.samples,
            }
            for h in self._detector.snapshot_all()
        ]

        return {
            "totals": {
                "rupees_rescued": m.rupees_rescued,
                "payments_recovered": m.recovered,
                "recovery_rate_pct": round(m.recovery_rate * 100),
                "recovery_links_issued": m.links_issued,
                "risky_retries_avoided_during_degradation": m.retries_avoided_degraded,
                "wasted_hard_retries_avoided": m.wasted_retries_avoided,
                "unrecoverable_stopped": m.unrecoverable,
                "total_decisions": m.total_events,
            },
            "decisions_by_action": dict(by_action),
            "decisions_by_rule": dict(by_rule),
            "route_health": routes,
        }

    # -- fallback when no LLM ---------------------------------------------- #
    def _deterministic(self, question: str, snap: dict) -> str:
        q = question.lower()
        t = snap["totals"]
        if any(w in q for w in ("unrecover", "stop", "give up", "gave up")):
            return (
                f"{t['unrecoverable_stopped']} payments were marked "
                f"unrecoverable and stopped honestly (e.g. hard declines or "
                f"retry cap reached), rather than retried blindly."
            )
        if any(w in q for w in ("hold", "why", "suspend", "outage", "down")):
            return (
                f"Retries were held while rails were degrading/down: "
                f"{t['risky_retries_avoided_during_degradation']} risky retries "
                f"into failing rails were avoided, preventing duplicate-charge "
                f"risk. Held payments are re-attempted once the rail recovers."
            )
        if any(w in q for w in ("reliable", "worst", "health", "rail", "route")):
            rows = ", ".join(
                f"{r['route']} {r['state']} ({r['failure_rate_pct']}%)"
                for r in snap["route_health"]
            ) or "no route data yet"
            return f"Current rail health: {rows}."
        money_words = ("rescue", "recover", "money", "rupee", "\u20b9", "amount")
        if any(w in q for w in money_words):
            return (
                f"\u20b9{t['rupees_rescued']:,.0f} rescued across "
                f"{t['payments_recovered']} recovered payments "
                f"({t['recovery_rate_pct']}% of recoverable), plus "
                f"{t['recovery_links_issued']} recovery links issued."
            )
        return (
            f"So far: \u20b9{t['rupees_rescued']:,.0f} rescued, "
            f"{t['payments_recovered']} recovered, "
            f"{t['risky_retries_avoided_during_degradation']} risky retries "
            f"avoided, {t['recovery_links_issued']} links issued, "
            f"{t['unrecoverable_stopped']} unrecoverable."
        )
