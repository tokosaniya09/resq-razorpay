# ResQ-Pay — Design Document

**A payment degradation & revenue-recovery controller**

| | |
|---|---|
| **Status** | Draft (v0.1) |
| **Author** | Pratham Agarwal |
| **Last updated** | 25 Aug 2026 |
| **Scope** | Hackathon build — Track 03 (AI Revenue Recovery) |
| **Reviewers** | _TBD_ |

> **How to use this doc:** This is the single source of truth for what ResQ-Pay is and how it's built. When you start the build in a fresh chat, paste this in first. Sections 5–7 define the architecture to implement; Section 11 is the folder layout to scaffold; Section 13 is the order to build in.

---

## 1. Overview

ResQ-Pay is a service that sits next to a payment gateway and turns failed payments into recovered revenue — safely. It listens to payment events from **Razorpay (Test Mode)**, classifies *why* each payment failed, decides on a **bounded** recovery action, and executes it. Crucially, it also watches the failure *stream as a whole*: when it detects that a bank or acquirer is **degrading**, it stops retrying into the failing system (which would double-charge customers and waste money) and switches to a hold-and-recover strategy.

Everything is visible on a live dashboard, and every money-touching decision is logged to an audit trail. The recovery *logic* is deterministic code; a language model is used only to write the customer-facing recovery message, never to decide whether or how money moves.

**One-line pitch:** *Most recovery tools react to one failed payment at a time. ResQ-Pay reacts to the health of the whole payment rail — and knows when the right move is to not retry at all.*

---

## 2. Goals and Non-Goals

Being explicit about scope is how we avoid overselling and keep the build finishable.

### Goals

- **G1** — Ingest payment failure events from Razorpay Test Mode (webhooks) and from a synthetic event generator we control for demos.
- **G2** — Classify each failure into an actionable root cause using a deterministic mapping (no AI in this path).
- **G3** — Detect *systemic degradation* across the event stream (rising failure rate / latency), not just individual failures.
- **G4** — Execute **bounded** recovery actions: safe retry, fresh payment link, or hold — each gated by hard safety limits.
- **G5** — Guarantee no double-charge via idempotency keys and retry caps.
- **G6** — Show the whole system working live on a 3-pane dashboard, with an audit ledger and honest metrics.
- **G7** — Measure impact against a naive baseline ("blindly retry everything") and report the difference.

### Non-Goals (explicitly out of scope)

- **N1** — We do **not** move real money. Test Mode only.
- **N2** — We do **not** actually deliver SMS/WhatsApp. Outreach messages are generated and displayed in the dashboard; real delivery is a future integration, and we say so.
- **N3** — We do **not** predict retry timing with a trained ML model. Timing is rule-based (cooldown windows). We do not claim otherwise.
- **N4** — We do **not** build a full merchant checkout. We simulate the checkout/payment surface enough to drive the demo.
- **N5** — We are **not** a fraud system. Fraud is a different track; ResQ-Pay assumes the customer genuinely wants to pay.

---

## 3. Background and problem

When a customer tries to pay and it fails, the merchant loses a sale they had already earned — no new acquisition spend required to win it back. In India this is a large, measurable leak:

- Blended payment success rates typically sit around **90–95%**, and a rate below 90% is considered a real business problem — so roughly **5–10% of attempts fail**, varying by method and segment. During bank/issuer overloads, UPI success can dip to **80–85%**. *(Razorpay, productgrowth.in benchmarks, 2026.)*
- A **1% drop in payment success rate is reported to cost ~10× more** in lost revenue than the equivalent saving on transaction fees. *(RBI Operational Resilience Framework, 2025, via PayU.)*
- **~70% of customers abandon after a single payment failure**, so first-attempt recovery matters. *(Razorpay, 2026.)*

The core insight that makes ResQ-Pay principled rather than ad hoc is **NPCI's own failure taxonomy**, which splits every declined transaction into two buckets:

- **Technical Decline (TD)** — failure on the bank/NPCI/infrastructure side (server unavailable, timeout, network). System-wide this is small (~0.8%) but **spikes during outages**. *(NPCI target <1%.)*
- **Business Decline (BD)** — failure on the user side (wrong PIN, insufficient balance, expired card). *(NPCI target <5%; NPCI Circular OC-149.)*

