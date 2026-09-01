# Architecture

## Data flow

```
                +-------------------------------+
                |   Event Sources               |
                |   - Razorpay webhooks (test)  |
                |   - Synthetic generator       |
                +---------------+---------------+
                                | payment.failed / captured
                                v
                +-------------------------------+
                |   Ingestion & Normalization   |
                |   verify signature, dedupe,   |
                |   -> internal PaymentEvent    |
                +---------------+---------------+
                                v
                +-------------------------------+
                |   Deterministic Classifier    |   error_code -> {TD | BD}
                +---------------+---------------+
                                |
             +------------------+------------------+
             v                                     v
   +---------------------+            +---------------------------+
   | Degradation Detector|            |  per-transaction context  |
   | rolling window ->   |            |  (attempts, cooldown)     |
   | HEALTHY/DEGRADING/  |            +-------------+-------------+
   | DOWN/RECOVERING     |                          |
   +----------+----------+                          |
              +------------------+------------------+
                                 v
                +-------------------------------+
                |   Recovery Policy Engine      |  Guardrails:
                |   picks ONE bounded action    |  max retries, cooldown,
                +---------------+---------------+  link TTL, amount cap,
                                v                  idempotency
        +-----------+----------+----------+-----------+
        v           v                     v           v
     HOLD /      SAFE RETRY          RECOVERY LINK    STOP
     BACKOFF     (soft, healthy)     + outreach       (honest)
        |           |                     |
        |           |                (LLM writes the
        |           |                 message text only)
        +-----------+----------+----------+
                               v
                +-------------------------------+
                |   Audit Ledger (persist all)  |
                +---------------+---------------+
                                v
                    REST + WebSocket -> Dashboard
```

## Module map

| Path | Responsibility |
|---|---|
| `app/api/` | HTTP/WS transport only — no business logic |
| `app/services/ingestion/` | normalize + dedupe events |
| `app/services/classifier/` | deterministic TD/BD table + lookup |
| `app/services/degradation/` | rolling window + route-health state machine |
| `app/services/policy/` | policy engine + guardrails (the safety contract) |
| `app/services/executors/` | retry / recovery_link / hold / stop |
| `app/services/outreach/` | isolated LLM client + template fallback |
| `app/services/ledger/` | audit persistence + metrics |
| `app/integrations/razorpay_client.py` | the ONLY file that talks to Razorpay |
| `app/pipeline.py` | orchestrates the stages in order |

## Key design principle

The money path is deterministic and testable **without a server** — the
pipeline sequences plain services, so the same logic runs under `pytest`, via
a webhook, or from the synthetic generator. The LLM is walled off on a side
branch that returns only text.
