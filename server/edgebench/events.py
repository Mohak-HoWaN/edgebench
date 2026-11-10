from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger(__name__)


class EventHub:
    """Fans server events out to WebSocket clients. ``publish`` is safe to call from any thread (the worker is one)."""

    def __init__(self, queue_size: int = 1000) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue_size = queue_size

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        # The loop may close (shutdown) at any moment; an event for no one must never break the publishing worker.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._fan_out, event)

    def _fan_out(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("dropping event for a slow client", extra={"event_type": event.get("type")})

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        self._subs.add(q)
        try:
            yield q
        finally:
            self._subs.discard(q)
