# ADR 0003 — The money path is deterministic; the LLM is a side branch

**Status:** accepted

## Context
The brief is "AI revenue recovery," so there's pressure to put an LLM in the
decision loop. But money actions must be bounded, auditable, and never
probabilistic.

## Decision
Classification, degradation detection, and the recovery decision are all
deterministic code. The LLM is used only by the outreach service to write the
customer-facing message, receives no authority to move money, and returns only
text. If the LLM call fails, we fall back to a template and the recovery still
works.

## Consequences
- The "AI judgment" story is really about *where we chose not to use AI*.
- The money path is unit-testable without a network or a model.
- Outreach quality can improve independently without risking the safety layer.
