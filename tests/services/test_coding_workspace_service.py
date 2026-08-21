from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
)
from app.services.coding_workspace_service import (
    list_workspace_paths_with_sessions,
    upsert_coding_workspace,
)
from app.services.coding_project_service import (
    get_visible_project_ids_for_workspace_path,
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
async def test_no_sessions_returns_empty(db, tmp_path):
    await upsert_coding_workspace(db, path=str(tmp_path), kind="repo")
    await db.commit()

    assert await list_workspace_paths_with_sessions(db) == []


@pytest.mark.asyncio
async def test_standalone_session_workspace_included(db, tmp_path):
    ws_path = str(tmp_path)
    await upsert_coding_workspace(db, path=ws_path, kind="repo")
    db.add(ChatSession(mode="coding", workspace=ws_path))
    await db.commit()

    paths = await list_workspace_paths_with_sessions(db)
    assert paths == [ws_path]


@pytest.mark.asyncio
async def test_hidden_workspace_excluded_even_with_session(db, tmp_path):
    ws_path = str(tmp_path)
    await upsert_coding_workspace(db, path=ws_path, kind="repo", hidden=True)
    db.add(ChatSession(mode="coding", workspace=ws_path))
    await db.commit()

    assert await list_workspace_paths_with_sessions(db) == []


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
async def test_project_without_session_excludes_its_workspaces(db, tmp_path):
    """A repo merely added to a project (never opened) shouldn't be watched."""
    project = CodingProject(name="Unused project")
    db.add(project)
    await db.flush()
    await _add_project_workspace(db, project.id, str(tmp_path / "repo-a"))
    await db.commit()

    assert await list_workspace_paths_with_sessions(db) == []


@pytest.mark.asyncio
async def test_project_with_session_includes_every_repo(db, tmp_path):
    """A project session can touch any repo in the project, not just the
    one it was resolved with — every project workspace should be watched."""
    project = CodingProject(name="Multi-repo project")
    db.add(project)
    await db.flush()
    repo_a = str(tmp_path / "repo-a")
    repo_b = str(tmp_path / "repo-b")
    await _add_project_workspace(db, project.id, repo_a)
    await _add_project_workspace(db, project.id, repo_b)
    db.add(ChatSession(mode="coding", project_id=project.id, workspace=repo_a))
    await db.commit()

    paths = set(await list_workspace_paths_with_sessions(db))
    assert paths == {repo_a, repo_b}


@pytest.mark.asyncio
async def test_worktree_session_also_watches_source_repo(db, tmp_path):
    source_path = str(tmp_path / "source-repo")
    worktree_path = str(tmp_path / "worktree")
    await upsert_coding_workspace(db, path=source_path, kind="repo")
    await upsert_coding_workspace(
        db,
        path=worktree_path,
        kind="worktree",
        source_path=source_path,
        managed=True,
    )
    db.add(ChatSession(mode="coding", workspace=worktree_path))
    await db.commit()

    paths = set(await list_workspace_paths_with_sessions(db))
    assert paths == {source_path, worktree_path}


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
