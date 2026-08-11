"""Plugin-owned bridge between Artifact Fabric and the desktop WebView.

The Python sidecar deliberately does not ship a browser.  New PowerPoint decks
are authored as inert HTML and rendered by the already-running desktop WebView.
This broker keeps that exchange local, correlated, cancellable, and bounded.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

RENDERER_LEASE_SECONDS = 15.0
HEARTBEAT_RETENTION_SECONDS = 300.0


@dataclass(slots=True)
class _PendingRender:
    request_id: UUID
    session_id: str
    payload: dict[str, Any]
    future: asyncio.Future[dict[str, Any]]
    claimed: bool = False


class HtmlSlideRenderBroker:
    """Coordinate one-shot slide renders with a session's active WebView."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._queues: dict[str, deque[UUID]] = defaultdict(deque)
        self._pending: dict[UUID, _PendingRender] = {}
        self._heartbeats: dict[str, float] = {}

    async def heartbeat(self, session_id: str) -> None:
        async with self._lock:
            now = monotonic()
            self._heartbeats = {
                key: timestamp
                for key, timestamp in self._heartbeats.items()
                if now - timestamp <= HEARTBEAT_RETENTION_SECONDS
            }
            self._heartbeats[session_id] = now

    async def request(
        self,
        session_id: str | None,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        if not session_id:
            raise RuntimeError(
                "HTML slide rendering requires an active desktop session."
            )
        loop = asyncio.get_running_loop()
        request_id = uuid4()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        pending = _PendingRender(request_id, session_id, payload, future)
        async with self._lock:
            last_heartbeat = self._heartbeats.get(session_id)
            if (
                last_heartbeat is None
                or monotonic() - last_heartbeat > RENDERER_LEASE_SECONDS
            ):
                raise RuntimeError(
                    "The HTML slide renderer is unavailable. Keep the EvoFlux "
                    "desktop window open while generating slides."
                )
            self._pending[request_id] = pending
            self._queues[session_id].append(request_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "The HTML slide renderer is unavailable. Keep the EvoFlux desktop "
                "window open while generating slides."
            ) from exc
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)
                queue = self._queues.get(session_id)
                if queue is not None:
                    try:
                        queue.remove(request_id)
                    except ValueError:
                        pass
                    if not queue:
                        self._queues.pop(session_id, None)

    async def claim(self, session_id: str) -> dict[str, Any] | None:
        async with self._lock:
            queue = self._queues.get(session_id)
            while queue:
                request_id = queue.popleft()
                pending = self._pending.get(request_id)
                if pending is None or pending.future.done():
                    continue
                pending.claimed = True
                return {
                    "request_id": str(request_id),
                    **pending.payload,
                }
            self._queues.pop(session_id, None)
            return None

    async def complete(
        self,
        session_id: str,
        request_id: UUID,
        result: dict[str, Any],
    ) -> bool:
        async with self._lock:
            pending = self._pending.get(request_id)
            if (
                pending is None
                or pending.session_id != session_id
                or pending.future.done()
            ):
                return False
            pending.future.set_result(result)
            return True

    async def fail(
        self,
        session_id: str,
        request_id: UUID,
        message: str,
    ) -> bool:
        async with self._lock:
            pending = self._pending.get(request_id)
            if (
                pending is None
                or pending.session_id != session_id
                or pending.future.done()
            ):
                return False
            pending.future.set_exception(RuntimeError(message))
            return True


_broker = HtmlSlideRenderBroker()


def get_html_slide_render_broker() -> HtmlSlideRenderBroker:
    return _broker


__all__ = ["HtmlSlideRenderBroker", "get_html_slide_render_broker"]
