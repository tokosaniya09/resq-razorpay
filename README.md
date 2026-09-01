# ResQ-Pay

**A payment degradation & revenue-recovery controller.**

Most recovery tools react to one failed payment at a time. ResQ-Pay reacts to
the health of the *whole payment rail* — and knows when the right move is to
**not retry at all**.

It sits next to Razorpay (Test Mode), classifies *why* each payment failed,
detects when an acquirer is degrading, and takes exactly one **bounded**
recovery action (safe retry / fresh payment link / hold). Every money decision
is deterministic code; an LLM is used only to write the customer-facing
message — never to decide whether or how money moves.

> Hackathon build, Track 03 (AI Revenue Recovery). Test Mode only — no real
> money moves. See [Honesty notes](#honesty-what-is-real-vs-simulated).

---

## See it in 30 seconds (no setup)

Open **`frontend/standalone-demo.html`** in any browser. It runs the *real
deterministic engine* (classifier, degradation state machine, guardrails,
policy) ported to the browser, with a synthetic event stream.

1. Press **Start** — events stream in, the pipeline classifies and decides.
2. Press **Trigger bank outage** — watch `UPI-SBI` climb `HEALTHY → DEGRADING
   → DOWN`. The moment it's `DOWN`, retries are **suspended** and technical
   failures are **held** (this is the differentiator — the naive loop would
   retry here and risk double-charging).
3. When the outage clears, the rail returns to `RECOVERING`, held payments are
   drained (re-attempted live once the rail is healthy), and **₹ Rescued** jumps.

This is also the on-stage fallback if the live backend has any trouble.

---

## Run the full stack

Requirements: Python 3.11+, Node 18+.

```bash
# 1) Backend  (runs in MOCK mode — no Razorpay keys needed)
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000

# 2) Frontend  (in a second terminal)
cd frontend
npm install
npm run dev            # dashboard at http://localhost:5173

# 3) Drive a demo  (in a third terminal)
cd backend
python scripts/generate_events.py --count 90 --rate 5 --outage --outage-at 30 --outage-len 25 --seed 7
```

Or one command: **`.\run.ps1`** (Windows) / **`./run.sh`** (macOS/Linux) —
launches backend, frontend, and a demo stream together.

Or use the Makefile: `make backend`, `make frontend`, `make demo`, `make test`,
`make baseline`.

To use **real Razorpay Test Mode**: copy `.env.example` to `.env`, set
`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`, and `RAZORPAY_MOCK=false`.

To turn on the **real LLM features** (outreach, root-cause diagnosis, and
escalation notes): in `backend/.env` set `LLM_ENABLED=true` and
`LLM_API_KEY=<free key from https://aistudio.google.com/apikey>`. The default
provider is **Google Gemini** (`gemini-2.0-flash`, free tier); Anthropic is also
supported (`LLM_PROVIDER=anthropic`). Without a key, every AI feature falls back
to a deterministic version automatically — the money path is never affected.

**Every AI feature is advisory and text-only.** One shared client
(`app/services/llm/client.py`) is the single place any model is called; the
deterministic money path never imports it. The AI *reads, explains, and
communicates* — it never decides or moves money.

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
   -> Outreach (LLM or template — text only, side branch)
   -> Audit Ledger (persist everything)
   -> REST + WebSocket -> 3-pane dashboard
```

The **money path** (classify → detect → decide → act → log) is 100%
deterministic and unit-tested. The LLM lives on a side branch that only
produces human-readable text; if it's down or wrong, no money decision is
affected. Full diagram in [`docs/architecture.md`](docs/architecture.md).

### Where AI is and isn't used

| Layer | AI? | Why |
|---|---|---|
| Failure classification | No | A deterministic table is more reliable and auditable. |
| Degradation detection | No | Thresholds + a state machine must be predictable. |
| Recovery decision (money) | No | Money actions must be explainable and bounded. |
| Retry timing | No | Rule-based cooldowns; we have no data to justify ML. |
| Failure root-cause diagnosis | **Yes (advisory)** | When a rail degrades, an LLM summarizes the *cluster* of failures. It explains; it never decides. |
| Merchant escalation notes | **Yes (advisory)** | When a payment is unrecoverable, an LLM drafts the ops follow-up note. Text only. |
| Outreach message text | **Yes** | NL generation is what an LLM is good at — and it touches no money. |

---

## The safety contract (guardrails)

The two tests a serious reviewer looks for first live in
[`backend/tests/test_guardrails.py`](backend/tests/test_guardrails.py):

1. **No double-charge.** The same logical payment, submitted twice, executes at
   most once (deterministic idempotency keys + a hard execution check).
2. **Bounded retries.** Retries never exceed the configured cap, and never fire
   into a `DOWN` route.

Plus: recovery-link **TTL** and **amount cap**, retry **cooldown**. All limits
are config values (`backend/app/core/config.py`), tunable at runtime.

---

## Metrics vs a naive baseline

We measure against "retry every failure, up to N times, regardless of route
health." Run it yourself:

```bash
cd backend && python scripts/run_baseline.py --count 200 --outage --seed 7
```

Representative run (200 events, 72 failures, with an outage):

| | Naive | ResQ-Pay |
|---|---|---|
| Recovered | 17 (₹23,388) | **40 (₹41,966)** |
| Risky retries into a failing rail | **44** | ~0 |
| Wasted hard-failure retries | 21 | 0 |
| Recovered via post-outage drain | — | 36 |

The story isn't "we save X%." It's: against a naive loop, ResQ-Pay recovers a
comparable-or-better share of the *safely* recoverable failures **while
eliminating the duplicate-charge risk and wasted fees** the naive loop creates
during an outage.

---

## Layout

```
backend/    FastAPI service — the deterministic spine (see backend/app/services/)
frontend/   React + Vite dashboard + the standalone demo
docs/       architecture, demo script, and ADRs (why SQLite, why no ML, ...)
```

`api/` is thin (HTTP/WS only); `services/` is the brain, one folder per
responsibility; `integrations/razorpay_client.py` is the only file that talks
to Razorpay. Tests mirror the services, heaviest on the deterministic core.

---

## Honesty — what is real vs simulated

- **Money:** Razorpay **Test Mode** only. No real funds move.
- **Outreach:** messages are **generated and displayed, not delivered.** Real
  SMS/WhatsApp is future work.
- **Degradation in the demo:** induced by the generator's `--outage` mode. The
  same detector works on a live webhook stream; we just can't force a real bank
  outage on cue.
- **Retry timing:** rule-based cooldowns, **not** a trained model.
- **Data:** synthetic, from our own script.

---

## Tests

```bash
cd backend && pytest -q      # 22 tests: classifier, degradation, policy, guardrails
```

CI runs lint (`ruff` + `black`) and the test suite on every push.
