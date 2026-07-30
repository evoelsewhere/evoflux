"""Tests for POST /api/team/projects/{id}/code-graph/reindex.

This is the single-call replacement for the old client-side pattern of
POSTing /code-graph/reindex once per repo and then separately chaining
/cross-repo/resolve after polling for completion — see CrossRepoLinksPanel.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.db as db_module
from app.api.routes.code_graph import router as code_graph_router
from app.api.routes.team.projects import router as projects_router
from app.services import coding_project_service as proj_svc


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
    # See test_project_cross_repo.py::_create_project for why this goes
    # through db_module rather than a top-level import.
    async with db_module.async_session_factory() as db:
        project = await proj_svc.create_project(
            db, name="Test Project", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        return project.id


async def _wait_until_settled(
    client: AsyncClient, project_id, *, attempts: int = 300
) -> list[dict]:
    """Poll project code-graph status until no repo is indexing, then wait
    for any auto-chained resolve job to finish too."""
    for _ in range(attempts):
        repos = (
            await client.get(f"/api/team/projects/{project_id}/code-graph/status")
        ).json()
        if not any(r["indexing"] for r in repos):
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("indexing did not finish in time")

    for _ in range(attempts):
        status = (
            await client.get(f"/api/team/projects/{project_id}/cross-repo/status")
        ).json()
        if not status["running"]:
            return repos
        await asyncio.sleep(0.02)
    raise AssertionError("cross-repo resolve did not finish in time")


@pytest.mark.asyncio
async def test_reindex_requires_existing_project(client):
    res = await client.post(f"/api/team/projects/{uuid.uuid4()}/code-graph/reindex")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_single_call_indexes_every_repo_and_autoresolves(
    client, java_project_repos
):
    repo_a, repo_b = java_project_repos
    project_id = await _create_project(repo_a, repo_b)

    res = await client.post(f"/api/team/projects/{project_id}/code-graph/reindex")
    assert res.status_code == 202
    body = res.json()
    assert body["indexing"] is True
    assert body["repo_count"] == 2
    assert body["already_running"] == 0
    assert body["will_resolve"] is True

    repos = await _wait_until_settled(client, project_id)
    assert all(r["indexed"] for r in repos)
    assert all(r["index_error"] is None for r in repos)

    # The Java FQN reference from repo-a into repo-b should have resolved
    # without any separate /cross-repo/resolve call from the test.
    edges = (
        await client.get(f"/api/team/projects/{project_id}/cross-repo/edges")
    ).json()
    assert len(edges) == 1
    assert edges[0]["status"] == "resolved"
    assert edges[0]["dst_qualified_name"] == "com.example.foo.Baz"


@pytest.mark.asyncio
async def test_already_running_repo_is_joined_not_duplicated(
    client, java_project_repos
):
    repo_a, repo_b = java_project_repos
    project_id = await _create_project(repo_a, repo_b)

    first = await client.post(f"/api/team/projects/{project_id}/code-graph/reindex")
    assert first.status_code == 202

    # Fire a second call immediately — repos are still indexing, so this
    # should report them as already-running rather than starting duplicate
    # jobs.
    second = await client.post(f"/api/team/projects/{project_id}/code-graph/reindex")
    assert second.status_code == 202
    body = second.json()
    assert body["repo_count"] == 2
    assert body["already_running"] >= 1

    await _wait_until_settled(client, project_id)


@pytest.mark.asyncio
async def test_single_repo_project_does_not_trigger_resolve(client, tmp_path: Path):
    repo = tmp_path / "solo-repo"
    repo.mkdir()
    (repo / "Main.java").write_text("class Main {}\n", encoding="utf-8")

    async with db_module.async_session_factory() as db:
        project = await proj_svc.create_project(
            db, name="Solo Project", workspace_paths=[str(repo)]
        )
        await db.commit()
        project_id = project.id

    res = await client.post(f"/api/team/projects/{project_id}/code-graph/reindex")
    assert res.status_code == 202
    body = res.json()
    assert body["repo_count"] == 1
    assert body["will_resolve"] is False

    for _ in range(300):
        repos = (
            await client.get(f"/api/team/projects/{project_id}/code-graph/status")
        ).json()
        if not any(r["indexing"] for r in repos):
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("indexing did not finish in time")

    status = (
        await client.get(f"/api/team/projects/{project_id}/cross-repo/status")
    ).json()
    assert status["running"] is False
    assert status["job"] is None
