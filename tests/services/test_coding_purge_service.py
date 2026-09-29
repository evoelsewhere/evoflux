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
from app.scheduler.models import ScheduledTask
from app.services import coding_purge_service as purge
from app.services.coding_project_service import create_project
from app.services.snapshot_service import snapshot_dir


def _redirect_storage(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(root / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_STATE_DIR", str(root / "state"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(root / "cache"))
    monkeypatch.setattr(purge, "SESSION_LOG_DIR", root / "state" / "logs" / "sessions")


def _every_hour_task(name: str, mode: str, **fields) -> ScheduledTask:
    return ScheduledTask(
        name=name,
        mode=mode,
        schedule_type="every",
        every_seconds=3600,
        prompt="test",
        **fields,
    )


@pytest.mark.asyncio
async def test_purge_standalone_coding_sessions_removes_only_projectless_coding_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    standalone = tmp_path / "standalone"
    in_project = tmp_path / "in-project"
    standalone.mkdir()
    in_project.mkdir()
    lead_id = uuid.uuid7()
    child_id = uuid.uuid7()
    side_id = uuid.uuid7()
    project_lead_id = uuid.uuid7()
    project_member_id = uuid.uuid7()
    project_side_id = uuid.uuid7()
    work_id = uuid.uuid7()

    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Kept", workspace_paths=[str(in_project)]
        )
        project_id = project.id
        db.add(CodingWorkspace(path=str(standalone), kind="repo"))
        # A standalone Coding chat with a sub-agent session and a side chat.
        db.add(
            ChatSession(
                id=lead_id, mode="coding", workspace=str(standalone), title="lead"
            )
        )
        db.add(ChatSession(id=child_id, parent_session_id=lead_id))
        db.add(
            ChatSession(
                id=side_id,
                mode="coding",
                workspace=str(standalone),
                session_type="side_chat",
                source_session_id=lead_id,
                source_session_ref=lead_id,
            )
        )
        db.add(SessionMessage(session_id=lead_id, role="user", content="gone"))
        db.add(DreamLog(session_id=lead_id, processed_at=datetime.now(timezone.utc)))
        # A project chat whose member and side chat carry no project_id of
        # their own; none of it is standalone.
        db.add(
            ChatSession(
                id=project_lead_id,
                mode="coding",
                workspace=str(in_project),
                project_id=project_id,
            )
        )
        db.add(
            ChatSession(
                id=project_member_id,
                mode="coding",
                workspace=str(in_project),
                parent_session_id=project_lead_id,
            )
        )
        db.add(
            ChatSession(
                id=project_side_id,
                mode="coding",
                workspace=str(in_project),
                session_type="side_chat",
                source_session_id=project_lead_id,
                source_session_ref=project_lead_id,
            )
        )
        db.add(SessionMessage(session_id=project_lead_id, role="user", content="kept"))
        db.add(ChatSession(id=work_id, mode="work"))
        db.add(_every_hour_task("standalone", "coding", workspace=str(standalone)))
        db.add(
            _every_hour_task(
                "project", "coding", workspace=str(in_project), project_id=project_id
            )
        )
        db.add(_every_hour_task("work", "work", session_id=str(work_id)))
        await db.commit()

    generated_paths = (
        workspace_dir(str(lead_id)),
        session_artifact_dir(str(lead_id)),
        snapshot_dir(str(lead_id)),
        purge.SESSION_LOG_DIR / str(lead_id),
    )
    kept_path = workspace_dir(str(project_lead_id))
    for path in (*generated_paths, kept_path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "owned.txt").write_text("data", encoding="utf-8")

    async with db_module.async_session_factory() as db:
        result = await purge.purge_standalone_coding_sessions(db)

    assert result.session_count == 3
    assert result.repository_paths == (str(standalone),)
    assert standalone.is_dir() and in_project.is_dir()
    assert all(not path.exists() for path in generated_paths)
    assert (kept_path / "owned.txt").is_file()
    async with db_module.async_session_factory() as db:
        remaining = {row.id for row in (await db.exec(select(ChatSession))).all()}
        assert remaining == {
            project_lead_id,
            project_member_id,
            project_side_id,
            work_id,
        }
        messages = (await db.exec(select(SessionMessage))).all()
        assert [m.session_id for m in messages] == [project_lead_id]
        assert (await db.exec(select(DreamLog))).all() == []
        tasks = (await db.exec(select(ScheduledTask))).all()
        assert sorted(task.name for task in tasks) == ["project", "work"]
        # The repository registry is left alone so the folder can still be
        # added to a project.
        registered = (await db.exec(select(CodingWorkspace.path))).all()
        assert str(standalone) in registered

    async with db_module.async_session_factory() as db:
        again = await purge.purge_standalone_coding_sessions(db)
    assert again == purge.PurgeResult(0, ())


@pytest.mark.asyncio
async def test_purge_files_projectless_chats_under_the_repos_sole_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo that joined a project later keeps its older chats, in the project."""
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    repository = tmp_path / "repository"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    worktree.mkdir()
    lead_id = uuid.uuid7()
    side_id = uuid.uuid7()
    worktree_lead_id = uuid.uuid7()
    async with db_module.async_session_factory() as db:
        project = await create_project(
            db, name="Later", workspace_paths=[str(repository)]
        )
        project_id = project.id
        db.add(
            CodingWorkspace(
                path=str(worktree),
                kind="worktree",
                source_path=str(repository),
                managed=True,
            )
        )
        db.add(ChatSession(id=lead_id, mode="coding", workspace=str(repository)))
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
        db.add(ChatSession(id=worktree_lead_id, mode="coding", workspace=str(worktree)))
        db.add(_every_hour_task("older", "coding", workspace=str(repository)))
        await db.commit()

    async with db_module.async_session_factory() as db:
        result = await purge.purge_standalone_coding_sessions(db)

    assert result == purge.PurgeResult(0, ())
    async with db_module.async_session_factory() as db:
        rows = {row.id: row for row in (await db.exec(select(ChatSession))).all()}
        assert set(rows) == {lead_id, side_id, worktree_lead_id}
        assert {row.project_id for row in rows.values()} == {project_id}
        task = (await db.exec(select(ScheduledTask))).one()
        assert task.project_id == project_id


@pytest.mark.asyncio
async def test_purge_leaves_rows_created_after_startup_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.db as db_module

    _redirect_storage(monkeypatch, tmp_path)
    started_at = datetime.now(timezone.utc)
    session_id = uuid.uuid7()
    async with db_module.async_session_factory() as db:
        # A member row a live request wrote before linking it to its lead.
        db.add(ChatSession(id=session_id, mode="coding", workspace=str(tmp_path)))
        await db.commit()

    async with db_module.async_session_factory() as db:
        result = await purge.purge_standalone_coding_sessions(
            db, created_before=started_at
        )

    assert result == purge.PurgeResult(0, ())
    async with db_module.async_session_factory() as db:
        assert await db.get(ChatSession, session_id) is not None


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

    async with db_module.async_session_factory() as db:
        result = await purge.purge_project(db, project_id)

    assert result is not None
    assert result.session_count == 1
    assert repository.is_dir()
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
