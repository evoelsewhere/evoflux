"""Interactive terminal WebSocket — the transport for EvoFlux's AI Terminal.

``WS /team/{session_id}/terminal`` bridges a browser xterm.js client to a
persistent PTY shell (:mod:`app.services.terminal_service`). The shell is
spawned in the session's mode-aware working directory (the coding/aim
workspace, or the forge session dir) so the terminal always lands where the
agent is working.

Protocol
--------
Server → Client:
- **Binary frame**: raw PTY output bytes (written straight into xterm).
- **JSON text frame** ``{"type": "exit"}``: the shell process ended.

Client → Server (JSON text frames):
- ``{"type": "input", "data": "..."}`` — keystrokes to the shell
- ``{"type": "resize", "cols": N, "rows": N}`` — window resize
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.paths import session_workspace_dir
from app.services.terminal_service import terminal_manager

router = APIRouter()


async def _resolve_cwd_and_env(session_id: str) -> tuple[str, dict[str, str]]:
    """The mode-aware cwd + context env for a session's shell.

    coding/aim → the bound workspace (aim's is the target repo); forge → the
    per-session workspace dir. Falls back to the session dir if the row can't
    be read (e.g. a terminal opened before the first message persisted it).
    """
    mode = "forge"
    workspace: str | None = None
    try:
        from app.core import db as db_module
        from app.models.chat import ChatSession, normalize_mode

        async with db_module.async_session_factory() as db:
            row = await db.get(ChatSession, UUID(session_id))
            if row is not None:
                mode = normalize_mode(row.mode)
                workspace = row.workspace
    except Exception as exc:  # noqa: BLE001 — never block opening a terminal
        logger.debug("terminal_session_lookup_failed session_id={} error={}", session_id, exc)

    cwd = str(session_workspace_dir(session_id, workspace))
    return cwd, {"EVOFLUX_MODE": mode}


@router.websocket("/{session_id}/terminal")
async def terminal_ws(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    cols, rows = _int_param(ws, "cols", 80), _int_param(ws, "rows", 24)
    cwd, env = await _resolve_cwd_and_env(session_id)

    try:
        terminal_manager.attach(session_id, cwd=cwd, env=env, cols=cols, rows=rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("terminal_attach_failed session_id={} error={}", session_id, exc)
        await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await ws.close()
        return

    terminal_manager.resize(session_id, cols, rows)
    queue = terminal_manager.subscribe(session_id)
    logger.debug("terminal_ws_open session_id={}", session_id)

    # Replay recent scrollback so a reconnecting client isn't staring at a
    # blank screen with a live-but-contextless shell.
    replay = terminal_manager.snapshot(session_id)
    if replay:
        await ws.send_bytes(replay)

    async def pump_output() -> None:
        while True:
            chunk = await queue.get()
            if chunk is None:  # shell exited
                await ws.send_text(json.dumps({"type": "exit"}))
                return
            await ws.send_bytes(chunk)

    output_task = asyncio.create_task(pump_output())
    try:
        while True:
            raw = await ws.receive_text()
            _handle_client_message(session_id, raw)
    except WebSocketDisconnect:
        logger.debug("terminal_ws_close session_id={}", session_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("terminal_ws_error session_id={} error={}", session_id, exc)
    finally:
        output_task.cancel()
        terminal_manager.unsubscribe(session_id, queue)


def _handle_client_message(session_id: str, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return
    action = msg.get("type")
    if action == "input":
        data = msg.get("data")
        if isinstance(data, str):
            terminal_manager.write(session_id, data.encode("utf-8"))
    elif action == "resize":
        cols, rows = msg.get("cols"), msg.get("rows")
        if isinstance(cols, int) and isinstance(rows, int):
            terminal_manager.resize(session_id, cols, rows)


def _int_param(ws: WebSocket, name: str, default: int) -> int:
    try:
        return int(ws.query_params.get(name, default))
    except (TypeError, ValueError):
        return default
