"""WebSocket broadcaster (§6.8, §11).

Keeps the set of connected dashboards and fans out pipeline messages to all
of them. The pipeline calls `broadcast(...)`; it does not know or care how
many dashboards are watching. Thin transport layer — no business logic.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class Broadcaster:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


# single app-wide instance
broadcaster = Broadcaster()
