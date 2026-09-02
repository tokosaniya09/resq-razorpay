"""SQLAlchemy models for the audit ledger (§7).

The audit trail must *persist* — the design doc is explicit that we do not
rely on in-memory-only state. Every record that touches money is written
here, so the ledger is a full, honest reconstruction of who decided what,
why, and what happened.

Money is stored as integer paise. Never floats.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.domain import utcnow


class Base(DeclarativeBase):
    pass


class PaymentEventRow(Base):
    __tablename__ = "payment_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, index=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[str] = mapped_column(String)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    route: Mapped[str] = mapped_column(String, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DecisionRow(Base):
    __tablename__ = "recovery_decisions"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    rule_fired: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    attempt_number: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String, index=True)
    route_state: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutcomeRow(Base):
    __tablename__ = "recovery_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_event_id: Mapped[str] = mapped_column(String, index=True)
    result: Mapped[str] = mapped_column(String, index=True)
    amount_recovered: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutreachRow(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_event_id: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String, default="simulated")
    body: Mapped[str] = mapped_column(String)
    generated_by: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RouteHealthRow(Base):
    __tablename__ = "route_health_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    failure_rate: Mapped[int] = mapped_column(Integer)  # basis points (rate*10000)
    samples: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AiNoteRow(Base):
    """Persisted advisory AI output — diagnoses and escalation notes.

    Kept in one table (discriminated by `kind`) so the audit trail records
    not just what the engine decided, but what the AI advised alongside it.
    These rows never gate a money action; they are commentary for humans.
    """

    __tablename__ = "ai_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String, index=True)  # "diagnosis" | "escalation"
    route: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)  # txn/event id
    body: Mapped[str] = mapped_column(String)
    # one of: "llm" | "heuristic" | "template"
    generated_by: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