This maps directly onto our architecture:

- **TD-type failures** → often a *systemic* signal. Retrying into a degrading rail causes duplicate charges and wasted fees. Correct response: **hold, back off, recover when healthy** (or route around).
- **BD-type failures** → a *user-side* problem the customer can fix. Correct response: **a fresh, bounded payment link + a clear message.**

The three operational failure modes we're fixing:

1. **No root-cause precision** — gateways return broad statuses, so a bank outage is treated like a wrong PIN. We separate them.
2. **Risky unbounded retries** — blind retries double-charge users, trip fraud flags, and burn fees. We gate every retry.
3. **High dropped-checkout churn** — expecting the user to restart checkout loses them. We hand them a one-tap recovery path.

Industry data also validates the approach: automated retry of **soft** failures (timeouts, network) recovers ~15–20% of failed transactions, while retrying **hard** failures (insufficient funds, blocked card) just wastes attempts. *(PayU, 2026.)* ResQ-Pay encodes exactly that distinction.

---

## 4. What we deliver (the tangible artifacts)

This is what exists at the end — the "delivers something" checklist:

1. **A running backend service** (`backend/`) — ingests events, classifies, detects degradation, decides, and acts against Razorpay Test Mode, exposing a REST + WebSocket API.
2. **A live dashboard** (`frontend/`) — the 3-pane control surface (see §6.8), the thing judges watch.
3. **A synthetic event generator** (`backend/scripts/`) — replays realistic failure streams and can inject a bank-outage spike on command, so the demo is deterministic and repeatable.
4. **An audit ledger** — every decision, with inputs, the rule that fired, and the outcome; exportable as a report.
5. **A metrics report** — recovery rate, ₹ rescued, retries avoided, wasted-retry cost avoided vs the naive baseline (see §9).
6. **A demo script** (`docs/demo-script.md`) — the exact sequence to run on stage.
7. **A clean, documented repo** — README, tests, and the structure in §11, so a stranger can clone and run it.

---

## 5. System design — high level

```
                        +-------------------------------+
                        |   Event Sources               |
                        |   - Razorpay webhooks (test)  |
                        |   - Synthetic generator        |
                        +---------------+---------------+
                                        | payment.failed / captured / ...
                                        v
                        +-------------------------------+
                        |   Ingestion & Normalization   |
                        |   (verify, dedupe, to schema) |
                        +---------------+---------------+
                                        v
                        +-------------------------------+
                        |   Deterministic Classifier    |  NPCI-style
                        |   error code -> {TD | BD}     |  TD/BD split
                        +---------------+---------------+
                                        |
                     +------------------+------------------+
                     v                                     v
        +-------------------------+          +----------------------------+
        |  Degradation Detector   |          |  (per-transaction context) |
        |  rolling window over    |          |                            |
        |  the whole stream ->    |          |                            |
        |  HEALTHY/DEGRADING/DOWN |          |                            |
        +-----------+-------------+          +-------------+--------------+
                    |                                       |
                    +------------------+--------------------+
                                       v
                        +-------------------------------+
                        |   Recovery Policy Engine      |  <-- Hard guardrails:
                        |   picks ONE bounded action    |      max retries, cooldown,
                        +---------------+---------------+      link TTL, idempotency
                                        v
              +-------------------------+-------------------------+
              v                         v                         v
        +-----------+           +--------------+          +----------------+
        |  HOLD /   |           |  SAFE RETRY  |          |  RECOVERY LINK |
        |  BACKOFF  |           |  (soft only) |          |  + outreach    |
        |  (systemic)|          |  via Razorpay|          |  (BD / user)   |
        +-----+-----+           +------+-------+          +-------+--------+
              |                        |                          |
              |                        |                     (LLM writes the
              |                        |                      message text only)
              +------------------------+--------------------------+
                                       v
                        +-------------------------------+
                        |   Audit Ledger (persist all)  |
                        +---------------+---------------+
                                        v
                        +-------------------------------+
                        |   REST + WebSocket API        |
                        +---------------+---------------+
                                        v
                        +-------------------------------+
                        |   3-Pane Live Dashboard        |
                        +-------------------------------+
```

