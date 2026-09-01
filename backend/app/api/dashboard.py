"""Dashboard REST API (§6.8).

Read-only endpoints that back the dashboard panes and let a reviewer inspect
the audit trail without the UI. Thin: each handler opens a session, reads via
the repository / metrics module, returns JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.db.session import SessionLocal
from app.services.ledger import metrics as metrics_mod
from app.services.ledger.repository import LedgerRepository

router = APIRouter()


@router.get("/api/metrics")
def get_metrics():
    session = SessionLocal()
    try:
        repo = LedgerRepository(session)
        return metrics_mod.compute(repo).as_dict()
    finally:
        session.close()


@router.get("/api/health-routes")
def get_route_health(request: Request):
    detector = request.app.state.pipeline.detector
    return [
        {
            "route": h.route,
            "state": h.state.value,
            "failure_rate": h.failure_rate,
            "samples": h.samples,
        }
        for h in detector.snapshot_all()
    ]


@router.get("/api/ledger")
def get_ledger(limit: int = 100):
    """The audit trail: decisions joined to their latest outcome."""
    session = SessionLocal()
    try:
        repo = LedgerRepository(session)
        decisions = repo.recent_decisions(limit=limit)
        outcomes = {o.decision_event_id: o for o in repo.all_outcomes()}
        rows = []
        for d in decisions:
            o = outcomes.get(d.event_id)
            rows.append(
                {
                    "event_id": d.event_id,
                    "transaction_id": d.transaction_id,
                    "action": d.action,
                    "rule_fired": d.rule_fired,
                    "reason": d.reason,
                    "attempt_number": d.attempt_number,
                    "route_state": d.route_state,
                    "decided_at": d.decided_at.isoformat(),
                    "result": o.result if o else None,
                    "amount_recovered": o.amount_recovered if o else 0,
                    "detail": o.detail if o else None,
                }
            )
        return rows
    finally:
        session.close()


@router.get("/api/ai-notes")
def get_ai_notes(kind: str | None = None, limit: int = 50):
    """Advisory AI output (root-cause diagnoses + escalation notes) for the
    audit trail. These never gate a money action; they are analyst commentary."""
    session = SessionLocal()
    try:
        repo = LedgerRepository(session)
        return [
            {
                "kind": n.kind,
                "route": n.route,
                "ref_id": n.ref_id,
                "body": n.body,
                "generated_by": n.generated_by,
                "at": n.at.isoformat(),
            }
            for n in repo.recent_ai_notes(kind=kind, limit=limit)
        ]
    finally:
        session.close()


@router.get("/api/outreach")
def get_outreach(limit: int = 50):
    session = SessionLocal()
    try:
        repo = LedgerRepository(session)
        return [
            {
                "decision_event_id": m.decision_event_id,
                "body": m.body,
                "generated_by": m.generated_by,
                "channel": m.channel,
                "at": m.at.isoformat(),
            }
            for m in repo.recent_outreach(limit=limit)
        ]
    finally:
        session.close()
