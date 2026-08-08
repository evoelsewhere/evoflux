"""Unified process manager composition and termination tests."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.tools.builtin.preview import PreviewServer
from app.services import process_manager as manager
from app.services.terminal_service import TerminalSession


def test_list_active_processes_combines_all_registries(monkeypatch):
    command = SimpleNamespace(
        process_id="proc_1234567890",
        command="bun run dev",
        scope="session:session-command",
        pid=101,
        cwd="/tmp/command",
        elapsed_seconds=12.5,
    )
    preview_process = SimpleNamespace(
        elapsed_seconds=7.0,
        running=True,
        pid=202,
    )
    preview = PreviewServer(
        name="web",
        port=5173,
        command="bun run dev",
        workdir="/tmp/preview",
        config_fingerprint="fingerprint",
        session_id="session-preview",
        _process=preview_process,
    )
    terminal = TerminalSession(
        session_id="session-terminal",
        terminal_id="terminal-a",
        backend=SimpleNamespace(pid=303),
        cols=80,
        rows=24,
        cwd="/tmp/terminal",
        started_at=time.monotonic() - 3,
    )
    monkeypatch.setattr(manager, "tracked_processes", lambda: [command])
    monkeypatch.setattr(
        manager, "preview_servers", lambda: [(("/tmp/workspace", "web"), preview)]
    )
    monkeypatch.setattr(manager.terminal_manager, "list_sessions", lambda: [terminal])

    processes = manager.list_active_processes()

    assert {process.kind for process in processes} == {
        "command",
        "preview",
        "terminal",
    }
    by_kind = {process.kind: process for process in processes}
    assert by_kind["command"].session_id == "session-command"
    assert by_kind["preview"].metadata["url"] == "http://localhost:5173"
    assert by_kind["terminal"].pid == 303
    assert by_kind["terminal"].cwd == "/tmp/terminal"


@pytest.mark.asyncio
async def test_terminate_active_process_routes_to_owner(monkeypatch):
    command_stop = AsyncMock(return_value=True)
    preview_stop = AsyncMock(return_value=True)
    terminal_stop = AsyncMock()
    preview = PreviewServer(
        name="web",
        port=5173,
        command="bun run dev",
        workdir="/tmp/preview",
        config_fingerprint="fingerprint",
    )
    terminal = TerminalSession(
        session_id="session-terminal",
        terminal_id="terminal-a",
        backend=SimpleNamespace(pid=303),
        cols=80,
        rows=24,
    )
    monkeypatch.setattr(manager, "terminate_tracked_process", command_stop)
    monkeypatch.setattr(manager, "terminate_preview_server", preview_stop)
    monkeypatch.setattr(
        manager, "preview_servers", lambda: [(("/tmp/workspace", "web"), preview)]
    )
    monkeypatch.setattr(manager.terminal_manager, "list_sessions", lambda: [terminal])
    monkeypatch.setattr(manager.terminal_manager, "close", terminal_stop)

    assert await manager.terminate_active_process("proc_1234567890")
    command_stop.assert_awaited_once_with("proc_1234567890")

    preview_id = manager._opaque_id("preview", "/tmp/workspace", "web")
    assert await manager.terminate_active_process(preview_id)
    preview_stop.assert_awaited_once_with("/tmp/workspace", "web")

    terminal_id = manager._opaque_id("terminal", "session-terminal", "terminal-a")
    assert await manager.terminate_active_process(terminal_id)
    terminal_stop.assert_awaited_once_with("session-terminal", terminal_id="terminal-a")
    assert not await manager.terminate_active_process("missing")
