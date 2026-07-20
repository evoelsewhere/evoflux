"""WebBridge manager — in-process bridge between the agent and browser extensions.

The WebBridge feature lets the agent drive the user's *real* Chrome/Edge
browser (with its login sessions) through a browser extension::

    agent → webbridge tool → WebBridgeManager → Chrome extension → CDP → real browser

The extension holds a persistent WebSocket to the relay endpoint
(:mod:`app.api.routes.team.webbridge`). This manager owns the extension
registry, request/response correlation (``request_id`` + per-request
``asyncio.Future``), event/state tracking and stale-extension reaping.

Both consumers are thin adapters over the singleton:

- the ``webbridge`` agent tool calls :meth:`WebBridgeManager.send_command`
  directly (same process — no loopback WebSocket), and
- the relay's WS endpoints translate wire messages into manager calls.

The manager is deliberately framework-light: an extension is registered
with a plain ``send`` callable (the relay passes ``ws.send_text``), so the
service never imports FastAPI.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

#: Extensions silent for longer than this are considered gone.
_IDLE_TIMEOUT = 300.0  # 5 minutes
#: How long a command may wait for the extension's response.
_RESPONSE_TIMEOUT = 30.0
#: How often the stale-extension cleanup pass runs.
_CLEANUP_INTERVAL = 60.0

#: Error returned when a command is issued with no usable extension.
NO_EXTENSION_ERROR = (
    "No browser extension connected. "
    "Install the EvoFlux WebBridge extension and open Chrome/Edge."
)

#: Send half of an extension's WebSocket, supplied by the relay adapter
#: (typically ``ws.send_text``).
SendText = Callable[[str], Awaitable[None]]


class ExtensionConnection:
    """A registered browser extension and its last-reported state."""

    def __init__(
        self,
        *,
        extension_id: str,
        browser: str,
        version: str,
        send: SendText,
    ) -> None:
        self.extension_id = extension_id
        self.browser = browser
        self.version = version
        self.send = send
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.tabs: list[dict[str, Any]] = []
        self.current_url: str = ""
        self.current_title: str = ""

    def is_active(self, now: float) -> bool:
        return now - self.last_seen < _IDLE_TIMEOUT

    def info(self) -> dict[str, Any]:
        """Serializable state — superset of the REST ``ExtensionInfo`` shape."""
        return {
            "extension_id": self.extension_id,
            "browser": self.browser,
            "version": self.version,
            "connected_at": self.connected_at,
            "current_url": self.current_url,
            "current_title": self.current_title,
            "tabs": self.tabs,
        }


class WebBridgeManager:
    """Registry, command router and event hub for WebBridge extensions."""

    def __init__(self) -> None:
        self._extensions: dict[str, ExtensionConnection] = {}
        # request_id → (extension_id, future resolving to the response dict)
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
        # session_id → queues of connected agent-WS consumers (event stream)
        self._agent_queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    # ── Extension lifecycle ─────────────────────────────────────────────

    def register_extension(
        self,
        *,
        extension_id: str,
        browser: str,
        version: str,
        send: SendText,
    ) -> ExtensionConnection:
        """Register (or replace) a connected extension."""
        conn = ExtensionConnection(
            extension_id=extension_id,
            browser=browser,
            version=version,
            send=send,
        )
        self._extensions[extension_id] = conn
        logger.info(
            "webbridge_ext_connected extension_id={} browser={} version={}",
            extension_id,
            browser,
            version,
        )
        return conn

    def unregister_extension(self, extension_id: str) -> None:
        """Drop an extension and fail every command still pending on it."""
        conn = self._extensions.pop(extension_id, None)
        if conn is None:
            return
        logger.info("webbridge_ext_disconnected extension_id={}", extension_id)
        for request_id, (ext_id, fut) in list(self._pending.items()):
            if ext_id != extension_id:
                continue
            self._pending.pop(request_id, None)
            if not fut.done():
                fut.set_result({"success": False, "data": None, "error": "extension disconnected"})

    def get_extension(self, extension_id: str) -> ExtensionConnection | None:
        return self._extensions.get(extension_id)

    def touch(self, extension_id: str) -> None:
        """Refresh an extension's liveness timestamp (heartbeat)."""
        conn = self._extensions.get(extension_id)
        if conn is not None:
            conn.last_seen = time.time()

    # ── Status ──────────────────────────────────────────────────────────

    def active_extensions(self) -> list[ExtensionConnection]:
        now = time.time()
        return [ext for ext in self._extensions.values() if ext.is_active(now)]

    def get_active_extension(self) -> ExtensionConnection | None:
        """Return the most recently seen active extension, or None."""
        active = self.active_extensions()
        if not active:
            return None
        return max(active, key=lambda e: e.last_seen)

    def has_active_extension(self) -> bool:
        return self.get_active_extension() is not None

    def status(self) -> dict[str, Any]:
        """Connection status — the shape behind ``GET /webbridge/status``."""
        active = self.active_extensions()
        return {
            "connected": len(active) > 0,
            "extensions": [ext.info() for ext in active],
        }

    # ── Events / responses coming from the extension ────────────────────

    def handle_event(self, extension_id: str, event: str, data: dict[str, Any]) -> None:
        """Track extension state and broadcast the event to agent consumers."""
        conn = self._extensions.get(extension_id)
        if conn is not None:
            conn.last_seen = time.time()
            if event == "tab_updated":
                conn.tabs = data.get("tabs", [])
                conn.current_url = data.get("url", "")
                conn.current_title = data.get("title", "")

        envelope = {
            "type": "event",
            "event": event,
            "data": data,
            "extension_id": extension_id,
        }
        for queues in self._agent_queues.values():
            for queue in queues:
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass

    def handle_response(
        self,
        request_id: str,
        *,
        success: bool,
        data: Any,
        error: str | None,
    ) -> bool:
        """Resolve the pending command for *request_id*. False if unknown."""
        entry = self._pending.pop(request_id, None)
        if entry is None:
            logger.debug("webbridge_orphan_response request_id={}", request_id)
            return False
        _, fut = entry
        if not fut.done():
            fut.set_result({"success": success, "data": data, "error": error})
        return True

    # ── Commands (agent → extension) ────────────────────────────────────

    async def send_command(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send *action* to the active extension and await its response.

        Always resolves to ``{"success": bool, "data": ..., "error": ...}``
        (plus ``request_id`` for wire correlation) — never raises for
        routine failures like a missing extension or a timeout.
        """
        if action == "status":
            # Answered locally — does not need an extension.
            return {"success": True, "data": self.status(), "error": None}

        ext = self.get_active_extension()
        if ext is None:
            return {"success": False, "data": None, "error": NO_EXTENSION_ERROR}

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = (ext.extension_id, fut)

        command = {
            "type": "command",
            "request_id": request_id,
            "action": action,
            "params": params or {},
        }
        try:
            await ext.send(json.dumps(command))
        except Exception as e:
            self._pending.pop(request_id, None)
            logger.debug(
                "webbridge_send_failed extension_id={} error={}", ext.extension_id, e
            )
            return {
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": "Extension disconnected",
            }

        try:
            result = await asyncio.wait_for(fut, timeout=_RESPONSE_TIMEOUT)
        except TimeoutError:
            self._pending.pop(request_id, None)
            return {
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": "Extension response timeout (30s)",
            }
        return {"request_id": request_id, **result}

    # ── Agent event subscriptions (relay's agent WS endpoint) ───────────

    def subscribe_agent(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._agent_queues.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe_agent(
        self, session_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        queues = self._agent_queues.get(session_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            self._agent_queues.pop(session_id, None)

    # ── Stale-extension cleanup ─────────────────────────────────────────

    def cleanup_stale(self, now: float | None = None) -> list[str]:
        """Drop extensions past the idle timeout; returns removed ids."""
        now = time.time() if now is None else now
        stale = [
            eid
            for eid, ext in self._extensions.items()
            if not ext.is_active(now)
        ]
        for eid in stale:
            self.unregister_extension(eid)
            logger.info("webbridge_ext_timeout extension_id={}", eid)
        return stale

    async def run_cleanup_loop(self) -> None:
        """Background task: periodically reap silent extensions."""
        while True:
            await asyncio.sleep(_CLEANUP_INTERVAL)
            self.cleanup_stale()


#: Process singleton.
webbridge_manager = WebBridgeManager()
