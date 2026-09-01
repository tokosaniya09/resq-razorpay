"""FastAPI application entry point.

Wires the routers together, owns the app-wide singletons (the pipeline and
the ingestion service), and exposes the WebSocket the dashboard subscribes
to. Business logic lives in services/ and pipeline.py — this file only
assembles and serves.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import dashboard, webhooks
from app.api.ws import broadcaster
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import init_db
from app.pipeline import Pipeline
from app.services.assistant.service import LedgerAssistant
from app.services.ingestion.service import IngestionService

log = get_logger("resq.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    init_db()
    app.state.settings = settings
    app.state.pipeline = Pipeline(settings)
    app.state.ingestion = IngestionService()
    app.state.assistant = LedgerAssistant(
        settings, app.state.pipeline.detector, app.state.pipeline.llm
    )
    log.info(
        "ResQ-Pay started (gateway=%s, llm=%s)",
        app.state.pipeline.gateway.mode,
        "on" if settings.llm_enabled else "template",
    )
    yield
    log.info("ResQ-Pay shutting down")


app = FastAPI(title="ResQ-Pay", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dashboard is same-origin in prod; open for local dev
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks.router, tags=["ingest"])
app.include_router(dashboard.router, tags=["dashboard"])


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "resq-pay",
        "gateway_mode": app.state.pipeline.gateway.mode,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await broadcaster.connect(ws)
    try:
        # Send current route health on connect so a fresh dashboard isn't blank.
        await ws.send_json(
            {
                "type": "snapshot",
                "routes": [
                    {
                        "route": h.route,
                        "state": h.state.value,
                        "failure_rate": h.failure_rate,
                        "samples": h.samples,
                    }
                    for h in app.state.pipeline.detector.snapshot_all()
                ],
            }
        )
        while True:
            # We don't expect inbound messages; keep the socket alive.
            await ws.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(ws)
    except Exception:
        await broadcaster.disconnect(ws)
