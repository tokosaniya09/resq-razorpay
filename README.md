# ResQ-Pay

**A payment degradation & revenue-recovery controller.**

Most recovery tools react to one failed payment at a time. ResQ-Pay reacts to
the health of the *whole payment rail* — and knows when the right move is to
**not retry at all**.

It sits next to Razorpay (Test Mode), classifies *why* each payment failed,
detects when a payment rail is degrading, and takes exactly one **bounded**
recovery action (safe retry / fresh payment link / hold). Every money decision
is deterministic code. AI is used only on the side — to *explain* a degrading
rail, *draft* an ops follow-up note, and *answer* plain-English questions about
the audit trail — never to decide whether or how money moves.

> Hackathon build, Track 03 (AI Revenue Recovery). Test Mode only — no real
> money moves. See [Honesty notes](#honesty--what-is-real-vs-simulated).

---

## Run it

Requirements: Python 3.11+, Node 18+. Runs fully in **mock mode** with no keys.

```bash
# 1) Backend  (no Razorpay or LLM keys needed)
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# 2) Frontend  (second terminal)
cd frontend
npm install
npm run dev            # dashboard at http://localhost:5173

# 3) Drive a demo  (third terminal)
cd backend
python scripts/generate_events.py --count 140 --rate 5 --outage --outage-at 30 --outage-len 20 --seed 7
```

Or one command: **`.\run.ps1`** (Windows) / **`./run.sh`** (macOS/Linux) —
launches backend, frontend, and a demo stream together. The Makefile also has
`make backend`, `make frontend`, `make demo`, `make baseline`, `make test`.

**What to watch:** as the stream runs, `UPI-SBI` climbs `HEALTHY → DEGRADING →
DOWN`. The moment it's `DOWN`, retries are suspended and technical failures are
**held** — the naive loop would retry here and risk double-charging. When the
outage clears the rail returns to `RECOVERING`, held payments are re-attempted
live, and **₹ Rescued** climbs.

---

## Optional: real integrations

**Real Razorpay Test Mode:** copy `.env.example` to `backend/.env`, set
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`, and `RAZORPAY_MOCK=false`. No real
money moves in Test Mode.

**Real LLM (for the advisory features):** in `backend/.env` set
`LLM_ENABLED=true` and `LLM_API_KEY=<free key from https://aistudio.google.com/apikey>`.
The default provider is **Google Gemini** (`LLM_MODEL=gemini-3.6-flash`, free
tier); Anthropic is also supported via `LLM_PROVIDER=anthropic`. Without a key,
every AI feature falls back to a deterministic version automatically — the money
path is never affected either way.

Not sure if the LLM is wired up? Open **`http://localhost:8000/api/llm-health`** —
it reports the config and the exact error if a call fails (model names change
over time; if one is retired, that page tells you and you swap `LLM_MODEL`).

---

## The idea, briefly

NPCI splits every declined transaction into two families, and so do we:

| Failure family | Cause | Right response |
|---|---|---|
| **Technical Decline (TD)** | bank / acquirer / infra (timeout, server down) — *soft* | retry **only if the rail is healthy**, else **hold** |
| **Business Decline (BD)** | user side (insufficient funds, wrong PIN, expired card) — *hard* | fresh bounded **payment link** + a clear message |

Blindly retrying a TD failure *during an outage* double-charges customers and
burns fees. Blindly retrying a BD failure can never succeed. ResQ-Pay encodes
exactly this distinction, and adds a **degradation detector** that watches the
failure stream as a whole so it knows which situation it's in.

---

## Architecture

```
Razorpay webhook / synthetic  ->  Ingestion (verify, dedupe, normalize)
   -> Deterministic Classifier (error code -> TD / BD)
   -> Degradation Detector (rolling window -> HEALTHY/DEGRADING/DOWN/RECOVERING)
   -> Policy Engine (+ Guardrails: caps, cooldown, idempotency, amount cap)
   -> Executor (retry | recovery_link | hold | stop)
   -> Audit Ledger (persist every event, decision, outcome)
   -> REST + WebSocket -> 3-pane dashboard
             \
              -> Advisory AI (side branch, text only): root-cause diagnosis,
                 escalation notes, "ask the ledger" Q&A
```

The **money path** (classify → detect → decide → act → log) is 100%
deterministic and unit-tested. AI lives on a side branch that only produces
human-readable text; if it's off or fails, no money decision is affected. Full
diagram in [`docs/architecture.md`](docs/architecture.md).

### Where AI is and isn't used

One shared client (`app/services/llm/client.py`) is the single place any model
is called. The deterministic money path never imports it. AI **reads, explains,
and communicates** — it never decides or moves money.

| Layer | AI? | Why |
|---|---|---|
| Failure classification | No | A deterministic table is more reliable and auditable. |
| Degradation detection | No | Thresholds + a state machine must be predictable. |
| Recovery decision (money) | No | Money actions must be explainable and bounded. |
| Retry timing | No | Rule-based cooldowns; we have no data to justify ML. |
| Customer outreach message | No | A fixed template says all a failure notice needs; an LLM call would add cost/latency for no gain. |
| **Root-cause diagnosis** | **Yes (advisory)** | When a rail degrades, an LLM summarizes the *cluster* of failures for the on-call engineer. It explains; it never decides. |
| **Merchant escalation notes** | **Yes (advisory)** | When a payment is unrecoverable, an LLM drafts the ops follow-up note. Text only. |
| **"Ask the ledger" Q&A** | **Yes (advisory)** | Answers plain-English questions strictly from verified ledger facts — the code computes the numbers, the LLM only phrases them. |

Every advisory feature has a deterministic fallback, so the app is fully
functional with no LLM key.

---

## The safety contract (guardrails)

The two tests a serious reviewer looks for first live in
[`backend/tests/test_guardrails.py`](backend/tests/test_guardrails.py):

1. **No double-charge.** The same logical payment, submitted twice, executes at
   most once (deterministic idempotency keys + a hard execution check).
2. **Bounded retries.** Retries never exceed the configured cap, and never fire
   into a `DOWN` rail.

Plus: recovery-link **TTL** and **amount cap**, retry **cooldown**. All limits
are config values (`backend/app/core/config.py`), tunable at runtime.

---

## Metrics vs a naive baseline

We measure against "retry every failure, up to N times, regardless of rail
health." Run it yourself (offline, no server needed):

```bash
cd backend && python scripts/run_baseline.py --count 200 --outage --seed 7
```

Representative run (200 events, with an outage):

| | Naive | ResQ-Pay |
|---|---|---|
| Recovered | 13 (₹15,189) | **42 (₹46,565)** |
| Risky retries into a failing rail | **44** | ~3 |
| Wasted hard-failure retries | 21 | 0 |
| Recovered via post-outage drain | — | 38 |

The story isn't "we save X%." It's: against a naive loop, ResQ-Pay recovers a
comparable-or-better share of the *safely* recoverable failures **while
eliminating the duplicate-charge risk and wasted fees** the naive loop creates
during an outage. (Exact figures vary with the random seed.)

---

## Layout

```
backend/    FastAPI service — the deterministic spine (see backend/app/services/)
frontend/   React + Vite dashboard (3 panes over WebSocket)
docs/       architecture, demo script, and ADRs (why SQLite, why no ML, ...)
```

`api/` is thin (HTTP/WS only); `services/` is the brain, one folder per
responsibility; `integrations/razorpay_client.py` is the only file that talks
to Razorpay. Tests mirror the services, heaviest on the deterministic core.

---

## Honesty — what is real vs simulated

- **Money & captures:** Razorpay **Test Mode** only. In the default mock mode,
  gateway responses (whether a retry "captures") are simulated — the *decision
  logic* is real; only the final gateway answer is mocked. No real funds move.
- **Outreach:** messages are **generated and displayed, not delivered.** Real
  SMS/WhatsApp is future work.
- **Degradation in the demo:** induced by the generator's `--outage` mode. The
  same detector works on a live webhook stream; we just can't force a real bank
  outage on cue.
- **Live rail health** is held in memory (resets on restart); the **audit
  ledger** is persisted (SQLite), so the decision trail survives restarts.
- **Retry timing:** rule-based cooldowns, **not** a trained model.
- **Data:** synthetic, from our own script.

None of these are hidden — they're deliberate scope choices for a Test-Mode
hackathon build, and each has a clear path to production.

---

## Tests & CI

```bash
cd backend && pytest -q
```

The suite covers the classifier, the degradation state machine, the policy
engine, the guardrails (including the two non-negotiable safety tests above),
the advisory AI services, and an end-to-end integration test (event in →
decision → outcome → ledger row). CI (`.github/workflows/ci.yml`) runs `ruff`
and the test suite on every push.