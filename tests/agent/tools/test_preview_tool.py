"""Tests for the preview dev-server lifecycle tool."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

from app.agent.tools.builtin import preview as pv


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_config(workspace: Path, configurations: list[dict]) -> None:
    cfg_dir = workspace / ".evoflux"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "launch.json").write_text(
        json.dumps({"version": "0.0.1", "configurations": configurations})
    )


def _server_config(name: str, port: int) -> dict:
    """A real tiny HTTP server as the dev-server command."""
    code = (
        "import http.server, socketserver, sys; "
        "print('dev server starting', flush=True); "
        f"httpd = socketserver.TCPServer(('127.0.0.1', {port}), "
        "http.server.SimpleHTTPRequestHandler); "
        "httpd.serve_forever()"
    )
    return {
        "name": name,
        "runtimeExecutable": sys.executable,
        "runtimeArgs": ["-c", code],
        "port": port,
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(pv, "_workspace_root", lambda: tmp_path)
    yield tmp_path


@pytest.fixture(autouse=True)
async def _clean_servers():
    yield
    for key, server in list(pv._servers.items()):
        if server._bg is not None:
            await server._bg.stop()
        pv._servers.pop(key, None)


# ── Config handling ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_without_config_explains_format(workspace):
    with pytest.raises(Exception, match="launch.json"):
        await pv.preview_tool.arun(action="start")


@pytest.mark.asyncio
async def test_start_unknown_name_lists_available(workspace):
    _write_config(workspace, [{"name": "web", "runtimeExecutable": "x", "port": 1}])
    with pytest.raises(Exception, match="Available: web"):
        await pv.preview_tool.arun(action="start", name="api")


@pytest.mark.asyncio
async def test_multiple_configs_require_name(workspace):
    _write_config(
        workspace,
        [
            {"name": "web", "runtimeExecutable": "x", "port": 1},
            {"name": "api", "runtimeExecutable": "y", "port": 2},
        ],
    )
    with pytest.raises(Exception, match="pass name="):
        await pv.preview_tool.arun(action="start")


@pytest.mark.asyncio
async def test_claude_launch_json_fallback(workspace):
    cfg_dir = workspace / ".claude"
    cfg_dir.mkdir()
    port = _free_port()
    (cfg_dir / "launch.json").write_text(
        json.dumps({"configurations": [_server_config("web", port)]})
    )
    out = await pv.preview_tool.arun(action="start")
    assert f"http://localhost:{port}" in out
    assert "ready" in out


# ── Lifecycle ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_status_logs_stop_roundtrip(workspace):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])

    out = await pv.preview_tool.arun(action="start", name="web")
    assert f"Server 'web' ready on http://localhost:{port}" in out

    status = await pv.preview_tool.arun(action="status")
    assert "web: running" in status
    assert f"http://localhost:{port}" in status

    logs = await pv.preview_tool.arun(action="logs", name="web")
    assert "dev server starting" in logs

    logs_filtered = await pv.preview_tool.arun(
        action="logs", name="web", search="no-such-line"
    )
    assert "no matching" in logs_filtered

    # Second start reuses the tracked server instead of spawning again
    again = await pv.preview_tool.arun(action="start", name="web")
    assert "already running" in again

    stopped = await pv.preview_tool.arun(action="stop", name="web")
    assert "Stopped 'web'" in stopped
    assert await pv._port_open(port) is False


@pytest.mark.asyncio
async def test_start_reuses_externally_running_port(workspace):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])

    with socket.socket() as s:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        out = await pv.preview_tool.arun(action="start", name="web")
        assert "reusing the existing server" in out

        status = await pv.preview_tool.arun(action="status")
        assert "reused external" in status

        logs = await pv.preview_tool.arun(action="logs", name="web")
        assert "logs unavailable" in logs

        stopped = await pv.preview_tool.arun(action="stop", name="web")
        assert "not stopped" in stopped


@pytest.mark.asyncio
async def test_command_that_exits_reports_failure_with_output(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [
            {
                "name": "broken",
                "runtimeExecutable": sys.executable,
                "runtimeArgs": ["-c", "print('boom: missing module'); raise SystemExit(3)"],
                "port": port,
            }
        ],
    )
    out = await pv.preview_tool.arun(action="start", name="broken")
    assert "exited with code 3" in out
    assert "boom: missing module" in out


@pytest.mark.asyncio
async def test_missing_executable_reports_cleanly(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [
            {
                "name": "ghost",
                "runtimeExecutable": "/nonexistent/binary-xyz",
                "runtimeArgs": [],
                "port": port,
            }
        ],
    )
    out = await pv.preview_tool.arun(action="start", name="ghost")
    assert "Executable not found" in out


@pytest.mark.asyncio
async def test_status_empty(workspace):
    out = await pv.preview_tool.arun(action="status")
    assert "No preview servers" in out
