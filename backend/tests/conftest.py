"""Shared test fixtures."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.domain import EventSource, PaymentEvent


@pytest.fixture
def settings() -> Settings:
    # Explicit, small thresholds keep tests fast and deterministic.
    return Settings(
        degradation_window_size=10,
        degradation_min_samples=4,
        degradation_warn_threshold=0.40,
        degradation_critical_threshold=0.65,
        recovering_threshold=0.25,
        recovering_drain_after_seconds=0,  # no wall-clock waits in tests
        max_retry_attempts=2,
        retry_cooldown_seconds=0,
    )


@pytest.fixture
def make_event():
    def _make(
        transaction_id: str = "txn_1",
        error_code: str | None = "GATEWAY_TIMEOUT",
        status: str = "failed",
        route: str = "UPI-HDFC",
        amount: int = 50000,
        idx: int = 0,
    ) -> PaymentEvent:
        return PaymentEvent(
            event_id=f"evt_{transaction_id}_{idx}",
            source=EventSource.SYNTHETIC,
            transaction_id=transaction_id,
            amount=amount,
            currency="INR",
            status=status,
            error_code=error_code,
            route=route,
        )

    return _make
