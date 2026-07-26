"""Tests for cross-repo resolution Tier 0 (reattach) via ``resolve_project``.

Regression coverage for a signature mismatch: ``resolve_project`` always
calls ``_reattach_stale_src(..., changed_workspaces=...)``, so that helper
must accept the parameter — it previously didn't, raising ``TypeError`` on
every incremental resolve pass (``changed_workspaces`` not None).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.core.db as db_module
from app.services.code_graph.cross_repo import resolve_project
from app.services.coding_project_service import create_project
from app.services.coding_workspace_service import upsert_coding_workspace


async def _setup_project(tmp_path: Path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Cross Repo Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        repo_a_ws = await upsert_coding_workspace(db, path=str(repo_a))
        repo_b_ws = await upsert_coding_workspace(db, path=str(repo_b))
        await db.commit()
        return project.id, repo_a_ws.id, repo_b_ws.id


async def _seed_node(db, *, workspace_id, name, file_path, line_start=1, line_end=5):
    from app.models.code_graph import CodeNode

    node = CodeNode(
        workspace_id=workspace_id,
        kind="method",
        name=name,
        qualified_name=f"{file_path}.{name}",
        file_path=file_path,
        language="java",
        line_start=line_start,
        line_end=line_end,
    )
    db.add(node)
    await db.flush()
    await db.refresh(node)
    return node


async def _seed_resolved_edge_with_stale_src(
    db, *, project_id, src_workspace_id, src_file_path, src_line
):
    """A ``resolved`` edge whose ``src_node_id`` is stale (None) — the exact
    shape ``_reattach_stale_src`` looks for."""
    from app.models.code_graph import CrossRepoEdge

    edge = CrossRepoEdge(
        project_id=project_id,
        src_workspace_id=src_workspace_id,
        src_file_path=src_file_path,
        src_line=src_line,
        src_node_id=None,
        raw_reference="some.Reference",
        status="resolved",
        kind="calls",
    )
    db.add(edge)
    await db.flush()
    await db.refresh(edge)
    return edge


@pytest.mark.asyncio
async def test_resolve_project_with_changed_workspaces_reattaches_stale_src(
    setup_db, tmp_path: Path
):
    """The bug: calling resolve_project with a non-None changed_workspaces
    used to raise TypeError from _reattach_stale_src. It should instead run
    and reattach src_node_id for edges in the changed workspace."""
    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        node = await _seed_node(
            db, workspace_id=repo_a_id, name="doThing", file_path="Main.java"
        )
        edge = await _seed_resolved_edge_with_stale_src(
            db,
            project_id=project_id,
            src_workspace_id=repo_a_id,
            src_file_path="Main.java",
            src_line=3,
        )
        await db.commit()
        node_id = node.id
        edge_id = edge.id

    async with db_module.async_session_factory() as db:
        stats = await resolve_project(
            db, project_id=project_id, changed_workspaces={repo_a_id}
        )

    assert stats.reattached >= 1

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge

        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed is not None
        assert refreshed.src_node_id == node_id


@pytest.mark.asyncio
async def test_resolve_project_changed_workspaces_skips_other_workspaces(
    setup_db, tmp_path: Path
):
    """An edge whose src_workspace_id isn't in changed_workspaces is left alone."""
    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        await _seed_node(
            db, workspace_id=repo_a_id, name="doThing", file_path="Main.java"
        )
        edge = await _seed_resolved_edge_with_stale_src(
            db,
            project_id=project_id,
            src_workspace_id=repo_a_id,
            src_file_path="Main.java",
            src_line=3,
        )
        await db.commit()
        edge_id = edge.id

    # Only repo_b "changed" — repo_a's stale edge should not be touched.
    async with db_module.async_session_factory() as db:
        await resolve_project(db, project_id=project_id, changed_workspaces={repo_b_id})

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge

        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed is not None
        assert refreshed.src_node_id is None


@pytest.mark.asyncio
async def test_changed_target_resolves_unresolved_edge_from_unchanged_source(
    setup_db, tmp_path: Path
):
    from app.models.code_graph import CrossRepoEdge

    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        edge = CrossRepoEdge(
            project_id=project_id,
            src_workspace_id=repo_a_id,
            src_file_path="Client.java",
            raw_reference="com.example.NewService",
            dst_name_hint="NewService",
            status="unresolved",
            kind="imports",
        )
        db.add(edge)
        await db.commit()
        edge_id = edge.id

    async with db_module.async_session_factory() as db:
        target = await _seed_node(
            db,
            workspace_id=repo_b_id,
            name="NewService",
            file_path="NewService.java",
        )
        target.qualified_name = "com.example.NewService"
        db.add(target)
        await db.commit()
        target_id = target.id

    async with db_module.async_session_factory() as db:
        stats = await resolve_project(
            db, project_id=project_id, changed_workspaces={repo_b_id}
        )

    assert stats.static_resolved == 1
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed is not None
        assert refreshed.status == "resolved"
        assert refreshed.dst_workspace_id == repo_b_id
        assert refreshed.dst_node_id == target_id
