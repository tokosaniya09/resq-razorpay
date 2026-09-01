# Demo script (~3 minutes)

**Goal:** show the pipeline working, then the outage moment, then the honest
metrics. Rehearse the outage beat — it's the memorable part.

## Setup (before you present)
- Terminal A: `make backend`
- Terminal B: `make frontend` → open http://localhost:5173
- Terminal C: ready with the demo command below
- Fallback: have `frontend/standalone-demo.html` open in a browser tab.

## Beat 1 — "here's the normal flow" (45s)
Run a calm stream:
```
python scripts/seed.py --count 20
```
Point at the three panes: events arriving (left), each one classified TD/BD and
given a bounded action (center), ₹ rescued ticking up and simulated messages
(right). Note: rails are all `HEALTHY`.

## Beat 2 — "now a bank starts failing" (60s)
```
python scripts/generate_events.py --count 90 --rate 5 --outage --outage-at 20 --outage-len 30 --seed 7
```
Watch `UPI-SBI` climb `HEALTHY → DEGRADING → DOWN`. The instant it's `DOWN`:
- the center pane shows the **retries-suspended banner**,
- technical failures switch to **HOLD** (rule `R1_hold_route_down`),
- ₹ rescued stops rising on that rail — on purpose.

Say the line: *"A naive retry loop would be firing payments into a dead bank
right now — double-charging customers and burning fees. We hold."*

## Beat 3 — "recovery + the honest scoreboard" (45s)
As the outage clears, the rail goes `RECOVERING`, held payments drain, and ₹
rescued jumps. Then show the numbers:
```
python scripts/run_baseline.py --count 200 --outage --seed 7
```
Land it: *"Comparable-or-better recovery, with the duplicate-charge risk and
wasted fees removed. And we list what we chose not to touch — no cherry-picking."*

## If something breaks
Switch to the standalone demo tab, press Start, then Trigger bank outage. Same
engine, no backend.
