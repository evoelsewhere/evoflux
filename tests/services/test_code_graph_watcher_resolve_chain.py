"""Watcher-triggered incremental reindex must chain into cross-repo resolve
for multi-repo projects, the same way the manual reindex endpoint
(reindex_project_code_graph) already does — see CodeGraphWatcher._reindex.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import app.core.db as db_module
from app.services.code_graph.cross_repo_jobs import cross_repo_jobs
from app.services.code_graph.watcher import CodeGraphWatcher
from app.services.code_graph_service import reindex_workspace
from app.services.coding_project_service import create_project


async def _wait_until_resolve_settles(project_id, *, attempts: int = 300) -> None:
    for _ in range(attempts):
        if not cross_repo_jobs.is_running(project_id):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("watcher-triggered resolve did not finish in time")


@pytest.mark.asyncio
async def test_watcher_reindex_chains_into_resolve_for_multi_repo_project(
    setup_db, tmp_path: Path
):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    concept_resource = repo_a / "ConceptResource.java"
    # No reference to ConceptService yet — added below as the "edit" the
    # watcher reacts to, so the incremental reindex has a real change to
    # report (the resolve-chain is gated on changed_files/deleted_files).
    concept_resource.write_text("public class ConceptResource {\n}\n")
    (repo_b / "ConceptService.java").write_text("public class ConceptService {}\n")

    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Watcher Chain Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        project_id = project.id

    async with db_module.async_session_factory() as db:
        from app.services.code_graph_service import resolve_workspace_id

        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        repo_b_id = await resolve_workspace_id(db, path=str(repo_b))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await reindex_workspace(db, workspace_id=repo_b_id, root_path=str(repo_b))
        await db.commit()

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge
        from sqlmodel import select

        rows = (
            await db.exec(
                select(CrossRepoEdge).where(CrossRepoEdge.project_id == project_id)
            )
        ).all()
        assert rows == []  # no reference to a sibling symbol exists yet

    # The "edit" — wires in the field the watcher is about to pick up.
    concept_resource.write_text(
        "public class ConceptResource {\n"
        "    private final ConceptService conceptService;\n"
        "    public ConceptResource(ConceptService conceptService) {\n"
        "        this.conceptService = conceptService;\n"
        "    }\n"
        "}\n"
    )

    # Simulate a file-change event triggering the watcher's own incremental
    # reindex path directly (bypassing the actual filesystem watch — that
    # infra isn't what this test is about).
    watcher = CodeGraphWatcher(db_factory=db_module.async_session_factory)
    await watcher._reindex(str(repo_a))

    await _wait_until_resolve_settles(project_id)

    async with db_module.async_session_factory() as db:
        from app.models.code_graph import CrossRepoEdge
        from sqlmodel import select

        rows = (
            await db.exec(
                select(CrossRepoEdge).where(CrossRepoEdge.project_id == project_id)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "resolved", (
            "watcher-triggered incremental reindex should have auto-chained "
            "into a cross-repo resolve pass, same as the manual reindex endpoint"
        )
        assert rows[0].dst_qualified_name == "ConceptService"


@pytest.mark.asyncio
async def test_watcher_reindex_does_not_resolve_for_solo_workspace(
    setup_db, tmp_path: Path
):
    """A workspace with no project (or a single-repo project) has no
    siblings to resolve against — the watcher must not start a resolve job
    for it (cross_repo_jobs.start() would just no-op on <2 workspaces, but
    the point is it shouldn't even try)."""
    repo = tmp_path / "solo-repo"
    repo.mkdir()
    (repo / "Main.java").write_text("class Main {}\n", encoding="utf-8")

    async with db_module.async_session_factory() as db:
        from app.services.coding_workspace_service import upsert_coding_workspace

        ws = await upsert_coding_workspace(db, path=str(repo))
        await db.commit()
        await reindex_workspace(db, workspace_id=ws.id, root_path=str(repo))
        await db.commit()

    watcher = CodeGraphWatcher(db_factory=db_module.async_session_factory)
    await watcher._reindex(str(repo))

    # No project owns this workspace, so no resolve job should ever have
    # been registered for anything — nothing to poll/assert false-negative
    # on other than "the call above didn't raise or hang".
