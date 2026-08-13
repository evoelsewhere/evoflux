from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest
from sqlmodel import col, select

from app.agent.artifacts import session_artifact_dir
from app.core.config import settings
from app.core.paths import workspace_dir
from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
    CodingWorkspace,
    DreamLog,
    SessionMessage,
)
from app.models.workflow import WorkflowExecution, WorkflowNodeRun
from app.scheduler.models import ScheduledTask
from app.services import coding_purge_service as purge
from app.services.code_index.paths import paths_for_repository
from app.services.coding_project_service import create_project
from app.services.snapshot_service import snapshot_dir


def _redirect_storage(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(root / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(root / "state"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(root / "cache"))
    monkeypatch.setattr(purge, "SESSION_LOG_DIR", root / "state" / "logs" / "sessions")


@pytest.mark.asyncio
async def test_purge_workspace_removes_session_graph_and_generated_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    lead_id = uuid.uuid7()
    child_id = uuid.uuid7()
    side_id = uuid.uuid7()
    execution_id = uuid.uuid7()

    async with db_module.async_session_factory() as db:
        async with db.begin():
            db.add(CodingWorkspace(path=str(repository), kind="repo"))
            db.add(
                ChatSession(
                    id=lead_id, mode="coding", workspace=str(repository), title="lead"
                )
            )
            db.add(ChatSession(id=child_id, parent_session_id=lead_id))
            db.add(
                ChatSession(
                    id=side_id,
                    mode="coding",
                    workspace=str(repository),
                    session_type="side_chat",
                    source_session_id=lead_id,
                    source_session_ref=lead_id,
                )
            )
            db.add(SessionMessage(session_id=lead_id, role="user", content="gone"))
            db.add(
                DreamLog(
                    session_id=lead_id,
                    processed_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                WorkflowExecution(
                    id=execution_id,
                    definition_name="test",
                    definition_hash="b" * 64,
                    session_id=lead_id,
                )
            )
            db.add(
                WorkflowNodeRun(
                    execution_id=execution_id,
                    node_id="node",
                    status="succeeded",
                )
            )

    generated_paths = (
        workspace_dir(str(lead_id)),
        session_artifact_dir(str(lead_id)),
        snapshot_dir(str(lead_id)),
        purge.SESSION_LOG_DIR / str(lead_id),
    )
    for path in generated_paths:
        path.mkdir(parents=True, exist_ok=True)
        (path / "owned.txt").write_text("delete", encoding="utf-8")
    index_dir = paths_for_repository(repository).directory
    index_dir.mkdir(parents=True)
    (index_dir / "graph.db").write_text("delete", encoding="utf-8")

    async with db_module.async_session_factory() as db:
        result = await purge.purge_workspace(db, str(repository))

    assert result.session_count == 3
    assert repository.is_dir()
    assert not index_dir.exists()
    assert all(not path.exists() for path in generated_paths)
    async with db_module.async_session_factory() as db:
        assert (await db.exec(select(ChatSession))).all() == []
        assert (await db.exec(select(SessionMessage))).all() == []
        assert (await db.exec(select(DreamLog))).all() == []
        assert (await db.exec(select(WorkflowExecution))).all() == []
        assert (await db.exec(select(WorkflowNodeRun))).all() == []
        assert (await db.exec(select(CodingWorkspace))).all() == []


@pytest.mark.asyncio
async def test_purge_project_hard_deletes_project_sessions_and_tasks_but_keeps_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    repository = tmp_path / "repository"
    repository.mkdir()
    session_id = uuid.uuid7()
    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Disposable", workspace_paths=[str(repository)]
        )
        project_id = project.id
        db.add(
            ChatSession(
                id=session_id,
                mode="coding",
                workspace=str(repository),
                project_id=project_id,
            )
        )
        db.add(
            ScheduledTask(
                name=f"project-{project_id}",
                mode="coding",
                project_id=project_id,
                schedule_type="every",
                every_seconds=3600,
                prompt="test",
                session_id=str(session_id),
            )
        )
        await db.commit()

    index_dir = paths_for_repository(repository).directory
    index_dir.mkdir(parents=True)
    (index_dir / "graph.db").write_text("delete", encoding="utf-8")
    async with db_module.async_session_factory() as db:
        result = await purge.purge_project(db, project_id)

    assert result is not None
    assert result.session_count == 1
    assert repository.is_dir()
    assert not index_dir.exists()
    async with db_module.async_session_factory() as db:
        assert await db.get(CodingProject, project_id) is None
        assert await db.get(ChatSession, session_id) is None
        assert (
            await db.exec(
                select(CodingProjectWorkspace).where(
                    col(CodingProjectWorkspace.project_id) == project_id
                )
            )
        ).all() == []
        assert (await db.exec(select(ScheduledTask))).all() == []
        workspace = (
            await db.exec(
                select(CodingWorkspace).where(CodingWorkspace.path == str(repository))
            )
        ).one()
        assert workspace.path == str(repository)


@pytest.mark.asyncio
async def test_detaching_project_repo_resets_project_sessions_and_keeps_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    session_id = uuid.uuid7()
    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Keep", workspace_paths=[str(first), str(second)]
        )
        project_id = project.id
        pairs = list(
            (
                await db.exec(
                    select(CodingProjectWorkspace, CodingWorkspace)
                    .join(
                        CodingWorkspace,
                        col(CodingWorkspace.id)
                        == col(CodingProjectWorkspace.workspace_id),
                    )
                    .where(CodingProjectWorkspace.project_id == project_id)
                )
            ).all()
        )
        removed_workspace = next(ws for _link, ws in pairs if ws.path == str(first))
        db.add(
            ChatSession(
                id=session_id,
                mode="coding",
                workspace=str(first),
                project_id=project_id,
            )
        )
        await db.commit()

    async with db_module.async_session_factory() as db:
        result = await purge.purge_project_workspace(
            db, project_id, removed_workspace.id
        )

    assert result is not None
    assert await _project_exists(project_id)
    assert first.is_dir() and second.is_dir()
    async with db_module.async_session_factory() as db:
        assert await db.get(ChatSession, session_id) is None
        links = (
            await db.exec(
                select(CodingProjectWorkspace).where(
                    CodingProjectWorkspace.project_id == project_id
                )
            )
        ).all()
        assert len(links) == 1


async def _project_exists(project_id: uuid.UUID) -> bool:
    import app.core.db as db_module

    async with db_module.async_session_factory() as db:
        return await db.get(CodingProject, project_id) is not None
