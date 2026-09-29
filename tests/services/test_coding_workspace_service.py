from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import (
    CodingProject,
    CodingProjectWorkspace,
)
from app.services.coding_workspace_service import (
    upsert_coding_workspace,
)
from app.services.coding_project_service import (
    get_visible_project_ids_for_workspace_path,
    split_project_paths_for_workspace,
)


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


async def _add_project_workspace(db: AsyncSession, project_id, workspace_path: str):
    ws = await upsert_coding_workspace(db, path=workspace_path, kind="repo")
    db.add(CodingProjectWorkspace(project_id=project_id, workspace_id=ws.id))
    await db.flush()
    return ws


@pytest.mark.asyncio
async def test_reopening_workspace_restores_hidden_and_deleted_registry_row(
    db, tmp_path
):
    workspace = await upsert_coding_workspace(
        db,
        path=str(tmp_path),
        kind="repo",
        hidden=True,
        deleted_at=datetime.now(timezone.utc),
    )
    await db.commit()

    reopened = await upsert_coding_workspace(db, path=str(tmp_path), kind="repo")
    await db.commit()

    assert reopened.id == workspace.id
    assert reopened.hidden is False
    assert reopened.deleted_at is None


@pytest.mark.asyncio
async def test_repo_in_no_project_has_no_owner(db, tmp_path):
    await upsert_coding_workspace(db, path=str(tmp_path), kind="repo")
    await db.commit()

    assert await get_visible_project_ids_for_workspace_path(db, str(tmp_path)) == []


@pytest.mark.asyncio
async def test_worktree_listed_as_a_project_repo_is_owned_by_that_project(db, tmp_path):
    """A worktree folder opened as its own project must be chat-able there."""
    source_path = str(tmp_path / "source-repo")
    worktree_path = str(tmp_path / "worktree")
    source_owner = CodingProject(name="Source owner")
    worktree_owner = CodingProject(name="Worktree as project")
    db.add(source_owner)
    db.add(worktree_owner)
    await db.flush()
    source = await _add_project_workspace(db, source_owner.id, source_path)
    worktree = await upsert_coding_workspace(
        db,
        path=worktree_path,
        kind="worktree",
        source_path=source.path,
        managed=True,
    )
    db.add(
        CodingProjectWorkspace(project_id=worktree_owner.id, workspace_id=worktree.id)
    )
    await db.commit()

    assert set(await get_visible_project_ids_for_workspace_path(db, worktree_path)) == {
        source_owner.id,
        worktree_owner.id,
    }


@pytest.mark.asyncio
async def test_worktree_inherits_source_project_ownership(db, tmp_path):
    source_path = str(tmp_path / "source-repo")
    worktree_path = str(tmp_path / "worktree")
    project = CodingProject(name="Owner")
    db.add(project)
    await db.flush()
    source = await _add_project_workspace(db, project.id, source_path)
    await upsert_coding_workspace(
        db,
        path=worktree_path,
        kind="worktree",
        source_path=source.path,
        managed=True,
    )
    await db.commit()

    assert await get_visible_project_ids_for_workspace_path(db, worktree_path) == [
        project.id
    ]


def test_project_session_on_a_repo_gets_the_other_repos_as_writable_extras(tmp_path):
    api = str((tmp_path / "api").resolve())
    web = str((tmp_path / "web").resolve())

    assert split_project_paths_for_workspace([api, web], api) == ([web], [])


def test_worktree_session_may_only_read_its_source_checkout(tmp_path):
    api = str((tmp_path / "api").resolve())
    web = str((tmp_path / "web").resolve())
    worktree = str((tmp_path / "web" / ".evoflux" / "worktrees" / "task").resolve())

    assert split_project_paths_for_workspace([api, web], worktree) == ([api], [web])
