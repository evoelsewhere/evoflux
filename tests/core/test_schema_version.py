from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import app
from app.core import schema_version


def _write_revision(path: Path, revision: str) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        db.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )


def test_schema_head_matches_alembic_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(app.__file__).resolve().parent / "alembic.ini"
    heads = ScriptDirectory.from_config(Config(str(ini))).get_heads()
    assert heads == [schema_version.SCHEMA_HEAD]


def test_schema_preflight_skips_database_at_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "at-head.sqlite"
    _write_revision(db_path, schema_version.SCHEMA_HEAD)
    monkeypatch.setattr(schema_version, "current_sqlite_path", lambda: str(db_path))

    status = schema_version.inspect_database_schema()

    assert status.at_head is True
    assert status.compatible is True


def test_schema_preflight_accepts_legacy_consolidated_easd_head(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "legacy-easd.sqlite"
    _write_revision(db_path, "00000060")
    monkeypatch.setattr(schema_version, "current_sqlite_path", lambda: str(db_path))

    status = schema_version.inspect_database_schema()

    assert status.current == "00000060"
    assert status.at_head is False
    assert status.compatible is True


def test_schema_preflight_rejects_unknown_revision(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "newer.sqlite"
    _write_revision(db_path, "99999999")
    monkeypatch.setattr(schema_version, "current_sqlite_path", lambda: str(db_path))

    status = schema_version.inspect_database_schema()

    assert status.compatible is False
    with pytest.raises(RuntimeError, match="downgrading"):
        schema_version.ensure_database_revision_is_supported(status)
