"""End-to-end integration tests.

Unit tests check each service in isolation; these check that the whole
pipeline actually wires together and *persists* — an event goes in, and a
decision + outcome (+ outreach, when a link is issued) come out and land in
the ledger. This is the layer that catches "it works in a unit test but the
real object is missing a field" bugs — exactly the class of bug that the
`Outreach.at` regression was.

Runs against a real in-memory SQLite database, so it exercises the actual
SQLAlchemy models and repository, not mocks.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.models.db import Base
from app.models.domain import Action, EventSource, PaymentEvent
from app.pipeline import Pipeline
from app.services.ledger.repository import LedgerRepository


@pytest.fixture
def db_session():
    # A fresh in-memory database per test.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def pipeline():
    return Pipeline(
        Settings(
            degradation_window_size=10,
            degradation_min_samples=4,
            degradation_critical_threshold=0.65,
            recovering_drain_after_seconds=0,
            max_retry_attempts=5,
            retry_cooldown_seconds=0,
            llm_enabled=False,  # template path — no network in tests
        )
    )


def _event(idx, code, status="failed", route="UPI-HDFC", amount=99900):
    return PaymentEvent(
        event_id=f"evt_{idx}",
        source=EventSource.SYNTHETIC,
        transaction_id=f"txn_{idx}",
        amount=amount,
        currency="INR",
        status=status,
        error_code=code,
        route=route,
        raw_payload={"customer_name": "Test"},
    )


def test_business_failure_persists_decision_outcome_and_outreach(pipeline, db_session):
    """A user-side failure should produce a LINK decision, an outcome, AND an
    outreach row — the exact path that used to 500 on the missing timestamp."""
    ledger = LedgerRepository(db_session)
    result = pipeline.process(_event(1, "INSUFFICIENT_FUNDS"), ledger)

    assert result["primary"]["decision"]["action"] == Action.RECOVERY_LINK.value

    # everything landed in the ledger
    assert len(ledger.all_decisions()) == 1
    assert len(ledger.all_outcomes()) == 1
    outreach = ledger.recent_outreach()
    assert len(outreach) == 1
    assert outreach[0].generated_by == "template"
    assert outreach[0].at is not None  # the regression guard


def test_technical_failure_on_healthy_route_retries_and_logs(pipeline, db_session):
    ledger = LedgerRepository(db_session)
    result = pipeline.process(_event(2, "GATEWAY_TIMEOUT"), ledger)
    assert result["primary"]["decision"]["action"] == Action.RETRY.value
    decisions = ledger.all_decisions()
    assert decisions[0].rule_fired == "R4_safe_retry"


def test_full_outage_then_recovery_drains_held_payments(pipeline, db_session):
    """The headline behaviour: hold during an outage, then recover the held
    payments when the route returns to healthy — end to end, persisted."""
    ledger = LedgerRepository(db_session)

    # Drive the route DOWN; technical failures get held.
    held = 0
    for i in range(9):
        r = pipeline.process(_event(100 + i, "GATEWAY_TIMEOUT", route="UPI-SBI"), ledger)
        if r["primary"]["decision"]["action"] == Action.HOLD.value:
            held += 1
    assert held > 0

    # Recover the route with successes; the held queue should drain.
    drained = 0
    for i in range(15):
        r = pipeline.process(
            _event(200 + i, None, status="captured", route="UPI-SBI"), ledger
        )
        drained += len(r.get("drained", []))

    assert drained > 0
    # Nothing left holding once healthy.
    assert pipeline._held.get("UPI-SBI", []) == []


def test_duplicate_event_is_not_double_recorded(pipeline, db_session):
    ledger = LedgerRepository(db_session)
    ev = _event(9, "GATEWAY_TIMEOUT")
    pipeline.process(ev, ledger)
    pipeline.process(ev, ledger)  # same event id again
    # The event row is deduped; we never store the same event twice.
    from app.models.db import PaymentEventRow

    rows = db_session.query(PaymentEventRow).filter_by(event_id="evt_9").all()
    assert len(rows) == 1
