"""WebBridge — WebSocket relay between agent and browser extension.

Provides:
- ``WS /webbridge/relay`` — extension connects here to register
- ``WS /webbridge/agent/{session_id}`` — external agent consumers
- ``GET /webbridge/status`` — list connected extensions

Architecture:
    Agent ←→ Relay Server ←→ Chrome Extension ←→ Real Browser (CDP)

These endpoints are thin adapters over
:data:`app.services.webbridge_service.webbridge_manager`, which owns the
extension registry, request/response correlation and event fan-out. The
in-process ``webbridge`` agent tool talks to the same manager directly, so
it never needs a loopback WebSocket of its own.

Both WS endpoints require the desktop token via the ``?_token=`` query
param when one is configured (see :mod:`app.core.desktop_auth`) — without
it, any local web page could open a socket and impersonate an extension
or drive the user's browser. When no token is configured (CLI mode) the
endpoints stay open, matching the HTTP middleware's behaviour.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

from app.core.desktop_auth import (
    _QS_TOKEN_PARAM,
    desktop_token_matches,
    expected_desktop_token,
)
from app.services.webbridge_service import NO_EXTENSION_ERROR, webbridge_manager

router = APIRouter()


async def _ws_authorized(ws: WebSocket) -> bool:
    """Enforce the desktop token on a WebSocket handshake.

    Mirrors :class:`app.core.desktop_auth.DesktopTokenMiddleware` for WS
    endpoints: open when no token is configured; otherwise the ``?_token=``
    query param must match. On failure the socket is closed with code 4401
    *before* accept so no handler logic runs.
    """
    expected = expected_desktop_token()
    if not expected:
        return True
    if desktop_token_matches(ws.query_params.get(_QS_TOKEN_PARAM), expected):
        return True
    logger.warning("webbridge_ws_rejected path={}", ws.url.path)
    await ws.close(code=4401)
    return False


# ── REST status ───────────────────────────────────────────────────────────────


class ExtensionInfo(BaseModel):
    extension_id: str
    browser: str
    version: str
    connected_at: float
    current_url: str = ""
    current_title: str = ""
    tabs: list[dict[str, Any]] = Field(default_factory=list)


class WebBridgeStatusResponse(BaseModel):
    connected: bool
    extensions: list[ExtensionInfo] = Field(default_factory=list)


@router.get("/status")
async def get_webbridge_status() -> WebBridgeStatusResponse:
    """Return list of connected browser extensions."""
    status = webbridge_manager.status()
    return WebBridgeStatusResponse(
        connected=status["connected"],
        extensions=[ExtensionInfo(**ext) for ext in status["extensions"]],
    )


# ── Extension WebSocket ───────────────────────────────────────────────────────


@router.websocket("/relay")
async def extension_relay(ws: WebSocket) -> None:
    """WebSocket endpoint for browser extensions to connect.

    Protocol (extension → relay):
    - ``{"type": "register", "extension_id": "...", "browser": "chrome", "version": "120"}``
    - ``{"type": "response", "request_id": "...", "success": true, "data": {...}}``
    - ``{"type": "event", "event": "tab_updated", "data": {...}}``
    - ``{"type": "ping"}`` — heartbeat (refreshes liveness)

    Protocol (relay → extension):
    - ``{"type": "registered", "extension_id": "..."}``
    - ``{"type": "command", "request_id": "...", "action": "...", "params": {...}}``
    - ``{"type": "pong"}`` — heartbeat reply
    """
    if not await _ws_authorized(ws):
        return
    await ws.accept()
    extension_id: str | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type")

            if msg_type == "register":
                extension_id = msg.get("extension_id") or str(uuid.uuid4())
                webbridge_manager.register_extension(
                    extension_id=extension_id,
                    browser=msg.get("browser", "unknown"),
                    version=msg.get("version", "unknown"),
                    send=ws.send_text,
                )
                await ws.send_text(
                    json.dumps({"type": "registered", "extension_id": extension_id})
                )
            elif extension_id is None:
                # Everything below requires a registered connection.
                continue
            elif msg_type == "response":
                webbridge_manager.handle_response(
                    msg.get("request_id", ""),
                    success=msg.get("success", False),
                    data=msg.get("data"),
                    error=msg.get("error"),
                )
            elif msg_type == "event":
                webbridge_manager.handle_event(
                    extension_id, msg.get("event"), msg.get("data", {})
                )
            elif msg_type == "ping":
                webbridge_manager.touch(extension_id)
                await ws.send_text(json.dumps({"type": "pong"}))
            elif msg_type == "pong":
                webbridge_manager.touch(extension_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("webbridge_ext_error extension_id={} error={}", extension_id, e)
    finally:
        if extension_id:
            # Fails every command still pending on this extension.
            webbridge_manager.unregister_extension(extension_id)


# ── Agent WebSocket ───────────────────────────────────────────────────────────


@router.websocket("/agent/{session_id}")
async def agent_relay(ws: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for external agent consumers of WebBridge.

    The in-process ``webbridge`` tool does not use this endpoint — it calls
    the manager directly. This remains for external consumers and tests.

    Protocol (agent → relay):
    - ``{"action": "navigate", "url": "..."}``
    - ``{"action": "click", "x": 100, "y": 200}``
    - ``{"action": "type", "text": "hello"}``
    - ``{"action": "screenshot"}``
    - ``{"action": "get_tabs"}``
    - ``{"action": "switch_tab", "index": 0}``
    - ``{"action": "evaluate", "script": "document.title"}``
    - ``{"action": "extract"}``
    - ``{"action": "status"}``

    Protocol (relay → agent):
    - ``{"type": "response", "request_id": "...", "success": true, "data": {...}}``
    - ``{"type": "event", "event": "...", "data": {...}}``
    - ``{"type": "no_extension", "error": "..."}``
    """
    if not await _ws_authorized(ws):
        return
    await ws.accept()
    queue = webbridge_manager.subscribe_agent(session_id)
    logger.info("webbridge_agent_connected session_id={}", session_id)

    async def forward_events() -> None:
        try:
            while True:
                event = await queue.get()
                await ws.send_text(json.dumps(event))
        except Exception:
            pass

    event_task = asyncio.create_task(forward_events())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action")
            if not action:
                continue

            if action != "status" and not webbridge_manager.has_active_extension():
                await ws.send_text(
                    json.dumps({"type": "no_extension", "error": NO_EXTENSION_ERROR})
                )
                continue

            params = {k: v for k, v in msg.items() if k != "action"}
            result = await webbridge_manager.send_command(session_id, action, params)
            await ws.send_text(json.dumps({"type": "response", **result}))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("webbridge_agent_error session_id={} error={}", session_id, e)
    finally:
        event_task.cancel()
        webbridge_manager.unsubscribe_agent(session_id, queue)
        logger.info("webbridge_agent_disconnected session_id={}", session_id)
