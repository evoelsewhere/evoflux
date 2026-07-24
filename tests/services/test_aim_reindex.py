from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.aim import AimLink, AimRun, AimUnit
from app.models.chat import CodingProject
from app.services.aim import kb_store
from app.services.aim.kb_store import write_transition_event, write_unit
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
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
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


@pytest.mark.asyncio
async def test_schema_v2_reindex_rejects_unverified_advanced_phase(
    db: AsyncSession, project, tmp_path: Path
):
    (tmp_path / "aim.yaml").write_text(
        "state_schema: 2\n"
        "rulebook: {id: test, version: '1'}\n"
        "roles: {source: [], target: []}\n"
    )
    write_unit(tmp_path, "core", "PAY", kind="program", phase="converted")

    result = await reindex_project(db, project.id, tmp_path)

    assert result.created == 0
    assert result.invalid == 1
    assert any("transition event" in error for error in result.errors)


@pytest.mark.asyncio
async def test_schema_v2_reindex_accepts_matching_transition_event(
    db: AsyncSession, project, tmp_path: Path
):
    (tmp_path / "aim.yaml").write_text(
        "state_schema: 2\n"
        "rulebook: {id: test, version: '1'}\n"
        "roles: {source: [], target: []}\n"
    )
    event_id = write_transition_event(
        tmp_path,
        "core",
        "PAY",
        from_phase="inventory",
        to_phase="understood",
        revision=1,
        workflow_name="aim-understand",
        workflow_execution_id="00000000-0000-7000-8000-000000000001",
        session_id=None,
    )
    write_unit(
        tmp_path,
        "core",
        "PAY",
        kind="program",
        phase="understood",
        revision=1,
        last_transition_id=event_id,
        body="Documented behavior.",
    )

    result = await reindex_project(db, project.id, tmp_path)

    assert result.created == 1
    assert result.invalid == 0


@pytest.mark.asyncio
async def test_reindex_rebuilds_file_backed_runs_and_links(
    db: AsyncSession, project, tmp_path: Path
):
    from uuid import uuid7

    write_unit(tmp_path, "core", "PAY", kind="program", phase="inventory")
    run_id = uuid7()
    link_id = uuid7()
    kb_store.write_run_meta(
        tmp_path,
        "core",
        "PAY",
        run_id=run_id,
        kind="compare",
        verdict="pass",
        case_set="smoke",
        stats={"diff_count": 0},
        report_path=f"runs/core/PAY/{run_id}/report.json",
        session_id=None,
        workflow_execution_id=None,
    )
    kb_store.write_link_meta(
        tmp_path,
        link_id=link_id,
        from_ref="rule:BR-CORE-0001",
        to_ref="unit:core/PAY",
        kind="implements",
        note=None,
    )

    result = await reindex_project(db, project.id, tmp_path)
    await db.flush()

    assert result.runs_created == 1
    assert result.links_created == 1
    assert (await db.exec(select(AimRun))).one().id == run_id
    assert (await db.exec(select(AimLink))).one().id == link_id


@pytest.mark.asyncio
async def test_reindex_reports_malformed_metadata_without_aborting_valid_units(
    db: AsyncSession, project, tmp_path: Path
):
    write_unit(tmp_path, "core", "GOOD", kind="program", phase="inventory")
    malformed_unit = tmp_path / "modules" / "core" / "BROKEN.md"
    malformed_unit.write_text("---\nkind: [not valid\n---\n")
    malformed_run = tmp_path / "runs" / "core" / "GOOD" / "bad" / "meta.yaml"
    malformed_run.parent.mkdir(parents=True)
    malformed_run.write_text("id: definitely-not-a-uuid\n")
    malformed_link = tmp_path / "state" / "links" / "bad.yaml"
    malformed_link.parent.mkdir(parents=True)
    malformed_link.write_text("from_ref: missing-required-fields\n")

    result = await reindex_project(db, project.id, tmp_path)

    assert result.created == 1
    assert result.invalid == 3
    assert len(result.errors) == 3
    assert (await db.exec(select(AimUnit))).one().name == "GOOD"