**Design principle running through all of it:** the *money path* (classify → detect → decide → act → log) is 100% deterministic and testable. The LLM lives on a side branch that only produces human-readable text. If the LLM is down or wrong, no money decision is affected.

---

## 6. Components

### 6.1 Ingestion & normalization
- Receives Razorpay webhooks (`payment.failed`, `payment.captured`, etc.) on a signed endpoint; verifies the webhook signature.
- Accepts synthetic events from the generator on an internal endpoint.
- Normalizes both into one internal `PaymentEvent` schema so nothing downstream cares about the source.
- Deduplicates by event ID (webhooks can be redelivered).

### 6.2 Deterministic classifier
- Pure function: `error_code -> FailureClass`.
- Maps Razorpay/technical codes into two families aligned with NPCI's split:
  - **Technical Decline (TD):** `GATEWAY_ERROR`, `NETWORK_TIMEOUT`, server-unavailable, acquirer timeout → *systemic-leaning, soft, retryable-if-healthy.*
  - **Business Decline (BD):** `INSUFFICIENT_FUNDS`, `BAD_REQUEST_ERROR`, expired card, wrong PIN → *user-side, hard, not blind-retryable.*
- Table-driven and unit-tested. No AI. This is the "right tool in the right place" showpiece.

### 6.3 Degradation detector (the differentiator)
- Maintains a rolling window (e.g. last N events or last T seconds) per route/acquirer.
- Tracks failure rate and, if available, latency.
- Runs a small **state machine** per route:
  - `HEALTHY` → normal handling.
  - `DEGRADING` → failure rate above warning threshold; be cautious, prefer HOLD for TD failures.
  - `DOWN` → failure rate above critical threshold; **stop retrying entirely**, queue for recovery when healthy.
  - `RECOVERING` → failures dropping; drain the hold queue gradually.
- Thresholds live in config, not code, so they're tunable during the demo.
- This is what elevates the project from "recovery bot" to "reliability controller for a payment rail."

### 6.4 Recovery policy engine
- Input: the classified failure + current route health + transaction history.
- Output: exactly **one** bounded action, chosen by explicit rules:
  - Route `DOWN`/`DEGRADING` + TD → **HOLD/BACKOFF** (protect against duplicate charges).
  - Route `HEALTHY` + soft TD, under retry cap → **SAFE RETRY**.
  - BD (user-side) → **RECOVERY LINK + OUTREACH**.
  - Retry cap hit, or hard failure → **STOP** (log as unrecoverable, honestly).
- Every decision records *which rule fired and why* for the ledger.

### 6.5 Guardrails (safety layer)
- **Max 2 retry attempts** per transaction identifier.
- **Cooldown** between attempts (rule-based, not ML).
- **Idempotency key / nonce** per recovery action → the same logical payment can never be executed twice.
- **Recovery link TTL** (e.g. 15 min) and an **amount cap** — links expire and are bounded.
- All limits are config values with safe defaults.

### 6.6 Action executors
- `retry` — re-attempts via the Razorpay Test Mode API, idempotency key attached.
- `recovery_link` — creates a fresh Razorpay payment link (Test Mode), TTL + amount bound.
- `hold` — enqueues the transaction, to be re-evaluated when the route returns to `HEALTHY`.
- Each executor is small, isolated, and independently testable.

### 6.7 Isolated LLM outreach service
- **Only** job: given the failure context (in structured form), produce a short, clear, plain-language recovery message ("Your payment didn't go through — here's a fresh link, valid 15 minutes").
- Receives no authority to move money and returns only text.
- Fails safe: if the LLM call fails, we fall back to a templated message. The recovery still works.

### 6.8 Dashboard (the visible deliverable)
Three panes, updated live over WebSocket:
- **Left — Event stream:** incoming `payment.failed` events as they arrive.
- **Center — Decision pipeline:** the classifier → detector → policy chain lighting up green/red per event, plus the current route-health state (HEALTHY/DEGRADING/DOWN).
- **Right — Outcomes:** Razorpay Test Mode transaction state, the audit ledger, generated outreach messages, and the running **₹ Rescued** counter + live metrics.

