# ADR 0002 — Rule-based retry timing, not ML

**Status:** accepted

## Context
"Predict the best time to retry" is a tempting place to add a model. But we
have no historical user-activity data to train or validate one, and a wrong
prediction here means firing money at the wrong moment.

## Decision
Retry timing is a fixed cooldown window (config: `retry_cooldown_seconds`), and
retry *eligibility* is governed by the deterministic degradation state machine
(don't retry into `DEGRADING`/`DOWN`). No ML in the money path.

## Consequences
- Every retry decision is explainable and reproducible.
- We state this plainly to judges instead of overselling an unjustified model.
- Learned timing is listed as future work, gated on having real data.
