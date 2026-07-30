"""Tests for the external-dependency pre-filter and the reject endpoint —
added after a real 4-repo OpenMRS-style project showed "0/27744 cross-repo
references resolved", almost entirely noise from third-party library
imports (Liquibase) that can never be a sibling-repo reference. Mirrors the
fixture/helper style of test_project_cross_repo.py.
"""

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


async def _create_project(*repos: Path):
    async with db_module.async_session_factory() as db:
        project = await proj_svc.create_project(
            db, name="Test Project", workspace_paths=[str(r) for r in repos]
        )
        await db.commit()
        return project.id


async def _reindex(client, workspace: Path) -> None:
    res = await client.post(
        "/api/code-graph/reindex", params={"workspace": str(workspace)}
    )
    assert res.status_code == 202
    await _wait_until_indexed(client, workspace)


async def _resolve_static(client, project_id) -> dict:
    """Kick off a resolve pass and wait for it to finish.

    ``POST .../resolve`` always starts a fire-and-forget background job and
    replies 202 (or 200 if one was already mid-flight) before it completes —
    the response body never carries finished stats. Poll ``.../status``
    instead and read stats off the settled job.
    """
    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/resolve", json={"use_llm": False}
    )
    assert res.status_code in (200, 202)
    for _ in range(300):
        status_res = await client.get(
            f"/api/team/projects/{project_id}/cross-repo/status"
        )
        assert status_res.status_code == 200
        body = status_res.json()
        if not body["running"]:
            job = body["job"]
            assert job["error"] is None, job["error"]
            return job["stats"]
        await asyncio.sleep(0.02)
    raise AssertionError("cross-repo resolve job did not finish in time")


async def _edges(client, project_id, status: str | None = None) -> list[dict]:
    params = {"status": status} if status else {}
    res = await client.get(
        f"/api/team/projects/{project_id}/cross-repo/edges", params=params
    )
    assert res.status_code == 200
    return res.json()


# ── Liquibase-style noise gets filtered, not left "unresolved" forever ─────


@pytest.mark.asyncio
async def test_liquibase_style_import_marked_external(client, tmp_path: Path):
    core = tmp_path / "openmrs-core"
    (core / "api/src/main/java/liquibase/ext/change/core").mkdir(parents=True)
    (core / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<groupId>org.openmrs</groupId><artifactId>openmrs-api</artifactId>"
        "</project>"
    )
    (
        core
        / "api/src/main/java/liquibase/ext/change/core/InsertWithUuidDataChange.java"
    ).write_text(
        "package liquibase.ext.change.core;\n\n"
        "import liquibase.change.ChangeMetadata;\n\n"
        "class InsertWithUuidDataChange {\n"
        "    ChangeMetadata getMetadata() { return null; }\n"
        "}\n"
    )

    other = tmp_path / "openmrs-module-webservices"
    other.mkdir()
    (other / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<groupId>org.openmrs.module</groupId><artifactId>webservices.rest</artifactId>"
        "</project>"
    )
    (other / "Placeholder.java").write_text(
        "package org.openmrs.module.webservices;\n\nclass Placeholder {}\n"
    )

    project_id = await _create_project(core, other)
    await _reindex(client, core)
    await _reindex(client, other)

    stats = await _resolve_static(client, project_id)
    assert stats["still_unresolved"] == 0

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["raw_reference"] == "liquibase.change.ChangeMetadata"
    assert edges[0]["status"] == "external"

    # The "external" bucket is queryable but never counted as "unresolved".
    unresolved = await _edges(client, project_id, status="unresolved")
    assert unresolved == []
    external = await _edges(client, project_id, status="external")
    assert len(external) == 1


# ── The filter must not swallow a genuine cross-repo Java reference ────────


@pytest.mark.asyncio
async def test_real_cross_repo_reference_still_resolves_alongside_noise(
    client, tmp_path: Path
):
    repo_a = tmp_path / "app-a"
    (repo_a / "src").mkdir(parents=True)
    (repo_a / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0">'
        "<groupId>com.acme</groupId><artifactId>app</artifactId>"
        "<dependencies><dependency><groupId>org.liquibase</groupId>"
        "<artifactId>liquibase-core</artifactId></dependency></dependencies>"
        "</project>"
    )
    (repo_a / "src/Main.java").write_text(
        "package com.acme.app;\n\n"
        "import com.acme.other.Helper;\n"
        "import liquibase.change.ChangeMetadata;\n\n"
        "class Main {\n"
        "    void run() { Helper.hello(); }\n"
        "}\n"
    )

    repo_b = tmp_path / "app-b"
    repo_b.mkdir()
    (repo_b / "Helper.java").write_text(
        "package com.acme.other;\n\nclass Helper {\n    static void hello() {}\n}\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    resolved = await _edges(client, project_id, status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["raw_reference"] == "com.acme.other.Helper"
    assert resolved[0]["dst_qualified_name"] == "com.acme.other.Helper"

    external = await _edges(client, project_id, status="external")
    assert len(external) == 1
    assert external[0]["raw_reference"] == "liquibase.change.ChangeMetadata"


# ── Reject endpoint ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reject_dismisses_and_survives_reindex(client, tmp_path: Path):
    repo_a = tmp_path / "reject-app"
    repo_a.mkdir()
    (repo_a / "Main.java").write_text(
        "package com.acme.app;\n\nimport com.acme.mystery.Thing;\n\nclass Main {\n}\n"
    )
    repo_b = tmp_path / "reject-other"
    repo_b.mkdir()
    (repo_b / "Placeholder.java").write_text(
        "package com.acme.other;\n\nclass Placeholder {}\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    unresolved = await _edges(client, project_id, status="unresolved")
    assert len(unresolved) == 1
    edge_id = unresolved[0]["id"]

    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/edges/{edge_id}/reject"
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    # Reindexing the same file again must not resurrect it as "unresolved".
    await _reindex(client, repo_a)
    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["id"] == edge_id
    assert edges[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_unknown_edge_404s(client, tmp_path: Path):
    import uuid

    repo_a = tmp_path / "solo"
    repo_a.mkdir()
    (repo_a / "Main.java").write_text("package com.acme;\n\nclass Main {}\n")
    project_id = await _create_project(repo_a)

    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/edges/{uuid.uuid4()}/reject"
    )
    assert res.status_code == 404