---

## 7. Data model (core records)

Keep it small and explicit. Suggested tables/entities:

- **`PaymentEvent`** — `id`, `source`, `transaction_id`, `amount`, `currency`, `status`, `error_code`, `received_at`, `raw_payload`.
- **`FailureClassification`** — `event_id`, `class` (TD/BD), `is_soft`, `mapped_reason`.
- **`RouteHealthSnapshot`** — `route`, `window_start`, `failure_rate`, `state`, `at`.
- **`RecoveryDecision`** — `id`, `event_id`, `action` (HOLD/RETRY/LINK/STOP), `rule_fired`, `attempt_number`, `idempotency_key`, `decided_at`.
- **`RecoveryOutcome`** — `decision_id`, `result` (recovered/failed/held/expired), `amount_recovered`, `at`.
- **`OutreachMessage`** — `decision_id`, `channel` (simulated), `body`, `generated_by` (llm/template).

The audit ledger is just `RecoveryDecision` joined to `RecoveryOutcome` — a full, honest trail of who decided what and what happened.

---

## 8. AI usage and boundaries (state this plainly to judges)

| Layer | AI? | Why |
|---|---|---|
| Failure classification | **No** | Deterministic mapping is more reliable and auditable than an LLM. |
| Degradation detection | **No** | Thresholds + a state machine; must be predictable. |
| Recovery decision (money) | **No** | Money actions must be explainable and bounded, never probabilistic. |
| Retry timing | **No** | Rule-based cooldowns. We have no user-activity data to justify ML. |
| Outreach message text | **Yes** | Natural-language generation is exactly what an LLM is good at, and it touches no money. |

The headline: **the LLM decides what to *say*, never what to *do* with money.** That boundary is the "AI judgment" answer, and "where we chose *not* to use AI" is most of this table.

---

## 9. Metrics and impact

We measure ourselves against a **naive baseline**: "retry every failure immediately, up to N times, regardless of route health."

Report, live and in the final summary:
- **Recovery rate** = recovered ÷ recoverable failures.
- **₹ Rescued** = sum of recovered transaction amounts.
- **Retries avoided during degradation** = retries the baseline would have fired into a `DOWN` route that we held → a proxy for **duplicate-charge risk and fee waste avoided.**
- **Wasted-retry rate** = retries on hard (BD) failures that can't succeed; baseline does these, we don't.
- **Unrecoverable, honestly listed** = failures we chose not to touch, with reasons (this honesty is itself scored — "one cherry-picked success proves nothing").

The impact story is not "we save X%." It's: *against a naive retry loop, ResQ-Pay recovers a comparable or better share of the safely-recoverable failures while eliminating the duplicate-charge risk and wasted fees that the naive loop creates during an outage.*

---

## 10. Tech stack

Chosen for reliability, speed of build, and a clean realtime dashboard:

- **Backend:** Python + **FastAPI** (async, great for webhooks + WebSocket).
- **Persistence:** **SQLite** via SQLAlchemy/SQLModel for zero-setup; swappable to Postgres (documented). The audit trail must persist, so we don't use in-memory-only state.
- **Realtime:** WebSocket (FastAPI native) pushing events to the dashboard.
- **Payments:** Razorpay Python SDK, **Test Mode** keys only.
- **LLM:** any provider via a thin, swappable client interface (so the model is a config detail, not a dependency baked through the code).
- **Frontend:** **React + Vite + TypeScript**, Tailwind for styling. A single-page realtime dashboard — Vite keeps it light.
- **Tooling:** `ruff` + `black` (lint/format), `pytest` (tests), `Makefile` (one-command dev), `docker-compose` (optional, for a clean "clone and run").

---

## 11. Repository structure

This is a small **monorepo** (backend + frontend + docs in one repo). Below is the layout to scaffold, with what each part is for. The annotations exist so a reviewer can see the reasoning, not just the tree.

