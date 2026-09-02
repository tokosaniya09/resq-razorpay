"""The classification table: gateway error code -> failure family.

This is deliberately a plain data table, not a model. The design doc's
headline point is *the right tool in the right place*: classifying a known,
finite set of error codes is exactly the kind of task where a deterministic
lookup is more reliable, faster and fully auditable — an LLM here would only
add latency and non-determinism to a money-critical path.

Each row records:
  - the failure family (TECHNICAL / BUSINESS),
  - whether it is "soft" (transient, retryable when the rail is healthy),
  - a human-readable reason for the audit trail.

Codes cover Razorpay-style errors and the NPCI TD/BD vocabulary. Anything
not in the table is classified UNKNOWN and treated conservatively (the policy
engine never blind-retries UNKNOWN).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import FailureClass


@dataclass(frozen=True)
class ClassRule:
    failure_class: FailureClass
    is_soft: bool
    reason: str


# error_code (upper-cased) -> ClassRule
CLASSIFICATION_TABLE: dict[str, ClassRule] = {
    # ---- Technical Decline (TD): bank / acquirer / infra side, soft ---- #
    "GATEWAY_ERROR": ClassRule(FailureClass.TECHNICAL, True, "Gateway error"),
    "GATEWAY_TIMEOUT": ClassRule(FailureClass.TECHNICAL, True, "Gateway timeout"),
    "NETWORK_TIMEOUT": ClassRule(FailureClass.TECHNICAL, True, "Network timeout"),
    "ACQUIRER_TIMEOUT": ClassRule(FailureClass.TECHNICAL, True, "Acquirer timeout"),
    "SERVER_ERROR": ClassRule(FailureClass.TECHNICAL, True, "Acquirer server error"),
    "SERVER_UNAVAILABLE": ClassRule(FailureClass.TECHNICAL, True, "Acquirer unavailable"),
    "ISSUER_DOWN": ClassRule(FailureClass.TECHNICAL, True, "Issuing bank down"),
    "BANK_ERROR": ClassRule(FailureClass.TECHNICAL, True, "Bank-side error"),
    "UPI_TECHNICAL_DECLINE": ClassRule(
        FailureClass.TECHNICAL, True, "UPI technical decline (NPCI TD)"
    ),
    # ---- Business Decline (BD): user side, hard (not blind-retryable) ---- #
    "INSUFFICIENT_FUNDS": ClassRule(FailureClass.BUSINESS, False, "Insufficient funds"),
    "BAD_REQUEST_ERROR": ClassRule(
        FailureClass.BUSINESS, False, "Invalid payment request"
    ),
    "INCORRECT_PIN": ClassRule(FailureClass.BUSINESS, False, "Incorrect UPI PIN"),
    "CARD_EXPIRED": ClassRule(FailureClass.BUSINESS, False, "Card expired"),
    "CARD_DECLINED": ClassRule(FailureClass.BUSINESS, False, "Card declined by issuer"),
    "PAYMENT_CANCELLED": ClassRule(FailureClass.BUSINESS, False, "Cancelled by customer"),
    "INVALID_ACCOUNT": ClassRule(FailureClass.BUSINESS, False, "Invalid account"),
    "LIMIT_EXCEEDED": ClassRule(FailureClass.BUSINESS, False, "Per-txn limit exceeded"),
    "AUTHENTICATION_FAILED": ClassRule(
        FailureClass.BUSINESS, False, "Authentication failed"
    ),
}

UNKNOWN_RULE = ClassRule(FailureClass.UNKNOWN, False, "Unmapped error code")


def lookup(error_code: str | None) -> ClassRule:
    """Pure lookup. Case-insensitive; None / unknown -> UNKNOWN_RULE."""
    if not error_code:
        return UNKNOWN_RULE
    return CLASSIFICATION_TABLE.get(error_code.strip().upper(), UNKNOWN_RULE)
