"""AIM structural-extractor wiring (app/services/aim/extractors.py).

Covers the §3.9 bridge end to end: rulebook manifest → extractor configs →
StructuralParsers for *source* workspaces only → build_registry extras →
reindex_workspace indexes a COBOL/JCL estate into code_nodes/code_edges →
lexical/FTS search finds legacy symbols.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Ensure all SQLModel tables are registered before the session-scoped setup_db
# fixture calls SQLModel.metadata.create_all (needed when running this file alone).
import app.models.chat  # noqa: F401
import app.models.code_graph  # noqa: F401
from app.services.aim import kb_store
from app.services.aim.extractors import (
    extractor_config_paths,
    structural_parsers_for_workspace,
)
from app.services.aim.project_setup import create_aim_project

COBOL_SAMPLE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL01.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM CALC-PARA.
           STOP RUN.
       CALC-PARA.
           ADD 1 TO WS-TOTAL.
"""

JCL_SAMPLE = """\
//NIGHTJOB JOB (ACCT),'NIGHTLY'
//STEP010  EXEC PGM=PAYROLL1
//INFILE   DD DSN=PROD.PAYROLL.INPUT,DISP=SHR
"""

COBOL_EXTRACTOR = {
    "id": "cobol-structural",
    "file_extensions": [".cbl", ".cob"],
    "ignore_case": True,
    "node_rules": [
        {
            "kind": "program",
            "scope": "file",
            "match": r"PROGRAM-ID\s*\.?\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)",
        },
        {
            "kind": "paragraph",
            "scope": "block",
            "match": r"^[\s0-9]{0,7}(?P<name>[A-Za-z][A-Za-z0-9-]*)\s*\.\s*$",
        },
    ],
    "edge_rules": [
        {
            "kind": "calls",
            "from": "paragraph",
            "match": r"\bPERFORM\s+(?P<target>[A-Za-z][A-Za-z0-9-]*)",
        }
    ],
    "keyword_denylist": ["UNTIL", "VARYING", "TIMES"],
}

JCL_EXTRACTOR = {
    "id": "jcl-structural",
    "file_extensions": [".jcl"],
    "ignore_case": True,
    "node_rules": [
        {
            "kind": "job",
            "scope": "file",
            "match": r"^//(?P<name>[A-Z0-9@#$]+)\s+JOB\b",
        },
        {
            "kind": "step",
            "scope": "block",
            "match": r"^//(?P<name>[A-Z0-9@#$]+)\s+EXEC\b",
        },
    ],
    "edge_rules": [
        {
            "kind": "calls",
            "from": "step",
            "match": r"\bPGM=(?P<target>[A-Z0-9@#$]+)",
        }
    ],
    "keyword_denylist": [],
}


def _configure_extractors(kb_root: Path, extractors: dict[str, dict]) -> None:
    rulebook_path = kb_root / "rulebook" / "rulebook.yaml"
    manifest = yaml.safe_load(rulebook_path.read_text(encoding="utf-8"))
    manifest["parser_strategy"] = "structural"
    manifest["extractors"] = [f"extractors/{name}" for name in extractors]
    rulebook_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    if not (kb_root / "aim.yaml").is_file():
        kb_store.create_manifest(
            kb_root,
            rulebook_id=manifest["id"],
            rulebook_version=str(manifest["version"]),
            source_identities=[],
            target_identities=[],
        )
    directory = kb_root / "rulebook" / "extractors"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in extractors.items():
        (directory / name).write_text(
            yaml.safe_dump(content, sort_keys=False), encoding="utf-8"
        )


# ── extractor_config_paths ────────────────────────────────────────────────────


def test_extractor_config_paths_reads_local_manifest_list(tmp_path):
    kb_root = tmp_path / "kb"
    (kb_root / "rulebook").mkdir(parents=True)
    (kb_root / "rulebook" / "rulebook.yaml").write_text(
        "id: local\nversion: '0.1'\n", encoding="utf-8"
    )
    _configure_extractors(
        kb_root,
        {
            "cobol-structural.yaml": COBOL_EXTRACTOR,
            "jcl-structural.yaml": JCL_EXTRACTOR,
        },
    )

    paths = extractor_config_paths(kb_root)
    assert [p.name for p in paths] == [
        "cobol-structural.yaml",
        "jcl-structural.yaml",
    ]


def test_extractor_examples_are_inert_until_declared(tmp_path):
    directory = tmp_path / "rulebook" / "extractors"
    directory.mkdir(parents=True)
    (tmp_path / "rulebook" / "rulebook.yaml").write_text(
        "id: local\nversion: '0.1'\n", encoding="utf-8"
    )
    kb_store.create_manifest(
        tmp_path,
        rulebook_id="local",
        rulebook_version="0.1",
        source_identities=[],
        target_identities=[],
    )
    (directory / "structural.example.yaml").write_text(
        yaml.safe_dump(COBOL_EXTRACTOR, sort_keys=False), encoding="utf-8"
    )

    assert extractor_config_paths(tmp_path) == []


def test_none_parser_strategy_disables_declared_extractors(tmp_path):
    kb_root = tmp_path / "kb"
    (kb_root / "rulebook/extractors").mkdir(parents=True)
    (kb_root / "rulebook/rulebook.yaml").write_text(
        "id: local\nversion: '0.1'\nparser_strategy: none\n"
        "extractors: [extractors/cobol.yaml]\n",
        encoding="utf-8",
    )
    (kb_root / "rulebook/extractors/cobol.yaml").write_text(
        yaml.safe_dump(COBOL_EXTRACTOR, sort_keys=False), encoding="utf-8"
    )
    kb_store.create_manifest(
        kb_root,
        rulebook_id="local",
        rulebook_version="0.1",
        source_identities=[],
        target_identities=[],
    )

    assert extractor_config_paths(kb_root) == []


