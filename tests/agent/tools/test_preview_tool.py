"""Tests for the preview dev-server lifecycle tool."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
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
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            denied_roots=[],
            denied_patterns=[],
        )
    )
    try:
        yield tmp_path
    finally:
        _sandbox_ctx.reset(token)


@pytest.fixture(autouse=True)
async def _clean_servers():
    yield
    for key, server in list(pv._servers.items()):
        if server._process is not None:
            await server._process.terminate()
        pv._servers.pop(key, None)
    pv._server_locks.clear()
    pv._port_locks.clear()


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
async def test_config_rejects_duplicate_names_and_invalid_fields(workspace):
    _write_config(
        workspace,
        [
            {"name": "web", "runtimeExecutable": "x", "port": 5173},
            {"name": "web", "runtimeExecutable": "y", "port": 5174},
        ],
    )
    with pytest.raises(Exception, match="duplicate configuration names"):
        await pv.preview_tool.arun(action="start", name="web")

    _write_config(
        workspace,
        [
            {
                "name": "web",
                "runtimeExecutable": "x",
                "runtimeArgs": "run dev",
                "port": 70_000,
            }
        ],
    )
    with pytest.raises(Exception, match="invalid port"):
        await pv.preview_tool.arun(action="start", name="web")


def test_config_allows_alternative_configurations_on_same_port(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [
            {"name": "dev", "runtimeExecutable": "x", "port": port},
            {"name": "prod", "runtimeExecutable": "y", "port": port},
        ],
    )

    configurations, _source = pv._load_configurations(workspace)

    assert [configuration.name for configuration in configurations] == ["dev", "prod"]


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
    assert pv._server_locks == {}
    assert pv._port_locks == {}


@pytest.mark.asyncio
async def test_start_reuses_externally_running_port(workspace):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])

    external = await asyncio.start_server(
        lambda _reader, writer: writer.close(), "127.0.0.1", port
    )
    try:
        out = await pv.preview_tool.arun(action="start", name="web")
        assert "reusing the existing server" in out

        status = await pv.preview_tool.arun(action="status")
        assert "reused external" in status

        logs = await pv.preview_tool.arun(action="logs", name="web")
        assert "logs unavailable" in logs

        stopped = await pv.preview_tool.arun(action="stop", name="web")
        assert "not stopped" in stopped
    finally:
        external.close()
        await external.wait_closed()


@pytest.mark.asyncio
async def test_reuse_existing_false_rejects_busy_port(workspace):
    port = _free_port()
    config = _server_config("web", port)
    config["reuseExisting"] = False
    _write_config(workspace, [config])

    external = await asyncio.start_server(
        lambda _reader, writer: writer.close(), "127.0.0.1", port
    )
    try:
        out = await pv.preview_tool.arun(action="start", name="web")
    finally:
        external.close()
        await external.wait_closed()

    assert "reuseExisting=false" in out
    assert pv._servers == {}


@pytest.mark.asyncio
async def test_status_prunes_stale_external_server(workspace):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])
    external = await asyncio.start_server(
        lambda _reader, writer: writer.close(), "127.0.0.1", port
    )
    try:
        await pv.preview_tool.arun(action="start", name="web")
    finally:
        external.close()
        await external.wait_closed()

    status = await pv.preview_tool.arun(action="status")

    assert "stale external tracking removed" in status
    assert pv._servers == {}


@pytest.mark.asyncio
async def test_config_change_restarts_managed_server(workspace):
    first_port = _free_port()
    second_port = _free_port()
    while second_port == first_port:
        second_port = _free_port()
    _write_config(workspace, [_server_config("web", first_port)])
    await pv.preview_tool.arun(action="start", name="web")
    first_pid = next(iter(pv._servers.values())).pid

    _write_config(workspace, [_server_config("web", second_port)])
    status = await pv.preview_tool.arun(action="status")
    out = await pv.preview_tool.arun(action="start", name="web")
    second_pid = next(iter(pv._servers.values())).pid

    assert "configuration changed; call start to restart" in status
    assert f"http://localhost:{second_port}" in out
    assert second_pid != first_pid
    assert await pv._port_open(first_port) is False


@pytest.mark.asyncio
async def test_command_that_exits_reports_failure_with_output(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [
            {
                "name": "broken",
                "runtimeExecutable": sys.executable,
                "runtimeArgs": [
                    "-c",
                    "print('boom: missing module'); raise SystemExit(3)",
                ],
                "port": port,
            }
        ],
    )
    out = await pv.preview_tool.arun(action="start", name="broken")
    assert "exited with code 3" in out
    assert "boom: missing module" in out
    assert pv._servers == {}


@pytest.mark.asyncio
async def test_start_timeout_stops_and_untracks_process(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [
            {
                "name": "sleeping",
                "runtimeExecutable": sys.executable,
                "runtimeArgs": ["-c", "import time; time.sleep(30)"],
                "port": port,
                "startupTimeoutSeconds": 1,
            }
        ],
    )

    out = await pv.preview_tool.arun(action="start", name="sleeping")

    assert "did not open port" in out
    assert "process was stopped" in out
    assert pv._servers == {}
    assert pv._server_locks == {}
    assert pv._port_locks == {}


@pytest.mark.asyncio
async def test_cancelled_start_stops_and_untracks_process(workspace, monkeypatch):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])
    blocked = asyncio.Event()

    async def wait_forever(_server, _timeout):
        await blocked.wait()
        return None

    monkeypatch.setattr(pv, "_wait_for_port", wait_forever)
    task = asyncio.create_task(pv.preview_tool.arun(action="start", name="web"))
    for _ in range(100):
        if pv._servers:
            break
        await asyncio.sleep(0.01)
    server = next(iter(pv._servers.values()))

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert server.running is False
    assert pv._servers == {}
    assert pv._port_locks == {}


@pytest.mark.asyncio
async def test_cwd_must_remain_inside_authorized_workspace(workspace):
    outside = workspace.parent / "outside"
    outside.mkdir(exist_ok=True)
    config = _server_config("web", _free_port())
    config["cwd"] = "../outside"
    _write_config(workspace, [config])

    with pytest.raises(Exception, match="outside the allowed sandbox roots"):
        await pv.preview_tool.arun(action="start", name="web")


@pytest.mark.asyncio
async def test_concurrent_start_spawns_only_one_process(workspace):
    port = _free_port()
    _write_config(workspace, [_server_config("web", port)])

    first, second = await asyncio.gather(
        pv.preview_tool.arun(action="start", name="web"),
        pv.preview_tool.arun(action="start", name="web"),
    )

    assert len(pv._servers) == 1
    assert sum("Server 'web' ready on" in value for value in (first, second)) == 1
    assert sum("already running" in value for value in (first, second)) == 1


@pytest.mark.asyncio
async def test_same_port_is_not_reused_under_a_second_configuration(workspace):
    port = _free_port()
    _write_config(
        workspace,
        [_server_config("web", port), _server_config("api", port)],
    )
    first, second = await asyncio.gather(
        pv.preview_tool.arun(action="start", name="web"),
        pv.preview_tool.arun(action="start", name="api"),
    )

    assert sum(" ready on " in out for out in (first, second)) == 1
    assert (
        sum(
            "already managed by preview configuration" in out for out in (first, second)
        )
        == 1
    )
    assert len(pv._servers) == 1
    assert pv._port_locks == {}


@pytest.mark.asyncio
async def test_shutdown_stops_all_managed_servers_and_clears_registry(workspace):
    web_port = _free_port()
    api_port = _free_port()
    while api_port == web_port:
        api_port = _free_port()
    _write_config(
        workspace,
        [_server_config("web", web_port), _server_config("api", api_port)],
    )
    await pv.preview_tool.arun(action="start", name="web")
    await pv.preview_tool.arun(action="start", name="api")

    await pv.stop_all_servers()

    assert pv._servers == {}
    assert pv._server_locks == {}
    assert pv._port_locks == {}
    assert await pv._port_open(web_port) is False
    assert await pv._port_open(api_port) is False


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
