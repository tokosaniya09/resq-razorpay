"""Guardrails — the safety contract (§6.5).

This is the layer that makes "we never double-charge" and "retries are
bounded" *true by construction* rather than by hope. It tracks, per
transaction:

  - how many recovery attempts have been made (hard cap),
  - when the last attempt was (cooldown window),
  - which idempotency keys have already been executed (dedupe / no double-run).

The policy engine consults these before choosing an action; the executors
consult them again at execution time. Two independent checks on the money
path is deliberate defence in depth.

Idempotency key format is stable and derived from (transaction_id, attempt),
so the *same logical recovery* always produces the *same key* — meaning a
duplicated event can never trigger a second execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.config import Settings
from app.models.domain import utcnow


@dataclass
class TxnState:
    transaction_id: str
    attempts: int = 0
    last_attempt_at: datetime | None = None
    executed_keys: set[str] = field(default_factory=set)


class Guardrails:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._txns: dict[str, TxnState] = {}

    # -- queries used by the policy engine --------------------------------- #
    def attempts_made(self, transaction_id: str) -> int:
        st = self._txns.get(transaction_id)
        return st.attempts if st else 0

    def retry_cap_reached(self, transaction_id: str) -> bool:
        return self.attempts_made(transaction_id) >= self._s.max_retry_attempts

    def in_cooldown(self, transaction_id: str, now: datetime | None = None) -> bool:
        st = self._txns.get(transaction_id)
        if not st or st.last_attempt_at is None:
            return False
        now = now or utcnow()
        elapsed = (now - st.last_attempt_at).total_seconds()
        return elapsed < self._s.retry_cooldown_seconds

    def next_attempt_number(self, transaction_id: str) -> int:
        return self.attempts_made(transaction_id) + 1

    def idempotency_key(self, transaction_id: str, attempt: int) -> str:
        """Deterministic key. Same (txn, attempt) -> same key, always."""
        return f"resq:{transaction_id}:attempt:{attempt}"

    # -- mutations at execution time --------------------------------------- #
    def already_executed(self, key: str) -> bool:
        return any(key in st.executed_keys for st in self._txns.values())

    def register_execution(self, transaction_id: str, key: str) -> bool:
        """Record an execution. Returns False if this key already ran
        (the caller must then NOT execute again). This is the hard stop
        against double-charging."""
        st = self._state(transaction_id)
        if key in st.executed_keys:
            return False
        st.executed_keys.add(key)
        st.attempts += 1
        st.last_attempt_at = utcnow()
        return True

    def amount_within_cap(self, amount_paise: int) -> bool:
        return 0 < amount_paise <= self._s.recovery_link_amount_cap_paise

    # -- internals --------------------------------------------------------- #
    def _state(self, transaction_id: str) -> TxnState:
        if transaction_id not in self._txns:
            self._txns[transaction_id] = TxnState(transaction_id=transaction_id)
        return self._txns[transaction_id]
