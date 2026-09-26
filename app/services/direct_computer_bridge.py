"""Request/response bridge between ``computer_app`` and EvoFlux Desktop.

Computer App Control runs natively in the Tauri shell: capture and input are
Win32 calls against the one window the agent attached to. The chat UI keeps
one WebSocket per session open to this bridge and relays each command to the
shell, so the backend never touches the desktop itself — the same shape as
:mod:`app.services.direct_browser_bridge`, minus the mount handshake, because
nothing has to appear on screen before the agent can list windows.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from app.services import memory_stream_store

# Close code for a socket displaced by a newer attach on the same session.
_WS_DISPLACED = 4409


class DirectComputerUnavailable(RuntimeError):
    """Raised when no desktop shell is connected for a session."""


@dataclass
class _Connection:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    ready: bool = False
    protocol_version: int = 1
    capabilities: dict[str, Any] = field(default_factory=dict)

    def fail_pending(self, message: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(DirectComputerUnavailable(message))
        self.pending.clear()


class DirectComputerBridge:
    """Routes one command at a time to the session's desktop shell."""

    #: How long a command waits for a session's desktop to reconnect.
    reconnect_grace: float = 3.0

    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}

    def is_connected(self, session_id: str) -> bool:
        connection = self._connections.get(session_id)
        return bool(connection and connection.ready)

    async def wait_connected(self, session_id: str, timeout: float = 3.0) -> bool:
        """Wait briefly for a chat that is reconnecting its bridge socket."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.is_connected(session_id):
                return True
            await asyncio.sleep(0.1)
        return self.is_connected(session_id)

    async def attach(self, session_id: str, websocket: WebSocket) -> None:
        connection = _Connection(websocket)
        previous = self._connections.get(session_id)
        self._connections[session_id] = connection
        if previous is not None:
            # Newest attach wins, and the displaced socket is told so with a
            # code it recognises instead of reconnecting into a takeover loop.
            previous.fail_pending("Desktop app control reconnected")
            logger.warning("direct_computer_displaced session_id={}", session_id)
            with suppress(Exception):
                await previous.websocket.close(code=_WS_DISPLACED)
        logger.info("direct_computer_connected session_id={}", session_id)

        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue
                if message.get("type") == "ready":
                    version = message.get("protocol_version", 1)
                    connection.protocol_version = (
                        version if isinstance(version, int) and version > 0 else 1
                    )
                    capabilities = message.get("capabilities")
                    connection.capabilities = (
                        capabilities if isinstance(capabilities, dict) else {}
                    )
                    connection.ready = True
                    logger.info("direct_computer_ready session_id={}", session_id)
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
                            else "Desktop app control command failed"
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if self._connections.get(session_id) is connection:
                self._connections.pop(session_id, None)
            connection.fail_pending("Desktop app control disconnected")
            logger.info("direct_computer_disconnected session_id={}", session_id)

    async def request(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> Any:
        connection = self._connections.get(session_id)
        if connection is None or not connection.ready:
            # The chat may be reconnecting its socket (a UI reload, a card
            # closing): give it a moment rather than failing the action.
            if await self.wait_connected(session_id, timeout=self.reconnect_grace):
                connection = self._connections.get(session_id)
        if connection is None or not connection.ready:
            raise DirectComputerUnavailable(
                "Open this chat in EvoFlux Desktop on Windows or macOS to control apps"
            )
        commands = connection.capabilities.get("commands")
        if isinstance(commands, list) and commands and action not in commands:
            raise DirectComputerUnavailable(
                f"This EvoFlux Desktop does not support '{action}'. Update EvoFlux Desktop."
            )

        async with connection.command_lock:
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
                # The desktop would otherwise finish the action unobserved,
                # and a retry would do it twice. Ask it to stop there.
                with suppress(Exception):
                    async with connection.send_lock:
                        await connection.websocket.send_json({"type": "cancel"})
                raise TimeoutError(
                    f"App control command timed out after {timeout:g}s: {action}. "
                    "The desktop was told to stop it, so the rest of it did not "
                    "happen; take a screenshot to see what did before retrying."
                ) from exc
            finally:
                connection.pending.pop(request_id, None)

    def connection_info(self, session_id: str) -> tuple[int, dict[str, Any]]:
        connection = self._connections.get(session_id)
        if connection is None:
            return 0, {}
        return connection.protocol_version, dict(connection.capabilities)

    async def release_after_turn(self, session_id: str) -> None:
        """Hand back the app a finished turn left attached.

        A hidden app stays off-screen for as long as it is attached. The chat
        UI released it when the turn ended, but only for the chat on screen:
        a turn that ended while the user was in another chat left its app
        hidden for good. The card is open while an app is attached, so its
        socket is too; a session with nothing attached (or stopped, whose
        card must stay) is left alone.
        """
        if not self.is_connected(session_id):
            return
        status = await self.request(session_id, "status", {}, timeout=10.0)
        if isinstance(status, dict) and status.get("attached"):
            await self.request(session_id, "detach", {}, timeout=10.0)
            logger.info("direct_computer_released_after_turn session_id={}", session_id)


direct_computer_bridge = DirectComputerBridge()
memory_stream_store.add_turn_done_listener(direct_computer_bridge.release_after_turn)
