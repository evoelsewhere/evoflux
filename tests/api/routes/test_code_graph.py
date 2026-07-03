"""Tests for /api/code-graph HTTP routes (P2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.code_graph import router as code_graph_router


async def _wait_until_indexed(client, workspace: Path, *, attempts: int = 200):
    """Poll /status until the background index finishes (or fail loudly)."""
    for _ in range(attempts):
        body = (
            await client.get(
                "/api/code-graph/status", params={"workspace": str(workspace)}
            )
        ).json()
        if not body["indexing"]:
            assert body["index_error"] is None, body["index_error"]
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("index did not finish in time")


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(code_graph_router, prefix="/api/code-graph")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "helpers.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "class Service:\n    def run(self):\n        helper()\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_status_requires_workspace(client):
    res = await client.get("/api/code-graph/status")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_status_unindexed_workspace(client, workspace):
    res = await client.get(
        "/api/code-graph/status", params={"workspace": str(workspace)}
    )
    assert res.status_code == 200
    assert res.json()["indexed"] is False


@pytest.mark.asyncio
async def test_reindex_then_query(client, workspace):
    reindexed = await client.post(
        "/api/code-graph/reindex", params={"workspace": str(workspace)}
    )
    assert reindexed.status_code == 202
    started = reindexed.json()
    assert started["indexing"] is True
    assert started["already_running"] is False

    status = await _wait_until_indexed(client, workspace)
    assert status["indexed"] is True
    assert status["files"] == 2
    assert status["nodes"] > 0

    overview = await client.get(
        "/api/code-graph/overview", params={"workspace": str(workspace)}
    )
    body = overview.json()
    assert body["file_count"] == 2
    assert body["kind_counts"].get("class") == 1

    search = await client.get(
        "/api/code-graph/search",
        params={"workspace": str(workspace), "query": "Service"},
    )
    nodes = search.json()["nodes"]
    assert any(n["qualified_name"] == "Service" for n in nodes)

    run_node = next(
        n
        for n in (
            await client.get(
                "/api/code-graph/search",
                params={"workspace": str(workspace), "query": "run"},
            )
        ).json()["nodes"]
        if n["qualified_name"] == "Service.run"
    )

    neighbors = await client.get(
        "/api/code-graph/neighbors",
        params={
            "workspace": str(workspace),
            "node_id": run_node["id"],
            "direction": "out",
        },
    )
    targets = [n["node"]["name"] for n in neighbors.json()["neighbors"]]
    assert "helper" in targets


@pytest.mark.asyncio
async def test_search_unindexed_returns_404(client, workspace):
    res = await client.get(
        "/api/code-graph/search",
        params={"workspace": str(workspace), "query": "x"},
    )
    assert res.status_code == 404
