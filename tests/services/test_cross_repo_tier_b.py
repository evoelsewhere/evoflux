"""Tests for cross-repo resolution Tier B (FTS5 lexical narrowing).

Tier A (static FQN/manifest matching) and its own tests live in
``tests/api/routes/test_project_cross_repo.py``. These tests exercise
``resolve_project_tier_b`` directly against manually-seeded ``CodeNode``/
``CrossRepoEdge`` rows and a hand-populated FTS index, so each branch
(exact match, ambiguous, zero candidates) is isolated from the parser
pipeline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.core.db as db_module
from app.services.code_graph import fts_store
from app.services.code_graph.cross_repo_llm import resolve_project_tier_b
from app.services.coding_project_service import create_project
from app.services.coding_workspace_service import upsert_coding_workspace


async def _setup_project(tmp_path: Path):
    """Create a 2-repo CodingProject; return (project_id, repo_a_id, repo_b_id)."""
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Tier B Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        repo_a_ws = await upsert_coding_workspace(db, path=str(repo_a))
        repo_b_ws = await upsert_coding_workspace(db, path=str(repo_b))
        await db.commit()
        return project.id, repo_a_ws.id, repo_b_ws.id


async def _seed_node(db, *, workspace_id, name, qualified_name, kind="class"):
    from app.models.code_graph import CodeNode

    node = CodeNode(
        workspace_id=workspace_id,
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        file_path=f"{name}.java",
        language="java",
        line_start=1,
        line_end=1,
    )
    db.add(node)
    await db.flush()
    await db.refresh(node)
    return node


async def _seed_unresolved_edge(db, *, project_id, src_workspace_id, raw_reference, dst_name_hint=None):
    from app.models.code_graph import CrossRepoEdge

    edge = CrossRepoEdge(
        project_id=project_id,
        src_workspace_id=src_workspace_id,
        src_file_path="Main.java",
        raw_reference=raw_reference,
        dst_name_hint=dst_name_hint,
        kind="imports",
    )
    db.add(edge)
    await db.flush()
    await db.refresh(edge)
    return edge


def _index_fts(workspace_id, rows: list[tuple[str, str, str]]) -> None:
    db_path = db_module.current_sqlite_path()
    assert db_path is not None
    fts_store.rebuild_workspace_fts(db_path, str(workspace_id), rows)


@pytest.mark.asyncio
async def test_tier_b_auto_resolves_single_exact_match(setup_db, tmp_path: Path):
    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        target = await _seed_node(
            db,
            workspace_id=repo_b_id,
            name="AuthClient",
            qualified_name="com.example.auth.AuthClient",
        )
        edge = await _seed_unresolved_edge(
            db,
            project_id=project_id,
            src_workspace_id=repo_a_id,
            raw_reference="com.example.auth.AuthClient",
            dst_name_hint="AuthClient",
        )
        await db.commit()
        target_id = target.id
        edge_id = edge.id

    _index_fts(repo_b_id, [(str(target_id), "AuthClient", "com.example.auth.AuthClient")])

    async with db_module.async_session_factory() as db:
        stats = await resolve_project_tier_b(db, project_id=project_id)

    assert stats.lexical_resolved == 1

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge

        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed.status == "resolved"
        assert refreshed.method == "lexical"
        assert refreshed.dst_node_id == target_id
        assert refreshed.dst_workspace_id == repo_b_id
        assert refreshed.dst_qualified_name == "com.example.auth.AuthClient"


@pytest.mark.asyncio
async def test_tier_b_leaves_unresolved_when_no_candidates(setup_db, tmp_path: Path):
    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        edge = await _seed_unresolved_edge(
            db,
            project_id=project_id,
            src_workspace_id=repo_a_id,
            raw_reference="com.example.auth.Nonexistent",
            dst_name_hint="Nonexistent",
        )
        await db.commit()
        edge_id = edge.id

    # repo_b has no FTS entries at all — nothing for Tier B to find.
    async with db_module.async_session_factory() as db:
        stats = await resolve_project_tier_b(db, project_id=project_id)

    assert stats.lexical_resolved == 0

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge

        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed.status == "unresolved"
        assert refreshed.method is None


@pytest.mark.asyncio
async def test_tier_b_does_not_guess_when_ambiguous(setup_db, tmp_path: Path):
    """Two equally-named candidates must not auto-resolve — a wrong guess is
    worse than staying unresolved."""
    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        node1 = await _seed_node(
            db,
            workspace_id=repo_b_id,
            name="Logger",
            qualified_name="com.example.a.Logger",
        )
        node2 = await _seed_node(
            db,
            workspace_id=repo_b_id,
            name="Logger",
            qualified_name="com.example.b.Logger",
        )
        edge = await _seed_unresolved_edge(
            db,
            project_id=project_id,
            src_workspace_id=repo_a_id,
            raw_reference="com.example.c.Logger",
            dst_name_hint="Logger",
        )
        await db.commit()
        edge_id = edge.id
        n1_id, n2_id = node1.id, node2.id

    _index_fts(
        repo_b_id,
        [
            (str(n1_id), "Logger", "com.example.a.Logger"),
            (str(n2_id), "Logger", "com.example.b.Logger"),
        ],
    )

    async with db_module.async_session_factory() as db:
        stats = await resolve_project_tier_b(db, project_id=project_id)

    assert stats.lexical_resolved == 0

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge

        refreshed = await db.get(CrossRepoEdge, edge_id)
        assert refreshed.status == "unresolved"


@pytest.mark.asyncio
async def test_tier_b_row_cap(setup_db, tmp_path: Path, monkeypatch):
    from app.core import runtime_settings as rs_module
    from app.services.code_graph import cross_repo_llm

    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    async with db_module.async_session_factory() as db:
        for i in range(5):
            await _seed_unresolved_edge(
                db,
                project_id=project_id,
                src_workspace_id=repo_a_id,
                raw_reference=f"com.example.missing.Thing{i}",
            )
        await db.commit()

    original_load = rs_module.load_runtime_settings

    def _capped_settings():
        settings = original_load()
        settings.cross_repo.max_rows_per_run = 2
        return settings

    monkeypatch.setattr(cross_repo_llm, "load_runtime_settings", _capped_settings)

    async with db_module.async_session_factory() as db:
        stats = await resolve_project_tier_b(db, project_id=project_id)

    assert stats.capped == 3


@pytest.mark.asyncio
async def test_tier_b_rotates_through_capped_rows_across_runs(
    setup_db, tmp_path: Path, monkeypatch
):
    """With more unresolved rows than max_rows_per_run, repeated calls must
    eventually reach every row instead of always retrying the same leading
    slice — a fixed ``[:max_rows_per_run]`` window would let rows past the
    cap sit unresolved forever no matter how many times resolve runs."""
    from app.core import runtime_settings as rs_module
    from app.models.code_graph import CrossRepoEdge
    from app.services.code_graph import cross_repo_llm

    project_id, repo_a_id, repo_b_id = await _setup_project(tmp_path)

    edge_ids = []
    fts_rows = []
    async with db_module.async_session_factory() as db:
        for i in range(5):
            target = await _seed_node(
                db,
                workspace_id=repo_b_id,
                name=f"Target{i}",
                qualified_name=f"com.example.gen.Target{i}",
            )
            edge = await _seed_unresolved_edge(
                db,
                project_id=project_id,
                src_workspace_id=repo_a_id,
                raw_reference=f"com.example.gen.Target{i}",
                dst_name_hint=f"Target{i}",
            )
            edge_ids.append(edge.id)
            fts_rows.append((str(target.id), f"Target{i}", f"com.example.gen.Target{i}"))
        await db.commit()
    _index_fts(repo_b_id, fts_rows)

    original_load = rs_module.load_runtime_settings

    def _capped_settings():
        settings = original_load()
        settings.cross_repo.max_rows_per_run = 2
        return settings

    monkeypatch.setattr(cross_repo_llm, "load_runtime_settings", _capped_settings)

    total_resolved = 0
    for _ in range(3):  # ceil(5 / 2) — enough rounds to sweep every row once
        async with db_module.async_session_factory() as db:
            stats = await resolve_project_tier_b(db, project_id=project_id)
            total_resolved += stats.lexical_resolved

    assert total_resolved == 5
    async with db_module.async_session_factory() as db:
        for edge_id in edge_ids:
            refreshed = await db.get(CrossRepoEdge, edge_id)
            assert refreshed.status == "resolved", (
                f"edge {edge_id} never got a Tier B attempt across all rounds"
            )