```
resq-pay/
├── README.md                      # what it is, how to run, screenshots, demo GIF
├── DESIGN.md                      # this document (source of truth)
├── Makefile                       # `make dev`, `make test`, `make seed`, `make demo`
├── docker-compose.yml             # optional one-command spin-up
├── .gitignore
├── .env.example                   # documents required env vars; real .env is git-ignored
├── .github/
│   └── workflows/
│       └── ci.yml                 # run lint + tests on every push (signals code care)
│
├── docs/
│   ├── architecture.md            # the diagrams from §5–6, kept up to date
│   ├── demo-script.md             # exact on-stage sequence
│   └── decisions/                 # short "ADR" notes: why SQLite, why no ML, etc.
│
├── backend/
│   ├── pyproject.toml             # deps + tool config (ruff, black, pytest)
│   ├── .env.example
│   ├── app/
│   │   ├── main.py                # FastAPI app entry; wires routers together
│   │   ├── core/                  # cross-cutting: config, logging, constants, thresholds
│   │   │   ├── config.py
│   │   │   └── logging.py
│   │   ├── api/                   # HTTP/WS layer ONLY (no business logic here)
│   │   │   ├── webhooks.py        # Razorpay webhook + synthetic ingest endpoints
│   │   │   ├── dashboard.py       # REST for the dashboard
│   │   │   └── ws.py              # WebSocket broadcaster
│   │   ├── models/                # data schemas (Pydantic) + DB models (§7)
│   │   ├── services/              # the brain — one folder per responsibility
│   │   │   ├── ingestion/         # normalize, verify, dedupe
│   │   │   ├── classifier/        # deterministic TD/BD mapping (+ the code->class table)
│   │   │   ├── degradation/       # rolling window + route-health state machine
│   │   │   ├── policy/            # recovery policy engine + guardrails
│   │   │   ├── executors/         # retry / recovery_link / hold
│   │   │   ├── outreach/          # isolated LLM client + template fallback
│   │   │   └── ledger/            # audit persistence + metrics computation
│   │   ├── integrations/
│   │   │   └── razorpay_client.py # the ONLY file that talks to Razorpay
│   │   └── db/
│   │       └── session.py         # DB setup/session
│   ├── scripts/
│   │   ├── generate_events.py     # synthetic stream; `--outage` injects a spike
│   │   ├── seed.py                # baseline data for a clean demo
│   │   └── run_baseline.py        # the naive-retry comparator for §9
│   └── tests/
│       ├── test_classifier.py     # the deterministic core is the most-tested part
│       ├── test_degradation.py
│       ├── test_policy.py
│       └── test_guardrails.py     # prove: no double-charge, retry cap holds
│
└── frontend/
    ├── package.json
    ├── index.html
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── panes/                 # one component per dashboard pane
    │   │   ├── EventStream.tsx
    │   │   ├── DecisionPipeline.tsx
    │   │   └── Outcomes.tsx
    │   ├── components/            # small reusable UI bits
    │   ├── hooks/
    │   │   └── useWebSocket.ts    # live connection to the backend
    │   └── lib/                   # api client, types, formatting
    └── ...
```

### Why this structure (the parts worth understanding)

- **`api/` is thin, `services/` is the brain.** Route handlers only parse requests and call services. This "keep the web layer dumb" split is standard in production because it makes the logic testable *without* spinning up a server, and lets you swap the interface (HTTP today, a queue tomorrow) without rewriting the logic.
- **One folder per responsibility inside `services/`.** Each of classify / detect / decide / execute / outreach / ledger is a separate unit with a clear input and output. This is *separation of concerns*: a change to how outreach messages are written can't accidentally break the retry cap.
- **`integrations/razorpay_client.py` is the only file that talks to Razorpay.** All external-vendor calls go through one wrapper, so if the SDK changes (or you demo with a mock), you touch one file. This is the *adapter* pattern.
- **`models/` centralizes the data shapes** so every layer agrees on what a `PaymentEvent` is.
- **`tests/` mirrors `services/`, and the deterministic core is the most heavily tested.** The two tests that matter most — "we never double-charge" and "the retry cap is enforced" — are the ones a serious reviewer will look for first.
- **`docs/decisions/` (ADRs)** are short notes recording *why* a choice was made (why SQLite, why no ML for timing). Real teams keep these so future contributors don't re-litigate settled decisions. Including them signals maturity.
- **`.env.example` + git-ignored `.env`** is how real projects handle secrets: the example documents what's needed, the real values never touch git.
- **`Makefile` + CI** mean a stranger can `make dev` and see it run, and every push is linted and tested automatically — the clearest possible signal that you care about code others can build on.

