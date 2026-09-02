"""Razorpay adapter — the ONLY module that talks to the gateway (§11).

All vendor calls funnel through here (the adapter pattern), so:
  - swapping to a mock for demos touches one file,
  - a future SDK change touches one file,
  - the rest of the codebase depends on our small, stable interface, never
    on Razorpay's SDK surface.

Two modes:
  MOCK (default)  — no network, deterministic-ish responses. Lets the whole
                    project run clone-and-go, and makes the demo repeatable.
                    A retry into a route the caller marks "unhealthy" is
                    modelled as likely-failing, matching reality.
  REAL            — uses the Razorpay Python SDK against TEST MODE keys.
                    Never touches real money (Non-Goal N1).

Every call carries an idempotency key so a duplicated request is a no-op on
the gateway side as well — belt and braces with our own guardrails.
"""

from __future__ import annotations

import hashlib
import hmac
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings


@dataclass(frozen=True)
class GatewayResult:
    ok: bool
    reference: str  # gateway payment / link id
    detail: str
    raw: dict


@dataclass(frozen=True)
class PaymentLink:
    ok: bool
    url: str
    reference: str
    expires_at: datetime
    raw: dict


class RazorpayClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._mock = settings.razorpay_mock or not (
            settings.razorpay_key_id and settings.razorpay_key_secret
        )
        self._sdk = None
        if not self._mock:
            self._sdk = self._build_sdk()

    @property
    def mode(self) -> str:
        return "mock" if self._mock else "test"

    # --------------------------------------------------------------------- #
    # Retry a payment (soft technical failures only; caller enforces that).
    # --------------------------------------------------------------------- #
    def retry_payment(
        self,
        transaction_id: str,
        amount_paise: int,
        idempotency_key: str,
        route_healthy: bool = True,
    ) -> GatewayResult:
        if self._mock:
            return self._mock_retry(transaction_id, idempotency_key, route_healthy)
        # Real Test Mode: Razorpay has no generic "retry" — in a live build we
        # create a fresh order/payment attempt for the same reference. Kept
        # behind the same interface so callers don't care which mode is active.
        try:
            order = self._sdk.order.create(  # type: ignore[union-attr]
                {
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": transaction_id,
                    "notes": {"resq_idempotency_key": idempotency_key},
                }
            )
            return GatewayResult(
                ok=True,
                reference=order["id"],
                detail="Test-mode order created for re-attempt",
                raw=order,
            )
        except Exception as exc:  # pragma: no cover - network path
            return GatewayResult(False, "", f"gateway error: {exc}", {})

    # --------------------------------------------------------------------- #
    # Create a fresh, bounded payment link (user-side recovery).
    # --------------------------------------------------------------------- #
    def create_payment_link(
        self,
        transaction_id: str,
        amount_paise: int,
        idempotency_key: str,
    ) -> PaymentLink:
        ttl = timedelta(minutes=self._s.recovery_link_ttl_minutes)
        expires_at = datetime.now(UTC) + ttl
        if self._mock:
            ref = f"plink_mock_{idempotency_key[-8:]}"
            return PaymentLink(
                ok=True,
                url=f"https://rzp.io/i/{ref}",
                reference=ref,
                expires_at=expires_at,
                raw={"mock": True, "idempotency_key": idempotency_key},
            )
        try:
            link = self._sdk.payment_link.create(  # type: ignore[union-attr]
                {
                    "amount": amount_paise,
                    "currency": "INR",
                    "expire_by": int(expires_at.timestamp()),
                    "reference_id": f"{transaction_id}:{idempotency_key}",
                    "notes": {"resq_idempotency_key": idempotency_key},
                }
            )
            return PaymentLink(
                ok=True,
                url=link["short_url"],
                reference=link["id"],
                expires_at=expires_at,
                raw=link,
            )
        except Exception as exc:  # pragma: no cover - network path
            return PaymentLink(False, "", "", expires_at, {"error": str(exc)})

    # --------------------------------------------------------------------- #
    # Webhook signature verification (real mode).
    # --------------------------------------------------------------------- #
    def verify_webhook(self, body: bytes, signature: str) -> bool:
        secret = self._s.razorpay_webhook_secret
        if self._mock or not secret:
            # In mock/demo we accept synthetic posts; documented in honesty notes.
            return True
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    # --------------------------------------------------------------------- #
    # internals
    # --------------------------------------------------------------------- #
    def _build_sdk(self):  # pragma: no cover - requires network + keys
        import razorpay  # imported lazily so mock mode needs no dependency

        client = razorpay.Client(
            auth=(self._s.razorpay_key_id, self._s.razorpay_key_secret)
        )
        client.set_app_details({"title": "ResQ-Pay", "version": "0.1"})
        return client

    def _mock_retry(
        self, transaction_id: str, idempotency_key: str, route_healthy: bool
    ) -> GatewayResult:
        # Model reality: retrying into a healthy rail usually succeeds; retrying
        # into an unhealthy one usually fails. Seeded by the idempotency key so
        # the same attempt is stable within a run.
        rng = random.Random(idempotency_key)
        success_p = 0.82 if route_healthy else 0.15
        ok = rng.random() < success_p
        ref = f"pay_mock_{idempotency_key[-8:]}"
        return GatewayResult(
            ok=ok,
            reference=ref,
            detail="captured" if ok else "re-attempt failed",
            raw={"mock": True, "route_healthy": route_healthy},
        )
