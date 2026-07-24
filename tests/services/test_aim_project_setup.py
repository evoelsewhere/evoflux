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
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    return repo


def test_resolve_repo_identity_falls_back_to_basename_for_non_git_dir(tmp_path):
    repo = _make_repo(tmp_path, "plain-dir")
    assert resolve_repo_identity(str(repo)) == "plain-dir"


def test_aim_kb_template_prefers_checkout_then_wheel_bundle(tmp_path, monkeypatch):
    import app as app_pkg

    repo = tmp_path / "repo"
    fake_module = repo / "app" / "services" / "aim" / "kb_store.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("")
    checkout_template = repo / "seed" / "aim-kb-template"
    checkout_template.mkdir(parents=True)
    site_app = tmp_path / "site-packages" / "app"
    bundled_template = site_app / "_seed" / "aim-kb-template"
    bundled_template.mkdir(parents=True)
    monkeypatch.setattr(kb_store, "__file__", str(fake_module))
    monkeypatch.setattr(app_pkg, "__file__", str(site_app / "__init__.py"))

    assert kb_store.aim_kb_template_dir() == checkout_template.resolve()

    checkout_template.rmdir()
    assert kb_store.aim_kb_template_dir() == bundled_template.resolve()


@pytest.mark.asyncio
async def test_create_aim_project_scaffolds_kb_and_writes_manifest(db, tmp_path):
    source = _make_repo(tmp_path, "core-batch-src")
    target = _make_repo(tmp_path, "core-batch-target")
    kb_path = tmp_path / "core-batch-kb"

    project = await create_aim_project(
        db,
        name="core-batch migration",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    assert project.kind == "aim"
    assert (kb_path / "aim.yaml").exists()
    assert (kb_path / "INDEX.md").exists()

    manifest = kb_store.read_manifest(kb_path)
    assert manifest.rulebook.id == "core-batch-migration-rulebook"
    assert manifest.roles.source == ["core-batch-src"]
    assert manifest.roles.target == ["core-batch-target"]
    assert (kb_path / "rulebook" / "rulebook.yaml").is_file()
    assert (kb_path / "rulebook" / "README.md").is_file()
    assert (kb_path / "GUIDELINES.md").is_file()
    assert (kb_path / "rulebook" / "GUIDELINES.md").is_file()
    assert (kb_path / "rulebook" / "canonicalizers" / "default.yaml").is_file()
    assert not (kb_path / "rulebook" / "rulebook.example.yaml").exists()

    aim_settings = project.settings["aim"]
    assert aim_settings["rulebook"]["id"] == "core-batch-migration-rulebook"
    assert len(aim_settings["roles"]["source"]) == 1
    assert len(aim_settings["roles"]["target"]) == 1
    assert len(aim_settings["roles"]["kb"]) == 1


@pytest.mark.asyncio
async def test_create_aim_project_uses_local_rulebook_compare_profile(
    db, tmp_path, monkeypatch
):
    template = tmp_path / "template"
    (template / "rulebook").mkdir(parents=True)
    (template / "rulebook" / "rulebook.yaml").write_text(
        "id: project-rulebook\nversion: '0.1'\ncompare_default_profile: strict\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kb_store, "aim_kb_template_dir", lambda: template)

    source = _make_repo(tmp_path, "pack-src")
    target = _make_repo(tmp_path, "pack-target")
    kb_path = tmp_path / "pack-kb"

    await create_aim_project(
        db,
        name="pack profile test",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    manifest = kb_store.read_manifest(kb_path)
    assert manifest.compare_default_profile == "strict"


@pytest.mark.asyncio
async def test_create_aim_project_preserves_prepared_local_rulebook(db, tmp_path):
    source = _make_repo(tmp_path, "prepared-src")
    target = _make_repo(tmp_path, "prepared-target")
    kb_path = tmp_path / "prepared-kb"
    (kb_path / "rulebook").mkdir(parents=True)
    (kb_path / "rulebook" / "rulebook.yaml").write_text(
        "id: engagement-policy\n"
        "version: '3.2'\n"
        "compare_default_profile: strict\n",
        encoding="utf-8",
    )

    project = await create_aim_project(
        db,
        name="prepared migration",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )

    manifest = kb_store.read_manifest(kb_path)
    assert manifest.rulebook.id == "engagement-policy"
    assert manifest.rulebook.version == "3.2"
    assert manifest.compare_default_profile == "strict"
    assert project.settings["aim"]["rulebook"] == {
        "id": "engagement-policy",
        "version": "3.2",
    }


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
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    await db.commit()

    manifest = await preview_aim_manifest(str(kb_path))
    assert manifest.rulebook.id == "p-rulebook"
    assert manifest.rulebook.version == "0.1"


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
    assert joined.settings["aim"]["rulebook"]["id"] == "original-rulebook"
    assert joined.settings["aim"]["rulebook"]["version"] == "0.1"


@pytest.mark.asyncio
async def test_join_aim_project_requires_local_rulebook(db, tmp_path):
    source = _make_repo(tmp_path, "source")
    target = _make_repo(tmp_path, "target")
    kb_path = tmp_path / "kb"
    await create_aim_project(
        db,
        name="original",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    (kb_path / "rulebook" / "rulebook.yaml").unlink()

    with pytest.raises(FileNotFoundError, match="rulebook manifest is missing"):
        await join_aim_project(
            db,
            name="joined",
            kb_path=str(kb_path),
            source_paths=[str(source)],
            target_path=str(target),
        )


@pytest.mark.asyncio
async def test_join_aim_project_rejects_rulebook_identity_mismatch(db, tmp_path):
    source = _make_repo(tmp_path, "source")
    target = _make_repo(tmp_path, "target")
    kb_path = tmp_path / "kb"
    await create_aim_project(
        db,
        name="original",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(kb_path),
    )
    rulebook_path = kb_path / "rulebook" / "rulebook.yaml"
    rulebook_path.write_text(
        rulebook_path.read_text(encoding="utf-8").replace(
            "id: original-rulebook", "id: copied-from-another-project"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        await join_aim_project(
            db,
            name="joined",
            kb_path=str(kb_path),
            source_paths=[str(source)],
            target_path=str(target),
        )


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
