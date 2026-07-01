"""Tests for /api/team/projects/{id}/cross-repo/* HTTP routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.db as db_module
from app.api.routes.code_graph import router as code_graph_router
from app.api.routes.team.projects import router as projects_router
from app.services import coding_project_service as proj_svc


async def _wait_until_indexed(client, workspace: Path, *, attempts: int = 300):
    """Poll /code-graph/status until the background index finishes."""
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
    app.include_router(projects_router, prefix="/api/team")
    app.include_router(code_graph_router, prefix="/api/code-graph")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
def java_project_repos(tmp_path: Path) -> tuple[Path, Path]:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "Main.java").write_text(
        "package com.example.bar;\n\n"
        "import com.example.foo.Baz;\n\n"
        "class Main {\n    void run() {\n        Baz.hello();\n    }\n}\n",
        encoding="utf-8",
    )
    (repo_b / "Baz.java").write_text(
        "package com.example.foo;\n\nclass Baz {\n    static void hello() {}\n}\n",
        encoding="utf-8",
    )
    return repo_a, repo_b


async def _create_project(repo_a: Path, repo_b: Path):
    # Access async_session_factory via the module, not a bound name imported
    # at collection time — conftest.py's setup_db fixture repoints
    # db_module.async_session_factory to the ephemeral test DB, but that
    # patch lands after pytest has already collected (imported) this file.
    # A top-level `from app.core.db import async_session_factory` would bind
    # to the pre-patch production factory instead.
    async with db_module.async_session_factory() as db:
        project = await proj_svc.create_project(
            db, name="Test Project", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        return project.id


async def _reindex(client, workspace: Path) -> None:
    res = await client.post("/api/code-graph/reindex", params={"workspace": str(workspace)})
    assert res.status_code == 202
    await _wait_until_indexed(client, workspace)


@pytest.mark.asyncio
async def test_resolve_requires_existing_project(client):
    import uuid

    res = await client.post(
        f"/api/team/projects/{uuid.uuid4()}/cross-repo/resolve", json={"use_llm": False}
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_edges_lists_unresolved_import(client, java_project_repos):
    repo_a, repo_b = java_project_repos
    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)

    res = await client.get(f"/api/team/projects/{project_id}/cross-repo/edges")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["raw_reference"] == "com.example.foo.Baz"
    assert body[0]["status"] == "unresolved"
    assert body[0]["method"] is None


@pytest.mark.asyncio
async def test_resolve_sync_static_only(client, java_project_repos):
    repo_a, repo_b = java_project_repos
    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)

    # repo-b (the resolution target) hasn't been indexed yet — Tier A should
    # find nothing to link against.
    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/resolve", json={"use_llm": False}
    )
    assert res.status_code == 200
    stats = res.json()
    assert stats["static_resolved"] == 0
    assert stats["still_unresolved"] == 1

    # Index repo-b, then resolving again should find the FQN match.
    await _reindex(client, repo_b)

    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/resolve", json={"use_llm": False}
    )
    assert res.status_code == 200
    stats = res.json()
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    edges = (
        await client.get(f"/api/team/projects/{project_id}/cross-repo/edges")
    ).json()
    assert len(edges) == 1
    assert edges[0]["status"] == "resolved"
    assert edges[0]["method"] == "static_fqn"
    assert edges[0]["dst_qualified_name"] == "com.example.foo.Baz"

    status_res = await client.get(f"/api/team/projects/{project_id}/cross-repo/status")
    assert status_res.status_code == 200
    assert status_res.json()["running"] is False


@pytest.mark.asyncio
async def test_resolve_with_llm_starts_background_job(client, java_project_repos):
    repo_a, repo_b = java_project_repos
    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)

    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/resolve", json={"use_llm": True}
    )
    assert res.status_code == 202
    job = res.json()
    assert job["use_llm"] is True
    assert job["status"] in ("running", "done")

    # Poll until the job (Tier A only for now — Tier B lands in a later
    # phase) finishes.
    for _ in range(300):
        status_res = await client.get(
            f"/api/team/projects/{project_id}/cross-repo/status"
        )
        body = status_res.json()
        if not body["running"]:
            assert body["job"]["status"] == "done"
            assert body["job"]["error"] is None
            return
        await asyncio.sleep(0.02)
    raise AssertionError("cross-repo resolve job did not finish in time")
