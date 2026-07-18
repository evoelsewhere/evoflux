from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.aim import kb_store
from app.services.aim.project import resolve_repo_identity
from app.services.aim.project_setup import (
    create_aim_project,
    join_aim_project,
    preview_aim_manifest,
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
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    return repo


def test_resolve_repo_identity_falls_back_to_basename_for_non_git_dir(tmp_path):
    repo = _make_repo(tmp_path, "plain-dir")
    assert resolve_repo_identity(str(repo)) == "plain-dir"


@pytest.mark.asyncio
async def test_create_aim_project_scaffolds_kb_and_writes_manifest(db, tmp_path):
    source = _make_repo(tmp_path, "core-batch-src")
    target = _make_repo(tmp_path, "core-batch-target")
    kb_path = tmp_path / "core-batch-kb"

    project = await create_aim_project(
        db,
        name="core-batch migration",
        rulebook_id="java8-java21",
        rulebook_version="0.1",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    assert project.kind == "aim"
    assert (kb_path / "aim.yaml").exists()
    assert (kb_path / "INDEX.md").exists()

    manifest = kb_store.read_manifest(kb_path)
    assert manifest.rulebook.id == "java8-java21"
    assert manifest.roles.source == ["core-batch-src"]
    assert manifest.roles.target == ["core-batch-target"]

    aim_settings = project.settings["aim"]
    assert aim_settings["rulebook"]["id"] == "java8-java21"
    assert len(aim_settings["roles"]["source"]) == 1
    assert len(aim_settings["roles"]["target"]) == 1
    assert len(aim_settings["roles"]["kb"]) == 1


@pytest.mark.asyncio
async def test_create_aim_project_uses_pack_declared_compare_profile(
    db, tmp_path, monkeypatch
):
    """create_manifest used to hardcode compare_default_profile="default"
    regardless of what the rulebook pack itself declares — this is the
    regression test for reading the pack's own value instead."""
    from app.services.aim import rulebook_install

    pack_dir = tmp_path / "fake-pack"
    pack_dir.mkdir()
    (pack_dir / "rulebook.yaml").write_text(
        "id: fake-pack\nversion: '0.1'\ncompare_default_profile: strict\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rulebook_install, "_pack_dir", lambda _rid: pack_dir)

    source = _make_repo(tmp_path, "pack-src")
    target = _make_repo(tmp_path, "pack-target")
    kb_path = tmp_path / "pack-kb"

    await create_aim_project(
        db,
        name="pack profile test",
        rulebook_id="fake-pack",
        rulebook_version="0.1",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    manifest = kb_store.read_manifest(kb_path)
    assert manifest.compare_default_profile == "strict"


@pytest.mark.asyncio
async def test_create_aim_project_registers_all_workspaces(db, tmp_path):
    from sqlmodel import select

    from app.models.chat import CodingProjectWorkspace

    source = _make_repo(tmp_path, "src")
    target = _make_repo(tmp_path, "tgt")
    kb_path = tmp_path / "kb"

    project = await create_aim_project(
        db,
        name="p",
        rulebook_id="default",
        rulebook_version="0.1",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    links = (
        await db.exec(
            select(CodingProjectWorkspace).where(
                CodingProjectWorkspace.project_id == project.id
            )
        )
    ).all()
    assert len(links) == 3  # source + target + kb


@pytest.mark.asyncio
async def test_preview_aim_manifest_reads_existing_kb(db, tmp_path):
    source = _make_repo(tmp_path, "src")
    target = _make_repo(tmp_path, "tgt")
    kb_path = tmp_path / "kb"
    await create_aim_project(
        db,
        name="p",
        rulebook_id="vb6-dotnet",
        rulebook_version="0.2",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    manifest = await preview_aim_manifest(str(kb_path))
    assert manifest.rulebook.id == "vb6-dotnet"
    assert manifest.rulebook.version == "0.2"


@pytest.mark.asyncio
async def test_preview_aim_manifest_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        await preview_aim_manifest(str(tmp_path / "nope"))


@pytest.mark.asyncio
async def test_join_aim_project_reuses_manifest_rulebook(db, tmp_path):
    # First "member" creates the project.
    source1 = _make_repo(tmp_path, "src-a")
    target1 = _make_repo(tmp_path, "tgt-a")
    kb_path = tmp_path / "shared-kb"
    await create_aim_project(
        db,
        name="original",
        rulebook_id="java8-java21",
        rulebook_version="0.1",
        source_paths=[str(source1)],
        target_path=str(target1),
        kb_path=str(kb_path),
    )
    await db.commit()

    # Second "member" joins via the same KB with their own local paths.
    source2 = _make_repo(tmp_path, "src-b-local-clone")
    target2 = _make_repo(tmp_path, "tgt-b-local-clone")
    joined = await join_aim_project(
        db,
        name="joined-copy",
        kb_path=str(kb_path),
        source_paths=[str(source2)],
        target_path=str(target2),
    )
    await db.commit()

    assert joined.kind == "aim"
    assert joined.settings["aim"]["rulebook"]["id"] == "java8-java21"
    assert joined.settings["aim"]["rulebook"]["version"] == "0.1"


@pytest.mark.asyncio
async def test_join_aim_project_missing_manifest_raises(db, tmp_path):
    with pytest.raises(FileNotFoundError):
        await join_aim_project(
            db,
            name="x",
            kb_path=str(tmp_path / "no-kb-here"),
            source_paths=[str(_make_repo(tmp_path, "s"))],
            target_path=str(_make_repo(tmp_path, "t")),
        )
