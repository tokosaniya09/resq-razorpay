"""Ingestion & normalization (§6.1).

Two sources — real Razorpay webhooks and our synthetic generator — are
normalized into one internal `PaymentEvent` so nothing downstream cares where
an event came from. Deduplication happens here (by event id) because webhooks
can be redelivered.
"""

from __future__ import annotations

from typing import Any

from app.models.domain import EventSource, PaymentEvent, utcnow


class IngestionService:
    def __init__(self) -> None:
        self._seen_ids: set[str] = set()

    def is_duplicate(self, event_id: str) -> bool:
        return event_id in self._seen_ids

    def mark_seen(self, event_id: str) -> None:
        self._seen_ids.add(event_id)

    # -- Razorpay webhook payload -> PaymentEvent -------------------------- #
    def from_razorpay(self, payload: dict[str, Any]) -> PaymentEvent:
        """Normalize a Razorpay `payment.*` webhook body.

        Razorpay nests the entity under payload.payment.entity; we defend
        against missing fields so a malformed webhook can't crash the path.
        """
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        event_id = payload.get("id") or entity.get("id") or f"evt_{utcnow().timestamp()}"
        return PaymentEvent(
            event_id=str(event_id),
            source=EventSource.RAZORPAY,
            transaction_id=str(entity.get("order_id") or entity.get("id") or event_id),
            amount=int(entity.get("amount") or 0),
            currency=str(entity.get("currency") or "INR"),
            status="failed" if payload.get("event") == "payment.failed" else "captured",
            error_code=(entity.get("error_reason") or entity.get("error_code")),
            route=self._route_from(entity),
            received_at=utcnow(),
            raw_payload=payload,
        )

    # -- synthetic event dict -> PaymentEvent ------------------------------ #
    def from_synthetic(self, data: dict[str, Any]) -> PaymentEvent:
        return PaymentEvent(
            event_id=str(data["event_id"]),
            source=EventSource.SYNTHETIC,
            transaction_id=str(data["transaction_id"]),
            amount=int(data["amount"]),
            currency=str(data.get("currency", "INR")),
            status=str(data.get("status", "failed")),
            error_code=data.get("error_code"),
            route=str(data.get("route", "UPI-HDFC")),
            received_at=utcnow(),
            raw_payload=data,
        )

    @staticmethod
    def _route_from(entity: dict[str, Any]) -> str:
        method = (entity.get("method") or "UPI").upper()
        bank = entity.get("bank") or entity.get("acquirer_data", {}).get("bank") or "HDFC"
        return f"{method}-{bank}"
