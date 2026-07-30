"""Tests for the explicit-path-dependency Tier A resolution added on top of
/api/team/projects/{id}/cross-repo/* — npm file:/workspace:, uv path=, Cargo
path=, and Go replace, each resolved for free (no LLM) via the source repo's
own manifest. Mirrors the fixture/helper style of test_project_cross_repo.py.
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


async def _create_project(repo_a: Path, repo_b: Path):
    # See test_project_cross_repo.py's _create_project for why this is a
    # module attribute lookup rather than a top-level `from ... import
    # async_session_factory` — the latter would bind the pre-patch,
    # pre-setup_db production factory at collection time.
    async with db_module.async_session_factory() as db:
        project = await proj_svc.create_project(
            db, name="Test Project", workspace_paths=[str(repo_a), str(repo_b)]
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


async def _edges(client, project_id) -> list[dict]:
    res = await client.get(f"/api/team/projects/{project_id}/cross-repo/edges")
    assert res.status_code == 200
    return res.json()


# ── npm: "file:" protocol ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_npm_file_protocol_resolves_via_path_dependency(client, tmp_path: Path):
    repo_b = tmp_path / "shared"
    repo_b.mkdir()
    (repo_b / "package.json").write_text('{"name": "shared"}')
    (repo_b / "index.js").write_text("function helper() {\n  return 1;\n}\n")

    repo_a = tmp_path / "app"
    repo_a.mkdir()
    (repo_a / "package.json").write_text(
        '{"name": "app", "dependencies": {"shared": "file:../shared"}}'
    )
    (repo_a / "index.js").write_text(
        'import { helper } from "shared";\n\nfunction run() {\n  return helper();\n}\n'
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["method"] == "static_path_dependency"
    assert edges[0]["dst_qualified_name"] == "helper"


# ── npm: "workspace:" protocol (member resolved via workspaces glob) ───────


@pytest.mark.asyncio
async def test_npm_workspace_protocol_resolves_via_path_dependency(
    client, tmp_path: Path
):
    repo_a = tmp_path / "app"
    repo_a.mkdir()
    (repo_a / "packages" / "shared").mkdir(parents=True)
    (repo_a / "packages" / "shared" / "package.json").write_text(
        '{"name": "@acme/shared"}'
    )
    (repo_a / "packages" / "shared" / "index.js").write_text(
        "function helper() {\n  return 1;\n}\n"
    )
    (repo_a / "package.json").write_text(
        '{"name": "app", "workspaces": ["packages/*"], '
        '"dependencies": {"@acme/shared": "workspace:*"}}'
    )
    (repo_a / "index.js").write_text(
        'import { helper } from "@acme/shared";\n\n'
        "function run() {\n  return helper();\n}\n"
    )
    # "packages/shared" is registered as its OWN CodingWorkspace below (the
    # scenario this test exercises: a sub-package tracked separately from its
    # monorepo root). Without excluding it here, repo_a's own reindex would
    # also walk into that subdirectory and resolve `helper` as an ordinary
    # same-workspace symbol — never producing a cross-repo edge to prove this
    # test actually needs to.
    (repo_a / ".gitignore").write_text("packages/\n")

    repo_b = repo_a / "packages" / "shared"

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["method"] == "static_path_dependency"


# ── Python: uv path source ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uv_path_source_resolves_via_path_dependency(client, tmp_path: Path):
    repo_b = tmp_path / "shared_lib"
    repo_b.mkdir()
    (repo_b / "pyproject.toml").write_text('[project]\nname = "shared_lib"\n')
    (repo_b / "lib.py").write_text("def helper():\n    return 1\n")

    repo_a = tmp_path / "app"
    repo_a.mkdir()
    (repo_a / "pyproject.toml").write_text(
        '[project]\nname = "app"\n\n'
        "[tool.uv.sources]\n"
        'shared_lib = { path = "../shared_lib" }\n'
    )
    (repo_a / "main.py").write_text(
        "from shared_lib import helper\n\ndef run():\n    return helper()\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["method"] == "static_path_dependency"
    assert edges[0]["dst_qualified_name"] == "helper"


# ── Rust: Cargo path dependency ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cargo_path_dependency_resolves(client, tmp_path: Path):
    repo_b = tmp_path / "shared_crate"
    repo_b.mkdir()
    (repo_b / "Cargo.toml").write_text('[package]\nname = "shared_crate"\n')
    (repo_b / "lib.rs").write_text("pub fn helper() -> i32 {\n    1\n}\n")

    repo_a = tmp_path / "app_crate"
    repo_a.mkdir()
    (repo_a / "Cargo.toml").write_text(
        '[package]\nname = "app"\n\n'
        "[dependencies]\n"
        'shared_crate = { path = "../shared_crate" }\n'
    )
    (repo_a / "main.rs").write_text(
        "use shared_crate::helper;\n\nfn run() -> i32 {\n    helper()\n}\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["method"] == "static_path_dependency"
    assert edges[0]["dst_qualified_name"] == "helper"


# ── Go: "replace" directive (repo-level link — bare package import has no ──
# ── single resolvable symbol, matching the pre-existing Java/manifest tiers'
# ── own "repo-level, not symbol-precise" fallback behavior) ─────────────────


@pytest.mark.asyncio
async def test_go_replace_resolves_repo_level_link(client, tmp_path: Path):
    repo_b = tmp_path / "other"
    repo_b.mkdir()
    (repo_b / "go.mod").write_text("module github.com/acme/other\n\ngo 1.22\n")
    (repo_b / "other.go").write_text("package other\n\nfunc Helper() {}\n")

    repo_a = tmp_path / "goapp"
    repo_a.mkdir()
    (repo_a / "go.mod").write_text(
        "module github.com/acme/app\n\ngo 1.22\n\n"
        "replace github.com/acme/other => ../other\n"
    )
    (repo_a / "main.go").write_text(
        'package main\n\nimport "github.com/acme/other"\n\n'
        "func run() {\n\tother.Helper()\n}\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 1
    assert stats["still_unresolved"] == 0

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["method"] == "static_path_dependency"
    assert edges[0]["status"] == "resolved"


# ── Negative: no explicit path dep and no matching identity → untouched ────


@pytest.mark.asyncio
async def test_no_path_dependency_falls_through_unresolved(client, tmp_path: Path):
    repo_b = tmp_path / "unrelated"
    repo_b.mkdir()
    (repo_b / "pyproject.toml").write_text('[project]\nname = "totally_different"\n')
    (repo_b / "lib.py").write_text("def mystery_symbol():\n    return 1\n")

    repo_a = tmp_path / "app2"
    repo_a.mkdir()
    (repo_a / "pyproject.toml").write_text('[project]\nname = "app2"\n')
    (repo_a / "main.py").write_text(
        "from mystery_pkg import mystery_symbol\n\n"
        "def run():\n    return mystery_symbol()\n"
    )

    project_id = await _create_project(repo_a, repo_b)
    await _reindex(client, repo_a)
    await _reindex(client, repo_b)

    stats = await _resolve_static(client, project_id)
    assert stats["static_resolved"] == 0
    assert stats["still_unresolved"] == 1

    edges = await _edges(client, project_id)
    assert len(edges) == 1
    assert edges[0]["status"] == "unresolved"
    assert edges[0]["method"] is None