def test_extractor_config_paths_empty_without_local_rulebook(tmp_path):
    assert extractor_config_paths(tmp_path) == []


def test_extractor_config_paths_reads_only_declared_local_files(tmp_path):
    kb_root = tmp_path / "kb"
    (kb_root / "rulebook").mkdir(parents=True)
    (kb_root / "rulebook" / "rulebook.yaml").write_text(
        "id: local\nversion: '0.1'\n",
        encoding="utf-8",
    )
    _configure_extractors(kb_root, {"only.yaml": COBOL_EXTRACTOR})

    assert [p.name for p in extractor_config_paths(kb_root)] == ["only.yaml"]


# ── structural_parsers_for_workspace (isolated in-memory DB) ─────────────────


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


async def _make_cobol_project(db, tmp_path: Path):
    source = tmp_path / "estate-src"
    source.mkdir()
    (source / "payroll01.cbl").write_text(COBOL_SAMPLE, encoding="utf-8")
    (source / "nightjob.jcl").write_text(JCL_SAMPLE, encoding="utf-8")
    target = tmp_path / "estate-target"
    target.mkdir()
    project = await create_aim_project(
        db,
        name="estate migration",
        source_paths=[str(source)],
        target_path=str(target),
        kb_path=str(tmp_path / "estate-kb"),
    )
    _configure_extractors(
        tmp_path / "estate-kb",
        {
            "cobol-structural.yaml": COBOL_EXTRACTOR,
            "jcl-structural.yaml": JCL_EXTRACTOR,
        },
    )
    await db.commit()
    return project, source


@pytest.mark.asyncio
async def test_source_workspace_gets_structural_parsers(db, tmp_path):
    from uuid import UUID

    project, _ = await _make_cobol_project(db, tmp_path)
    roles = project.settings["aim"]["roles"]

    source_parsers = await structural_parsers_for_workspace(
        db, UUID(roles["source"][0])
    )
    assert sorted(p.name for p in source_parsers) == [
        "cobol-structural",
        "jcl-structural",
    ]

    # Target and KB repos are modern/markdown — no extractors.
    assert await structural_parsers_for_workspace(db, UUID(roles["target"][0])) == []
    assert await structural_parsers_for_workspace(db, UUID(roles["kb"][0])) == []


@pytest.mark.asyncio
async def test_kb_local_rulebook_override_wins_for_extractors(db, tmp_path):
    """Changing the KB-local declaration changes parser resolution."""
    from uuid import UUID

    project, _ = await _make_cobol_project(db, tmp_path)
    roles = project.settings["aim"]["roles"]
    kb_root = tmp_path / "estate-kb"

    _configure_extractors(
        kb_root,
        {
            "solo-structural.yaml": {
                "id": "solo-structural",
                "file_extensions": [".cbl"],
                "node_rules": [
                    {
                        "kind": "program",
                        "scope": "file",
                        "match": r"PROGRAM-ID\s*\.?\s+(?P<name>[A-Za-z0-9][A-Za-z0-9-]*)",
                    }
                ],
            }
        },
    )

    parsers = await structural_parsers_for_workspace(db, UUID(roles["source"][0]))
    assert [p.name for p in parsers] == ["solo-structural"]


@pytest.mark.asyncio
async def test_non_aim_workspace_gets_no_parsers(db, tmp_path):
    from app.services.coding_workspace_service import upsert_coding_workspace

    plain = tmp_path / "plain-repo"
    plain.mkdir()
    ws = await upsert_coding_workspace(db, path=str(plain))
    await db.commit()
    assert await structural_parsers_for_workspace(db, ws.id) == []


# ── full reindex + search on a sample estate (real test DB) ──────────────────


@pytest.mark.asyncio
async def test_reindex_indexes_cobol_estate_and_search_finds_paragraph(
    setup_db, tmp_path
):
    from uuid import UUID

    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace, search_nodes

    async with async_session_factory() as db:
        project, source = await _make_cobol_project(db, tmp_path)
        source_ws_id = UUID(project.settings["aim"]["roles"]["source"][0])
        target_ws_id = UUID(project.settings["aim"]["roles"]["target"][0])
        target_path = tmp_path / "estate-target"
        await db.commit()

    async with async_session_factory() as db:
        stats = await reindex_workspace(
            db, workspace_id=source_ws_id, root_path=str(source)
        )
        await db.commit()

    assert stats.error_count == 0
    assert stats.file_count == 2  # the .cbl and the .jcl
    assert stats.node_count > 0

    async with async_session_factory() as db:
        hits = await search_nodes(db, workspace_id=source_ws_id, query="CALC")
        assert any(
            node.name == "CALC-PARA" and node.kind == "paragraph" for node in hits
        )
        job_hits = await search_nodes(db, workspace_id=source_ws_id, query="STEP010")
        assert any(node.kind == "step" for node in job_hits)

    # The same .cbl content in the TARGET workspace is ignored — extractors
    # are scoped to source-role workspaces, so no parser claims .cbl there.
    (target_path / "leftover.cbl").write_text(COBOL_SAMPLE, encoding="utf-8")
    async with async_session_factory() as db:
        target_stats = await reindex_workspace(
            db, workspace_id=target_ws_id, root_path=str(target_path)
        )
        await db.commit()
    assert target_stats.file_count == 0
