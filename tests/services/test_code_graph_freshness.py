"""Freshness and input-boundary regression coverage for graph navigation."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

import app.models.chat  # noqa: F401 -- register SQLModel tables
import app.models.code_graph  # noqa: F401 -- register SQLModel tables


async def _index(root: Path):  # noqa: ANN202
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    async with async_session_factory() as db:
        workspace = await upsert_coding_workspace(db, path=str(root))
        await db.commit()
        await reindex_workspace(db, workspace_id=workspace.id, root_path=str(root))
        await db.commit()
        return workspace.id


@pytest.mark.asyncio
async def test_source_filename_is_rejected_before_graph_navigation(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        with pytest.raises(ValueError, match="source filename/path"):
            await navigate_code_graph(
                db,
                root_path=str(tmp_path),
                workspace_id=workspace_id,
                symbol="app/services/billing.py",
            )


@pytest.mark.asyncio
async def test_balanced_navigation_reindexes_clean_committed_source(
    setup_db, tmp_path: Path
) -> None:
    """A clean worktree must not make an older graph snapshot look fresh."""
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "service.py"
    source.write_text("def old_handler():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Code Graph Test",
            "-c",
            "user.email=code-graph@example.test",
            "commit",
            "-qm",
            "old source",
        ],
        cwd=tmp_path,
        check=True,
    )
    workspace_id = await _index(tmp_path)

    source.write_text("def committed_handler():\n    return 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "service.py"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Code Graph Test",
            "-c",
            "user.email=code-graph@example.test",
            "commit",
            "-qm",
            "committed source",
        ],
        cwd=tmp_path,
        check=True,
    )
    future = time.time() + 2
    os.utime(source, (future, future))
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )

    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="committed_handler",
            freshness_policy="balanced",
        )

    assert result.freshness == "fresh"
    assert result.dirty_files == 0
    assert [item.node.name for item in result.matches] == ["committed_handler"]
    assert "return 2" in (result.matches[0].source or "")
