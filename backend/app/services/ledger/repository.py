"""Ledger repository — persistence for the audit trail (§6, §7).

Turns domain records into DB rows and back. The audit ledger is simply the
join of decisions to their outcomes: a complete trail of who decided what,
which rule fired, and what happened. Kept behind a repository so services
depend on methods, not on SQLAlchemy.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.db import (
    AiNoteRow,
    DecisionRow,
    OutcomeRow,
    OutreachRow,
    PaymentEventRow,
    RouteHealthRow,
)
from app.models.domain import Decision, Outcome, Outreach, PaymentEvent
from app.services.degradation.detector import HealthSnapshot


class LedgerRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    # -- writes ------------------------------------------------------------ #
    def record_event(self, e: PaymentEvent) -> None:
        if self._db.get(PaymentEventRow, e.event_id):
            return  # dedupe: webhooks can be redelivered
        self._db.add(
            PaymentEventRow(
                event_id=e.event_id,
                source=e.source.value,
                transaction_id=e.transaction_id,
                amount=e.amount,
                currency=e.currency,
                status=e.status,
                error_code=e.error_code,
                route=e.route,
                received_at=e.received_at,
                raw_payload=e.raw_payload,
            )
        )

    def record_decision(self, d: Decision) -> None:
        if self._db.get(DecisionRow, d.event_id):
            return
        self._db.add(
            DecisionRow(
                event_id=d.event_id,
                transaction_id=d.transaction_id,
                action=d.action.value,
                rule_fired=d.rule_fired,
                reason=d.reason,
                attempt_number=d.attempt_number,
                idempotency_key=d.idempotency_key,
                route_state=d.route_state.value,
                decided_at=d.decided_at,
            )
        )

    def record_outcome(self, o: Outcome) -> None:
        self._db.add(
            OutcomeRow(
                decision_event_id=o.decision_event_id,
                result=o.result.value,
                amount_recovered=o.amount_recovered,
                detail=o.detail,
                at=o.at,
            )
        )

    def record_outreach(self, m: Outreach) -> None:
        self._db.add(
            OutreachRow(
                decision_event_id=m.decision_event_id,
                channel=m.channel,
                body=m.body,
                generated_by=m.generated_by,
                at=m.at,
            )
        )

    def record_health(self, h: HealthSnapshot) -> None:
        self._db.add(
            RouteHealthRow(
                route=h.route,
                state=h.state.value,
                failure_rate=int(h.failure_rate * 10000),
                samples=h.samples,
                at=h.at,
            )
        )

    def record_ai_note(
        self, kind: str, body: str, generated_by: str,
        route: str | None = None, ref_id: str | None = None,
    ) -> None:
        self._db.add(
            AiNoteRow(
                kind=kind, route=route, ref_id=ref_id,
                body=body, generated_by=generated_by,
            )
        )

    def commit(self) -> None:
        self._db.commit()

    # -- reads ------------------------------------------------------------- #
    def recent_decisions(self, limit: int = 100) -> list[DecisionRow]:
        stmt = select(DecisionRow).order_by(DecisionRow.decided_at.desc()).limit(limit)
        return list(self._db.scalars(stmt))

    def all_outcomes(self) -> list[OutcomeRow]:
        return list(self._db.scalars(select(OutcomeRow)))

    def all_decisions(self) -> list[DecisionRow]:
        return list(self._db.scalars(select(DecisionRow)))

    def recent_outreach(self, limit: int = 50) -> list[OutreachRow]:
        stmt = select(OutreachRow).order_by(OutreachRow.at.desc()).limit(limit)
        return list(self._db.scalars(stmt))

    def recent_ai_notes(self, kind: str | None = None, limit: int = 50) -> list[AiNoteRow]:
        stmt = select(AiNoteRow).order_by(AiNoteRow.at.desc()).limit(limit)
        if kind:
            stmt = select(AiNoteRow).where(AiNoteRow.kind == kind).order_by(
                AiNoteRow.at.desc()).limit(limit)
        return list(self._db.scalars(stmt))
