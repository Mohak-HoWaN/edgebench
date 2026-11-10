from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import Engine, text

from . import __version__, queue
from .events import EventHub
from .worker import Worker

router = APIRouter()


class DbHealth(BaseModel):
    ok: bool
    journal_mode: str | None = None
    error: str | None = None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    uptime_seconds: float
    db: DbHealth
    queue: dict[str, int]
    worker_running: bool
    disk_free_gb: float


def _db_health(engine: Engine) -> DbHealth:
    try:
        with engine.connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        return DbHealth(ok=True, journal_mode=str(mode))
    except Exception as exc:  # report, never raise: the health endpoint must answer when the database is broken
        return DbHealth(ok=False, error=f"{type(exc).__name__}: {exc}")


@router.get("/api/health")
def health(request: Request) -> Health:
    state = request.app.state
    db = _db_health(state.engine)
    worker: Worker | None = state.worker
    worker_ok = worker is None or worker.alive
    return Health(
        status="ok" if db.ok and worker_ok else "degraded",
        version=__version__,
        uptime_seconds=round(time.monotonic() - state.started, 1),
        db=db,
        queue=queue.counts(state.engine) if db.ok else {},
        worker_running=worker is not None and worker.alive,
        disk_free_gb=round(shutil.disk_usage(state.settings.data_dir).free / 1e9, 1),
    )


def _same_origin(ws: WebSocket) -> bool:
    """Refuse a browser page from another origin; clients that send no Origin header (scripts, agents) are allowed."""
    origin = ws.headers.get("origin")
    return origin is None or urlparse(origin).netloc == ws.headers.get("host")


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    if not _same_origin(ws):
        await ws.close(code=1008)
        return
    await ws.accept()
    hub: EventHub = ws.app.state.hub
    await ws.send_json({"type": "hello", "version": __version__})
    async with hub.subscribe() as inbox:
        outgoing = asyncio.ensure_future(inbox.get())
        incoming = asyncio.ensure_future(ws.receive_text())  # only used to notice that the client went away
        try:
            while True:
                await asyncio.wait({outgoing, incoming}, return_when=asyncio.FIRST_COMPLETED)
                if incoming.done():
                    incoming.result()  # raises WebSocketDisconnect on close
                    incoming = asyncio.ensure_future(ws.receive_text())
                if outgoing.done():
                    event: dict[str, Any] = outgoing.result()
                    await ws.send_json(event)
                    outgoing = asyncio.ensure_future(inbox.get())
        except (WebSocketDisconnect, RuntimeError):
            pass  # the client went away, possibly between waking up and sending
        finally:
            outgoing.cancel()
            incoming.cancel()
            await asyncio.gather(
                outgoing, incoming, return_exceptions=True
            )  # retrieve results so nothing is logged as lost
