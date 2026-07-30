"""Request/response bridge between agent tools and the desktop child WebView."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger


class DirectBrowserUnavailable(RuntimeError):
    """Raised when no desktop browser panel is connected for a session."""


@dataclass
class _Connection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    ready: bool = False

    def fail_pending(self, message: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(DirectBrowserUnavailable(message))
        self.pending.clear()


class DirectBrowserBridge:
    """Routes one command at a time to the user-visible browser session."""

    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}
        self._presence: dict[str, _Connection] = {}

    def is_connected(self, session_id: str) -> bool:
        connection = self._connections.get(session_id)
        return bool(connection and connection.ready)

    def is_available(self, session_id: str) -> bool:
        return session_id in self._presence

    def available_session_ids(self) -> list[str]:
        return sorted(self._presence)

    async def attach_presence(self, session_id: str, websocket: WebSocket) -> None:
        connection = _Connection(websocket)
        self._presence[session_id] = connection
        logger.info("direct_browser_presence_connected session_id={}", session_id)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if self._presence.get(session_id) is connection:
                self._presence.pop(session_id, None)
            logger.info(
                "direct_browser_presence_disconnected session_id={}", session_id
            )

    async def request_mount(self, session_id: str) -> bool:
        presence = self._presence.get(session_id)
        if presence is None:
            return False
        try:
            async with presence.send_lock:
                await presence.websocket.send_json({"action": "open"})
            return True
        except Exception:
            if self._presence.get(session_id) is presence:
                self._presence.pop(session_id, None)
            return False

    async def wait_connected(self, session_id: str, timeout: float = 8.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.is_connected(session_id):
                return True
            await asyncio.sleep(0.1)
        return False

    async def attach(self, session_id: str, websocket: WebSocket) -> None:
        connection = _Connection(websocket)
        previous = self._connections.get(session_id)
        if previous is not None:
            previous.fail_pending("Desktop browser reconnected")
        self._connections[session_id] = connection
        logger.info("direct_browser_connected session_id={}", session_id)

        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "ready":
                    connection.ready = True
                    logger.info("direct_browser_ready session_id={}", session_id)
                    continue
                request_id = message.get("id")
                if not isinstance(request_id, str):
                    continue
                future = connection.pending.get(request_id)
                if future is None or future.done():
                    continue
                if message.get("ok") is True:
                    future.set_result(message.get("result"))
                else:
                    error = message.get("error")
                    future.set_exception(
                        RuntimeError(
                            error
                            if isinstance(error, str)
                            else "Browser command failed"
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if self._connections.get(session_id) is connection:
                self._connections.pop(session_id, None)
            connection.fail_pending("Desktop browser disconnected")
            logger.info("direct_browser_disconnected session_id={}", session_id)

    async def request(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any],
        *,
        timeout: float = 35.0,
    ) -> Any:
        connection = self._connections.get(session_id)
        if connection is None or not connection.ready:
            raise DirectBrowserUnavailable(
                "Open the Browser panel in the EvoFlux desktop app first"
            )

        request_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        connection.pending[request_id] = future
        try:
            async with connection.send_lock:
                await connection.websocket.send_json(
                    {"id": request_id, "action": action, "params": params}
                )
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(f"Browser command timed out: {action}") from exc
        finally:
            connection.pending.pop(request_id, None)


direct_browser_bridge = DirectBrowserBridge()
