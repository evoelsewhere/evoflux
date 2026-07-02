"""Tests for cross-repo resolution of non-import edge kinds (EDGE_USES /
EDGE_INHERITS / EDGE_IMPLEMENTS) — the extension that lets a DI-wired field
or a base type link across repos, not just an import statement. Mirrors the
fixture/helper style of test_project_cross_repo_filtering.py.
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
    res = await client.post("/api/code-graph/reindex", params={"workspace": str(workspace)})
    assert res.status_code == 202
    await _wait_until_indexed(client, workspace)


async def _resolve_static(client, project_id, *, attempts: int = 300) -> dict:
    """POST resolve, then poll status until the background job finishes.

    The endpoint always starts a real ``asyncio`` background task (202) —
    it only returns 200 when a job for this project happened to already be
    running. Reading stats straight off the POST response would race the
    background task, so poll ``/cross-repo/status`` to completion instead.
    """
    res = await client.post(
        f"/api/team/projects/{project_id}/cross-repo/resolve", json={"use_llm": False}
    )
    assert res.status_code in (200, 202)
    for _ in range(attempts):
        status = (
            await client.get(f"/api/team/projects/{project_id}/cross-repo/status")
        ).json()
        if not status["running"]:
            assert status["job"] is not None
            assert status["job"]["error"] is None, status["job"]["error"]
            return status["job"]["stats"]
        await asyncio.sleep(0.02)
    raise AssertionError("cross-repo resolve did not finish in time")


async def _edges(client, project_id, status: str | None = None) -> list[dict]:
    params = {"status": status} if status else {}
    res = await client.get(
        f"/api/team/projects/{project_id}/cross-repo/edges", params=params
    )
    assert res.status_code == 200
    return res.json()


@pytest.mark.asyncio
async def test_autowired_field_resolves_to_sibling_repo_class(client, tmp_path: Path):
    """A DI-wired field (`@Autowired`/uninitialized final) pointing at a type
    with no local definition ends up a resolved, kind="uses" CrossRepoEdge
    once the sibling repo defining that type joins the same project.

    ``ConceptService`` is deliberately declared with no package so Tier A's
    direct FQN match applies — ``uses_target()`` only ever extracts the bare
    type name as written at the use site (no import statement to draw a
    fully-qualified path from, unlike EDGE_IMPORTS), so a package-qualified
    sibling would require Tier B (FTS5 lexical), a separate async pass not
    exercised by ``_resolve_static``.
    """
    repo_a = tmp_path / "rest-module"
    repo_a.mkdir()
    (repo_a / "ConceptResource.java").write_text(
        "public class ConceptResource {\n"
        "    private final ConceptService conceptService;\n"
        "    public ConceptResource(ConceptService conceptService) {\n"
        "        this.conceptService = conceptService;\n"
        "    }\n"
        "}\n"
    )

    repo_b = tmp_path / "core"
    repo_b.mkdir()
    (repo_b / "ConceptService.java").write_text("public class ConceptService {}\n")

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    unresolved = await _edges(client, project_id, status="unresolved")
    assert [e["kind"] for e in unresolved] == ["uses"]
    assert unresolved[0]["raw_reference"] == "ConceptService"

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    resolved = await _edges(client, project_id, status="resolved")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "uses"
    assert resolved[0]["dst_qualified_name"] == "ConceptService"
    assert resolved[0]["method"] is not None


@pytest.mark.asyncio
async def test_resolved_uses_edge_survives_incremental_reindex_after_field_removed(
    client, tmp_path: Path
):
    """A resolved cross-repo edge is only ever cleaned up by the reattach
    tier, never just because the local reference disappeared (``method IS
    NULL`` is the only delete condition, by design, so a resolution pass
    never races with reindex). Documented pre-existing behavior — this locks
    it in as intentional now that non-import kinds can hit it too."""
    repo_a = tmp_path / "rest-module"
    repo_a.mkdir()
    src = repo_a / "ConceptResource.java"
    src.write_text(
        "public class ConceptResource {\n"
        "    private final ConceptService conceptService;\n"
        "    public ConceptResource(ConceptService conceptService) {\n"
        "        this.conceptService = conceptService;\n"
        "    }\n"
        "}\n"
    )

    repo_b = tmp_path / "core"
    repo_b.mkdir()
    (repo_b / "ConceptService.java").write_text("public class ConceptService {}\n")

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)
    await _resolve_static(client, project_id)

    resolved = await _edges(client, project_id, status="resolved")
    assert len(resolved) == 1
    edge_id = resolved[0]["id"]

    # Remove the field entirely and reindex — the edge is untouched: it's a
    # "resolved" (method-stamped) row, and only method-IS-NULL rows are
    # deleted/replaced on reindex.
    src.write_text("public class ConceptResource {\n}\n")
    await _reindex(client, repo_a)

    edges = await _edges(client, project_id)
    assert [e["id"] for e in edges] == [edge_id]
    assert edges[0]["status"] == "resolved"
