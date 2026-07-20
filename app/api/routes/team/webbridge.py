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
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
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


# ── Guided browser launch (auto-install) ──────────────────────────────────────

_EXTENSION_DIR_ENV = "EVOFLUX_WEBBRIDGE_EXTENSION_DIR"

# Chrome install locations probed on Windows when ``chrome`` is not on PATH.
_WIN_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)

_LAUNCH_MESSAGE = (
    "Browser launched with the WebBridge extension loaded. Note: Chrome must "
    "have been FULLY quit before this launch — an already-running Chrome "
    "ignores the extension flags. Chrome also shows a developer-mode "
    "extension bubble on each launch; that is expected for unpacked "
    "extensions — keep the extension enabled to use WebBridge."
)


class LaunchBrowserResponse(BaseModel):
    ok: bool
    browser: str
    message: str


def _resolve_extension_dir() -> Path | None:
    """Locate the unpacked WebBridge extension directory.

    The ``EVOFLUX_WEBBRIDGE_EXTENSION_DIR`` override wins when set; otherwise
    fall back to ``<repo root>/extensions/webbridge`` (repo root = two parents
    up from the ``app`` package). Returns ``None`` when no candidate resolves
    to an existing directory — the caller turns that into a 404 with
    manual-install instructions.
    """
    override = os.environ.get(_EXTENSION_DIR_ENV)
    if override:
        candidate = Path(override).expanduser()
    else:
        import app as _app_pkg

        repo_root = Path(_app_pkg.__file__).resolve().parent.parent
        candidate = repo_root / "extensions" / "webbridge"
    return candidate if candidate.is_dir() else None


def _chrome_launch_command(
    extension_dir: Path,
) -> tuple[str, list[str], dict[str, Any]]:
    """Return ``(browser_label, argv, popen_kwargs)`` for the current platform.

    Raises ``RuntimeError`` with a user-facing message when no Chrome-family
    executable can be found or the platform is unsupported.
    """
    load_arg = f"--load-extension={extension_dir}"
    if sys.platform == "darwin":
        return "chrome", ["open", "-na", "Google Chrome", "--args", load_arg], {}
    if sys.platform == "win32":
        exe = shutil.which("chrome")
        if exe is None:
            for candidate in _WIN_CHROME_CANDIDATES:
                expanded = os.path.expandvars(candidate)
                if Path(expanded).is_file():
                    exe = expanded
                    break
        if exe is None:
            raise RuntimeError(
                "Google Chrome was not found on this machine. Install Chrome, "
                "or load the extension manually from chrome://extensions."
            )
        # DETACHED_PROCESS + CREATE_NO_WINDOW: fully independent of this
        # process, no console window. getattr defaults keep this importable
        # (and testable) on non-Windows hosts where the constants don't exist.
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        return "chrome", [exe, load_arg], {"creationflags": creationflags}
    if sys.platform.startswith("linux"):
        exe = shutil.which("google-chrome") or shutil.which("chromium")
        if exe is None:
            raise RuntimeError(
                "Neither google-chrome nor chromium was found on PATH. Install "
                "Chrome or Chromium, or load the extension manually from "
                "chrome://extensions."
            )
        browser = "chromium" if "chromium" in Path(exe).name else "chrome"
        return browser, [exe, load_arg], {}
    raise RuntimeError(
        f"Unsupported platform '{sys.platform}'. Load the extension manually "
        "from chrome://extensions instead."
    )


@router.post("/launch-browser")
async def launch_browser() -> LaunchBrowserResponse:
    """Launch the user's Chrome-family browser with the extension loaded.

    Guided auto-install: spawns Chrome with ``--load-extension`` pointing at
    the unpacked WebBridge extension, so the user never has to visit
    chrome://extensions by hand. The process is spawned detached — this
    endpoint never waits on the browser.
    """
    extension_dir = _resolve_extension_dir()
    if extension_dir is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "WebBridge extension directory not found (looked at "
                f"${_EXTENSION_DIR_ENV} and <install>/extensions/webbridge). "
                "Install it manually: open chrome://extensions, enable "
                "Developer mode, then 'Load unpacked' and select the "
                "extensions/webbridge directory from your EvoFlux installation."
            ),
        )
    try:
        browser, argv, popen_kwargs = _chrome_launch_command(extension_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        subprocess.Popen(  # noqa: S603 — argv is built from trusted local paths
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **popen_kwargs,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to launch {browser}: {exc}"
        ) from exc
    logger.info("webbridge_launch_browser browser={} argv={}", browser, argv)
    return LaunchBrowserResponse(ok=True, browser=browser, message=_LAUNCH_MESSAGE)


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
