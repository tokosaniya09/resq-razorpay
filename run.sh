#!/usr/bin/env bash
# ResQ-Pay one-command launcher (macOS/Linux).
# Runs backend + frontend in the background, streams a demo, cleans up on exit.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

cleanup() { echo "Shutting down..."; kill $BACK $FRONT 2>/dev/null || true; }
trap cleanup EXIT

echo "Starting backend..."
( cd "$ROOT/backend" && [ -d .venv ] && source .venv/bin/activate; uvicorn app.main:app --reload --port 8000 ) &
BACK=$!

echo "Starting frontend..."
( cd "$ROOT/frontend" && npm run dev ) &
FRONT=$!

echo "Waiting for backend..."
sleep 6

echo "Streaming demo events (with an outage)..."
( cd "$ROOT/backend" && [ -d .venv ] && source .venv/bin/activate; \
  python scripts/generate_events.py --count 90 --rate 5 --outage --outage-at 30 --outage-len 25 --seed 7 )

echo "Dashboard: http://localhost:5173  (Ctrl+C to stop everything)"
wait
