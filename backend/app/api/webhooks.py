"""Ingest API (§6.1, §11).

The web layer is deliberately thin: parse the request, hand it to the
pipeline, broadcast the result. No business logic lives here. Two entry
points:

  POST /webhooks/razorpay   real Razorpay webhooks (signature-verified)
  POST /ingest/synthetic    the generator's internal endpoint (demo stream)
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from app.api.ws import broadcaster
from app.db.session import SessionLocal
from app.models.schemas import SyntheticEventIn
from app.services.ledger.repository import LedgerRepository

router = APIRouter()


@router.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
):
    pipeline = request.app.state.pipeline
    ingestion = request.app.state.ingestion
    gateway = pipeline.gateway

    body = await request.body()
    if not gateway.verify_webhook(body, x_razorpay_signature or ""):
        return {"ok": False, "error": "invalid signature"}

    payload = await request.json()
    event = ingestion.from_razorpay(payload)

    if ingestion.is_duplicate(event.event_id):
        return {"ok": True, "deduped": True, "event_id": event.event_id}
    ingestion.mark_seen(event.event_id)

    result = _run(pipeline, event)
    await _broadcast_all(result)
    return {"ok": True, "event_id": event.event_id}


@router.post("/ingest/synthetic")
async def ingest_synthetic(payload: SyntheticEventIn, request: Request):
    pipeline = request.app.state.pipeline
    ingestion = request.app.state.ingestion

    event = ingestion.from_synthetic(payload.model_dump())
    if ingestion.is_duplicate(event.event_id):
        return {"ok": True, "deduped": True}
    ingestion.mark_seen(event.event_id)

    result = _run(pipeline, event)
    await _broadcast_all(result)
    return {"ok": True, "frame": result["primary"]}


def _run(pipeline, event):
    """Runs the pipeline inside a short-lived DB session."""
    session = SessionLocal()
    try:
        ledger = LedgerRepository(session)
        return pipeline.process(event, ledger)
    finally:
        session.close()


async def _broadcast_all(result):
    """Broadcast the event's own frame, then any held payments that were
    drained (re-attempted) because their route just recovered."""
    await broadcaster.broadcast(result["primary"])
    for frame in result.get("drained", []):
        await broadcaster.broadcast(frame)
