"""Seed a running backend with a small, calm burst of events.

Unlike generate_events.py (which streams and can inject an outage), this just
posts a handful of mixed events so a freshly-started dashboard has a few rows
and a healthy baseline before you begin the live demo.

    python scripts/seed.py
"""

from __future__ import annotations

import argparse

from scripts.generate_events import _post, _random_event


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--count", type=int, default=15)
    args = ap.parse_args()

    print(f"Seeding {args.count} calm events -> {args.base_url}")
    for _ in range(args.count):
        _post(args.base_url, _random_event(outage_active=False))
    print("Seed complete.")


if __name__ == "__main__":
    main()
