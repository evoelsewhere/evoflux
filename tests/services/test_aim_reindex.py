from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.aim import AimRun, AimUnit
from app.models.chat import CodingProject
from app.services.aim.kb_store import write_unit
from app.services.aim.reindex import reindex_project


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
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def project(db: AsyncSession):
    proj = CodingProject(name="test-migration", kind="aim")
    db.add(proj)
    await db.flush()
    return proj


@pytest.mark.asyncio
async def test_reindex_creates_units_from_kb(db: AsyncSession, project, tmp_path: Path):
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program", phase="inventory")
    write_unit(tmp_path, "core-batch", "TAXCALC", kind="program", phase="understood")

    result = await reindex_project(db, project.id, tmp_path)
    assert result.created == 2
    assert result.updated == 0

    rows = (
        await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
    ).all()
    assert {row.name for row in rows} == {"PAYROLL01", "TAXCALC"}


@pytest.mark.asyncio
async def test_reindex_is_idempotent_when_unchanged(
    db: AsyncSession, project, tmp_path: Path
):
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program", phase="inventory")
    await reindex_project(db, project.id, tmp_path)

    result = await reindex_project(db, project.id, tmp_path)
    assert result.created == 0
    assert result.updated == 0
    assert result.unchanged == 1


@pytest.mark.asyncio
async def test_reindex_updates_changed_phase(db: AsyncSession, project, tmp_path: Path):
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program", phase="inventory")
    await reindex_project(db, project.id, tmp_path)

    write_unit(tmp_path, "core-batch", "PAYROLL01", phase="understood")
    result = await reindex_project(db, project.id, tmp_path)
    assert result.updated == 1

    rows = (
        await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
    ).all()
    assert rows[0].phase == "understood"


@pytest.mark.asyncio
async def test_reindex_preserves_row_id_and_runs_across_reindex(
    db: AsyncSession, project, tmp_path: Path
):
    """Reindex must upsert, not delete+recreate — otherwise a unit's
    aim_runs (FK cascade) would be silently destroyed on every reindex."""
    write_unit(tmp_path, "core-batch", "PAYROLL01", kind="program", phase="inventory")
    await reindex_project(db, project.id, tmp_path)

    unit = (
        await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
    ).one()
    run = AimRun(unit_id=unit.id, kind="compare", verdict="pass")
    db.add(run)
    await db.flush()
    unit_id_before = unit.id

    write_unit(tmp_path, "core-batch", "PAYROLL01", phase="understood")
    await reindex_project(db, project.id, tmp_path)

    unit_after = (
        await db.exec(select(AimUnit).where(AimUnit.project_id == project.id))
    ).one()
    assert unit_after.id == unit_id_before

    runs = (await db.exec(select(AimRun).where(AimRun.unit_id == unit_id_before))).all()
    assert len(runs) == 1
