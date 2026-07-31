"""Project bootstrap and metadata invalidation regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.core.db as db_module
from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services.code_graph.cross_repo import (
    METHOD_STATIC_FQN,
    invalidate_workspace_resolutions,
)
from app.services.code_graph_service import (
    reindex_workspace,
    requires_project_graph_bootstrap,
)
from app.services.coding_project_service import create_project, get_project_workspaces
from app.services.coding_workspace_service import upsert_coding_workspace


@pytest.mark.asyncio
async def test_graph_built_before_project_membership_requires_bootstrap(
    setup_db, tmp_path: Path
) -> None:
    (tmp_path / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")

    async with db_module.async_session_factory() as db:
        workspace = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        await reindex_workspace(db, workspace_id=workspace.id, root_path=str(tmp_path))
        await db.commit()

        project = await create_project(
            db, name="Bootstrap", workspace_paths=[str(tmp_path)]
        )
        await db.commit()

        assert await requires_project_graph_bootstrap(
            db, project_id=project.id, workspace_id=workspace.id
        )

        await reindex_workspace(db, workspace_id=workspace.id, root_path=str(tmp_path))
        await db.commit()

        assert not await requires_project_graph_bootstrap(
            db, project_id=project.id, workspace_id=workspace.id
        )


@pytest.mark.asyncio
async def test_metadata_invalidation_preserves_rejected_links(
    setup_db, tmp_path: Path
) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Metadata", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        workspaces = await get_project_workspaces(db, project.id)
        workspace_a = workspaces[0][1]
        workspace_b = workspaces[1][1]
        source = CodeNode(
            workspace_id=workspace_a.id,
            kind="class",
            name="Source",
            qualified_name="Source",
            file_path="Source.java",
            language="java",
            line_start=1,
            line_end=1,
        )
        target = CodeNode(
            workspace_id=workspace_b.id,
            kind="class",
            name="Target",
            qualified_name="Target",
            file_path="Target.java",
            language="java",
            line_start=1,
            line_end=1,
        )
        db.add_all([source, target])
        await db.flush()
        resolved = CrossRepoEdge(
            project_id=project.id,
            src_workspace_id=workspace_a.id,
            src_node_id=source.id,
            src_file_path="Source.java",
            raw_reference="Target",
            kind="imports",
            status="resolved",
            method=METHOD_STATIC_FQN,
            confidence=1.0,
            dst_workspace_id=workspace_b.id,
            dst_node_id=target.id,
            dst_qualified_name="Target",
        )
        rejected = CrossRepoEdge(
            project_id=project.id,
            src_workspace_id=workspace_a.id,
            src_node_id=source.id,
            src_file_path="Source.java",
            raw_reference="RejectedTarget",
            kind="imports",
            status="rejected",
            method=METHOD_STATIC_FQN,
            dst_workspace_id=workspace_b.id,
            dst_node_id=target.id,
            dst_qualified_name="Target",
        )
        db.add_all([resolved, rejected])
        await db.commit()

        count = await invalidate_workspace_resolutions(db, workspace_id=workspace_b.id)
        await db.commit()
        await db.refresh(resolved)
        await db.refresh(rejected)

        assert count == 1
        assert resolved.status == "unresolved"
        assert resolved.method is None
        assert resolved.dst_workspace_id is None
        assert resolved.dst_node_id is None
        assert rejected.status == "rejected"
        assert rejected.method == METHOD_STATIC_FQN
        assert rejected.dst_node_id == target.id
