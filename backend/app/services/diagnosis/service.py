"""Route degradation diagnosis (advisory) — Track 03: "degradation -> root cause".

When a payment rail crosses into DEGRADING or DOWN, this looks at the *cluster*
of recent failures on that route and produces a short, human-readable
root-cause summary, e.g.:

    "UPI-SBI: 14 failures in ~90s, 86% technical timeouts, spread across many
     customers and amounts — consistent with an acquirer-side outage rather
     than customer errors. Recommended: hold retries until the rail recovers."

Two hard boundaries, both important for this hackathon's bar:
  * It is ADVISORY. It explains what the deterministic engine already decided;
    it never chooses or changes a money action.
  * It fails safe. With no LLM (or on any error) it emits a deterministic
    heuristic summary from the same statistics — so the feature always works,
    the LLM just makes the wording better.

The statistics it reasons over are computed in code (counts, ratios, spread),
so the *numbers* are always trustworthy; the LLM only phrases them.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass

from app.core.config import Settings
from app.models.domain import PaymentEvent, RouteState
from app.services.classifier.service import classify
from app.services.llm.client import LLMClient

_SYSTEM = (
    "You are a payments reliability analyst. Given failure statistics for one "
    "payment rail, write a 2-3 sentence root-cause assessment for an on-call "
    "engineer. Be concrete and cite the numbers. State whether it looks like an "
    "acquirer/bank-side outage or customer-side issues, and end with the single "
    "recommended posture (hold, retry, or issue links). Plain English, no "
    "markdown, no emoji. Do not invent numbers beyond those given."
)


@dataclass(frozen=True)
class Diagnosis:
    route: str
    state: str
    body: str
    generated_by: str  # "llm" or "heuristic"
    failure_rate: float
    sample_size: int


@dataclass
class _FailRecord:
    error_code: str | None
    failure_class: str
    is_soft: bool
    amount: int


class DiagnosisService:
    def __init__(self, settings: Settings, llm: LLMClient | None = None) -> None:
        self._s = settings
        self._llm = llm or LLMClient(settings)
        # recent FAILED events per route (bounded), for cluster analysis
        self._recent: dict[str, deque[_FailRecord]] = {}
        self._window = settings.degradation_window_size

    def observe(self, event: PaymentEvent) -> None:
        """Feed every event; we retain only recent failures per route."""
        if event.status.lower() != "failed":
            return
        cls = classify(event)
        buf = self._recent.setdefault(event.route, deque(maxlen=self._window))
        buf.append(
            _FailRecord(
                error_code=event.error_code,
                failure_class=cls.failure_class.value,
                is_soft=cls.is_soft,
                amount=event.amount,
            )
        )

    def diagnose(self, route: str, state: RouteState, failure_rate: float) -> Diagnosis:
        """Summarize the current failure cluster on `route`. Advisory only."""
        records = list(self._recent.get(route, []))
        stats = self._stats(records, failure_rate)

        body = self._llm.complete(
            _SYSTEM, self._prompt(route, state, stats), max_tokens=180
        )
        generated_by = "llm"
        if not body:
            body = self._heuristic(route, state, stats)
            generated_by = "heuristic"

        return Diagnosis(
            route=route,
            state=state.value,
            body=body,
            generated_by=generated_by,
            failure_rate=round(failure_rate, 4),
            sample_size=len(records),
        )

    # -- internals ---------------------------------------------------------- #
    def _stats(self, records: list[_FailRecord], failure_rate: float) -> dict:
        n = len(records)
        tech = sum(1 for r in records if r.failure_class == "TD")
        biz = sum(1 for r in records if r.failure_class == "BD")
        codes = Counter(r.error_code or "UNKNOWN" for r in records)
        top_code, top_n = codes.most_common(1)[0] if codes else ("n/a", 0)
        amounts = [r.amount for r in records]
        distinct_amounts = len(set(amounts))
        return {
            "n": n,
            "failure_rate_pct": round(failure_rate * 100),
            "technical": tech,
            "business": biz,
            "technical_pct": round((tech / n) * 100) if n else 0,
            "top_code": top_code,
            "top_code_count": top_n,
            "distinct_amounts": distinct_amounts,
        }

    def _prompt(self, route: str, state: RouteState, s: dict) -> str:
        return (
            f"Rail: {route}\n"
            f"Detector state: {state.value}\n"
            f"Recent failures analysed: {s['n']}\n"
            f"Window failure rate: {s['failure_rate_pct']}%\n"
            f"Technical (bank/infra-side): {s['technical']} ({s['technical_pct']}%)\n"
            f"Business (customer-side): {s['business']}\n"
            f"Most common error code: {s['top_code']} x{s['top_code_count']}\n"
            f"Distinct amounts among failures: {s['distinct_amounts']} "
            f"(spread across customers suggests infra, not user error)\n"
        )

    def _heuristic(self, route: str, state: RouteState, s: dict) -> str:
        if s["technical_pct"] >= 60:
            cause = (
                f"predominantly technical ({s['technical_pct']}% bank/infra-side, "
                f"mostly {s['top_code']}), spread across {s['distinct_amounts']} "
                f"distinct amounts — consistent with an acquirer-side outage "
                f"rather than customer errors"
            )
            posture = "Hold retries until the rail recovers, then drain."
        elif s["business"] > s["technical"]:
            cause = (
                f"mostly customer-side ({s['business']} of {s['n']}), e.g. "
                f"{s['top_code']} — not an infrastructure outage"
            )
            posture = "Issue fresh payment links; do not retry blindly."
        else:
            cause = f"a mix of technical and customer-side failures ({s['n']} total)"
            posture = "Proceed cautiously; hold technical failures if the rate climbs."
        return (
            f"{route} is {state.value} at {s['failure_rate_pct']}% failure over "
            f"the last {s['n']} attempts: {cause}. {posture}"
        )
