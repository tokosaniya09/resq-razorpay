"""Core domain types shared across every service.

These are plain, framework-free types (enums + dataclasses). Keeping the
domain vocabulary in one place means the classifier, degradation detector,
policy engine, executors and ledger all agree on what a `PaymentEvent`,
a `FailureClass` or a `RouteState` *is* — without importing FastAPI,
SQLAlchemy or Pydantic. That separation is what keeps the money path
unit-testable without spinning up a server or a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    """Timezone-aware UTC now. Used everywhere so timestamps are consistent."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Failure taxonomy — aligned with NPCI's Technical / Business decline split.
# --------------------------------------------------------------------------- #
class FailureClass(str, Enum):
    """NPCI-style split of every declined transaction.

    TECHNICAL — bank / acquirer / infrastructure side (timeout, server down).
                Soft: safe to retry *if the rail is healthy*. Spikes during
                outages, which is the signal the degradation detector watches.
    BUSINESS  — user side (insufficient funds, wrong PIN, expired card).
                Hard: blind retries cannot succeed and only waste attempts.
    UNKNOWN   — code we haven't mapped. Treated conservatively (never retried).
    """

    TECHNICAL = "TD"
    BUSINESS = "BD"
    UNKNOWN = "UNKNOWN"


class RouteState(str, Enum):
    """Health of a payment route/acquirer, driven by the degradation detector."""

    HEALTHY = "HEALTHY"
    DEGRADING = "DEGRADING"
    DOWN = "DOWN"
    RECOVERING = "RECOVERING"


class Action(str, Enum):
    """The bounded set of moves the policy engine may choose. Exactly one."""

    RETRY = "RETRY"          # re-attempt via the gateway (soft failure, healthy route)
    RECOVERY_LINK = "LINK"   # issue a fresh, bounded payment link (user-side failure)
    HOLD = "HOLD"            # back off; route is degrading/down — protect the customer
    STOP = "STOP"            # give up honestly (cap hit / unrecoverable)


class OutcomeResult(str, Enum):
    RECOVERED = "recovered"
    FAILED = "failed"
    HELD = "held"
    EXPIRED = "expired"
    STOPPED = "stopped"


class EventSource(str, Enum):
    RAZORPAY = "razorpay"
    SYNTHETIC = "synthetic"


# --------------------------------------------------------------------------- #
# Records that flow through the pipeline.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PaymentEvent:
    """A normalized payment event. Source-agnostic by design: downstream
    services never need to know whether it came from a real Razorpay webhook
    or the synthetic generator."""

    event_id: str
    source: EventSource
    transaction_id: str
    amount: int              # in paise (integer money — never floats)
    currency: str
    status: str              # e.g. "failed", "captured"
    error_code: str | None   # gateway error code, drives classification
    route: str               # acquirer / rail identifier, e.g. "UPI-HDFC"
    received_at: datetime = field(default_factory=utcnow)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Classification:
    event_id: str
    failure_class: FailureClass
    is_soft: bool
    mapped_reason: str        # human-readable, e.g. "Acquirer timeout"


@dataclass(frozen=True)
class Decision:
    event_id: str
    transaction_id: str
    action: Action
    rule_fired: str           # the exact rule id, for the audit trail
    reason: str               # plain-language justification
    attempt_number: int
    idempotency_key: str
    route_state: RouteState
    decided_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Outcome:
    decision_event_id: str
    result: OutcomeResult
    amount_recovered: int     # paise
    detail: str
    at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Outreach:
    decision_event_id: str
    channel: str              # "simulated" for the hackathon build
    body: str
    generated_by: str         # "llm" or "template"
    at: datetime = field(default_factory=utcnow)
