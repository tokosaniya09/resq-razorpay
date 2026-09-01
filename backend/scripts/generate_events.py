"""Synthetic event generator (§4.3).

Replays a realistic stream of payment events into the running backend's
`/ingest/synthetic` endpoint so the dashboard has something live to show.
`--outage` injects a bank-outage spike on one route at a chosen point, which
is what makes the degradation moment reproducible on stage (we cannot force a
real bank to fail on cue — see honesty notes §14).

Uses only the standard library (urllib), so it has zero dependencies and can
be run from anywhere.

Examples
--------
    python scripts/generate_events.py --count 60 --rate 4
    python scripts/generate_events.py --count 80 --rate 5 --outage --outage-at 30
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
import uuid

# Realistic-ish mix. Technical (soft) codes vs business (hard) codes.
TECHNICAL_CODES = [
    "GATEWAY_TIMEOUT",
    "NETWORK_TIMEOUT",
    "ACQUIRER_TIMEOUT",
    "SERVER_ERROR",
    "UPI_TECHNICAL_DECLINE",
]
BUSINESS_CODES = [
    "INSUFFICIENT_FUNDS",
    "INCORRECT_PIN",
    "CARD_EXPIRED",
    "PAYMENT_CANCELLED",
    "LIMIT_EXCEEDED",
]
ROUTES = ["UPI-HDFC", "UPI-SBI", "CARD-ICICI", "UPI-AXIS"]
NAMES = ["Aarav", "Diya", "Vivaan", "Ananya", "Kabir", "Ishaan", "Meera", "Rohan"]

OUTAGE_ROUTE = "UPI-SBI"


def _post(base_url: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}/ingest/synthetic",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception as exc:  # keep the stream going even if one post fails
        print(f"  ! post failed: {exc}")


def _random_event(outage_active: bool) -> dict:
    # ~88% of attempts succeed in steady state; failures split ~40/60 TD/BD.
    if outage_active:
        route = OUTAGE_ROUTE
        # During the outage, this route is mostly technical failures.
        if random.random() < 0.85:
            status, code = "failed", random.choice(TECHNICAL_CODES)
        else:
            status, code = "captured", None
    else:
        route = random.choice(ROUTES)
        r = random.random()
        if r < 0.82:
            status, code = "captured", None
        elif r < 0.90:
            status, code = "failed", random.choice(TECHNICAL_CODES)
        else:
            status, code = "failed", random.choice(BUSINESS_CODES)

    return {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "transaction_id": f"txn_{uuid.uuid4().hex[:10]}",
        "amount": random.choice([19900, 49900, 99900, 149900, 250000]),
        "currency": "INR",
        "status": status,
        "error_code": code,
        "route": route,
        "customer_name": random.choice(NAMES),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="ResQ-Pay synthetic event stream")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--count", type=int, default=60, help="events to emit")
    ap.add_argument("--rate", type=float, default=4.0, help="events per second")
    ap.add_argument("--outage", action="store_true", help="inject a bank outage")
    ap.add_argument("--outage-at", type=int, default=25, help="event # outage starts")
    ap.add_argument("--outage-len", type=int, default=20, help="outage duration (events)")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    delay = 1.0 / args.rate if args.rate > 0 else 0
    print(f"Streaming {args.count} events -> {args.base_url} at {args.rate}/s")
    if args.outage:
        end = args.outage_at + args.outage_len
        print(f"  Outage on {OUTAGE_ROUTE}: events {args.outage_at}-{end}")

    for i in range(args.count):
        outage_active = (
            args.outage and args.outage_at <= i < args.outage_at + args.outage_len
        )
        ev = _random_event(outage_active)
        marker = "  [OUTAGE]" if outage_active else ""
        print(
            f"[{i:>3}] {ev['route']:<10} {ev['status']:<8} "
            f"{ev['error_code'] or '-':<22}{marker}"
        )
        _post(args.base_url, ev)
        time.sleep(delay)

    print("Done.")


if __name__ == "__main__":
    main()
