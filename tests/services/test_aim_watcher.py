from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.aim import AimUnit
from app.models.chat import CodingProject
from app.services.aim.kb_store import write_unit
from app.services.aim.watcher import AimIndexWatcher


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_aim_watcher_filters_projection_paths():
    assert AimIndexWatcher.is_relevant("modules/core/PAY.md")
    assert AimIndexWatcher.is_relevant("runs/core/PAY/id/meta.yaml")
    assert AimIndexWatcher.is_relevant("state/links/id.yaml")
    assert AimIndexWatcher.is_relevant("aim.yaml")
    assert not AimIndexWatcher.is_relevant(".aim-actuals/core/PAY/out.txt")
    assert not AimIndexWatcher.is_relevant("notes/scratch.md")


@pytest.mark.asyncio
async def test_aim_watcher_rebuilds_projection(db_factory, tmp_path: Path):
    async with db_factory() as db:
        project = CodingProject(name="watched", kind="aim")
        db.add(project)
        await db.commit()
        await db.refresh(project)
    write_unit(tmp_path, "core", "PAY", kind="program", phase="inventory")
    watcher = AimIndexWatcher(db_factory=db_factory, debounce_ms=1)

    await watcher.reindex_now(project.id, str(tmp_path))

    async with db_factory() as db:
        rows = (await db.exec(select(AimUnit))).all()
    assert [row.name for row in rows] == ["PAY"]