---

## 12. Testing strategy

- **Unit tests** on every service, heaviest on the deterministic core (classifier, degradation state machine, policy, guardrails).
- **Two guardrail tests are non-negotiable and worth calling out in the README:**
  1. The same logical payment, submitted twice, executes at most once (idempotency).
  2. Retries never exceed the configured cap, and never fire into a `DOWN` route.
- **One integration test** for the happy path: event in → decision → outcome → ledger row.
- CI runs lint + tests on every push.

---

## 13. Build plan (order to execute in the new chat)

Phased so there's always something runnable. Don't build the fancy parts first.

**Phase 0 — Skeleton (get to "it runs")**
- Scaffold the repo (§11), FastAPI app, SQLite, one health endpoint, empty React dashboard connected over WebSocket.

**Phase 1 — Ingest + classify + ledger (the deterministic spine)**
- Synthetic event generator → ingestion → deterministic TD/BD classifier → persist to ledger → show events streaming in the left pane. *Fully testable, no AI, no Razorpay yet.*

**Phase 2 — Policy + guardrails + executors (money logic, still mockable)**
- Policy engine picks an action; guardrails enforce caps/idempotency; executors run (mock Razorpay first, then real Test Mode). Center pane lights up. Write the two guardrail tests here.

**Phase 3 — Degradation detector (the differentiator)**
- Rolling window + route-health state machine; `--outage` mode in the generator; center pane shows HEALTHY/DEGRADING/DOWN; policy starts HOLDing during `DOWN`.

**Phase 4 — Metrics + baseline comparator**
- Compute recovery rate, ₹ rescued, retries avoided; run the naive baseline; right pane shows the numbers.

**Phase 5 — LLM outreach (last, because it's the side branch)**
- Isolated outreach service + template fallback; generated messages shown in the right pane, clearly labelled as simulated.

**Phase 6 — Polish + demo**
- README with screenshots, `docs/demo-script.md`, rehearse the outage moment, tidy the dashboard.

> If time runs short, ship through **Phase 4** and stub Phase 5 with templates. The deterministic spine + degradation detection + honest metrics *is* the project; the LLM is the garnish.

---

## 14. Honesty notes (what is real vs simulated)

State these openly — judges respect it and it's the "no oversell" commitment:

- **Money:** Razorpay **Test Mode** only. No real funds move.
- **Outreach:** messages are **generated and displayed, not delivered.** Real SMS/WhatsApp is future work.
- **Degradation in the demo:** induced by the synthetic generator's `--outage` mode. The same detector also works on a live webhook stream; we just can't force a real bank outage on cue.
- **Retry timing:** rule-based cooldowns, **not** a trained model.
- **Data:** synthetic, generated by our own script.

---

## 15. Future work (out of scope, but shows direction)

- Real outreach delivery (WhatsApp/SMS sandbox).
- Smart routing: actively route around a `DOWN` acquirer instead of only holding (industry-standard "route health" optimization).
- Subscription/auto-pay recovery (UPI Autopay success runs a notably low ~30–50%, so recurring recovery is high-value).
- Learned retry timing *once real user-activity data exists* to justify it.

---

## 16. References

- NPCI failure taxonomy — Technical Decline vs Business Decline (NPCI Circular OC-149); TD trajectory ~8–10% (2016) → ~0.8% (2025).
- Razorpay — Payment Success Rate Optimization (India), 2026; Payment Gateway Reliability benchmarks, 2026.
- productgrowth.in — UPI Payment Success Rates: 2026 benchmarks (blended 92–96%; below 90% a problem).
- PayU — Reducing payment gateway transaction failures, 2026 (soft-vs-hard retry; ~15–20% soft-failure recovery; RBI Operational Resilience Framework 1%→10× point).
- RBI — Payment Systems / Operational Resilience Framework, 2025.

*(Figures are directional industry benchmarks; per-gateway success rates are not officially published. Cite ranges, not false precision.)*
