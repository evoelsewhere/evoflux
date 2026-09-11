"""Tests for the preview endpoints behind the browser pane's launcher."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.tools.builtin import preview as pv
from app.api.routes.team.preview import router as preview_router


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_config(workspace: Path, configurations: list[dict]) -> None:
    cfg_dir = workspace / ".evoflux"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "launch.json").write_text(
        json.dumps({"version": "0.0.2", "configurations": configurations}),
        encoding="utf-8",
    )


@pytest.fixture
async def client(tmp_path):
    app = FastAPI()
    app.include_router(preview_router, prefix="/api/team")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as http:
        yield http, tmp_path


@pytest.fixture(autouse=True)
async def _clean_servers():
    yield
    for key, server in list(pv._servers.items()):
        if server._process is not None:
            await server._process.terminate()
        pv._servers.pop(key, None)
    pv._server_locks.clear()
    pv._port_locks.clear()


@asynccontextmanager
async def _serving(port: int) -> AsyncIterator[asyncio.Server]:
    """A socket that accepts connections, standing in for a dev server."""

    server = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", port)
    try:
        yield server
    finally:
        server.close()
        # Probe connections may still be draining; closing the listener is
        # what the tests need, so do not block on their teardown.
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(server.wait_closed(), 2)


@pytest.mark.asyncio
async def test_targets_without_config_report_no_source(client):
    http, workspace = client
    response = await http.get(
        "/api/team/preview/targets", params={"workspace": str(workspace)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["targets"] == []
    assert body["source"] is None
    assert body["error"] is None
    assert body["suggested_source"] == ".evoflux/launch.json"


@pytest.mark.asyncio
async def test_targets_list_configurations_in_file_order(client):
    http, workspace = client
    _write_config(
        workspace,
        [
            {
                "name": "web",
                "runtimeExecutable": "npm",
                "runtimeArgs": ["run", "dev"],
                "port": 5173,
                "cwd": "web",
            },
            {
                "name": "api",
                "runtimeExecutable": "uvicorn",
                "port": 8000,
                "dependsOn": "web",
            },
        ],
    )
    response = await http.get(
        "/api/team/preview/targets", params={"workspace": str(workspace)}
    )
    body = response.json()
    assert [target["name"] for target in body["targets"]] == ["web", "api"]
    web, api = body["targets"]
    assert web["port"] == 5173
    assert web["url"] == "http://localhost:5173"
    assert web["command"] == "npm run dev"
    assert web["cwd"] == "web"
    assert web["running"] is False
    assert web["configured"] is True
    assert api["depends_on"] == "web"
    assert body["source"].endswith("launch.json")


@pytest.mark.asyncio
async def test_targets_report_a_port_served_outside_evoflux(client):
    http, workspace = client
    port = _free_port()
    _write_config(
        workspace, [{"name": "web", "runtimeExecutable": "npm", "port": port}]
    )
    async with _serving(port):
        response = await http.get(
            "/api/team/preview/targets", params={"workspace": str(workspace)}
        )
        target = response.json()["targets"][0]
        assert target["running"] is True
        # Nobody spawned it here, so the launcher offers "open", not "stop".
        assert target["reused"] is True
        assert target["pid"] is None


@pytest.mark.asyncio
async def test_invalid_config_is_reported_instead_of_failing(client):
    http, workspace = client
    cfg_dir = workspace / ".evoflux"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "launch.json").write_text("{ not json", encoding="utf-8")
    response = await http.get(
        "/api/team/preview/targets", params={"workspace": str(workspace)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["targets"] == []
    assert "launch config" in (body["error"] or "").lower()


@pytest.mark.asyncio
async def test_targets_reject_a_workspace_that_does_not_exist(client):
    http, workspace = client
    response = await http.get(
        "/api/team/preview/targets",
        params={"workspace": str(workspace / "nope")},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_start_unknown_name_lists_the_configured_ones(client):
    http, workspace = client
    _write_config(
        workspace, [{"name": "web", "runtimeExecutable": "npm", "port": 5173}]
    )
    response = await http.post(
        "/api/team/preview/start",
        json={"workspace": str(workspace), "name": "api"},
    )
    assert response.status_code == 422
    assert "Available: web" in response.json()["detail"]


@pytest.mark.asyncio
async def test_start_reuses_a_port_that_is_already_serving(client):
    http, workspace = client
    port = _free_port()
    _write_config(
        workspace,
        [{"name": "web", "runtimeExecutable": "npm", "port": port}],
    )
    async with _serving(port):
        response = await http.post(
            "/api/team/preview/start",
            json={"workspace": str(workspace), "name": "web"},
        )
        body = response.json()
        assert body["ok"] is True
        assert body["url"] == f"http://localhost:{port}"
        assert "reusing" in body["message"]
        # Tracked under the workspace the request named, not the default
        # sandbox — otherwise the agent would start a second copy.
        assert (str(Path(workspace).resolve()), "web") in pv._servers


@pytest.mark.asyncio
async def test_stop_untracks_an_external_server_without_killing_it(client):
    http, workspace = client
    port = _free_port()
    _write_config(
        workspace, [{"name": "web", "runtimeExecutable": "npm", "port": port}]
    )
    async with _serving(port) as server:
        await http.post(
            "/api/team/preview/start",
            json={"workspace": str(workspace), "name": "web"},
        )
        response = await http.post(
            "/api/team/preview/stop",
            json={"workspace": str(workspace), "name": "web"},
        )
        assert response.status_code == 200
        assert "external server" in response.json()["message"]
        assert server.is_serving()
