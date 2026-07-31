"""Fast, explicit database-schema compatibility checks for desktop startup."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.db import current_sqlite_path

# Keep this in sync with the single Alembic head. The migration tests and the
# sidecar build validate the value, so a release cannot silently ship a stale
# marker.
SCHEMA_HEAD = "00000038"


@dataclass(frozen=True)
class SchemaStatus:
    current: str | None
    at_head: bool
    compatible: bool


def inspect_database_schema() -> SchemaStatus:
    """Inspect SQLite's revision without importing/running Alembic.

    A database at the bundled head is the common path and can skip Alembic's
    comparatively expensive environment import. An unknown revision usually
    means an older app is opening data written by a newer release; fail with a
    useful message instead of Alembic's opaque "Can't locate revision" error.
    Non-SQLite deployments retain the normal migration path.
    """

    raw_path = current_sqlite_path()
    if raw_path is None:
        return SchemaStatus(current=None, at_head=False, compatible=True)

    db_path = Path(raw_path).expanduser()
    if not db_path.is_file():
        return SchemaStatus(current=None, at_head=False, compatible=True)

    try:
        database_uri = f"{db_path.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(database_uri, uri=True, timeout=2) as db:
            row = db.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return SchemaStatus(current=None, at_head=False, compatible=True)
        logger.warning("schema_preflight_failed error={}", exc)
        return SchemaStatus(current=None, at_head=False, compatible=True)

    current = str(row[0]) if row and row[0] else None
    if current is None:
        return SchemaStatus(current=None, at_head=False, compatible=True)
    if current == SCHEMA_HEAD:
        return SchemaStatus(current=current, at_head=True, compatible=True)

    revisions_dir = Path(__file__).resolve().parent.parent / "migrations" / "versions"
    bundled = {
        path.name.split("_", 1)[0]
        for path in revisions_dir.glob("*.py")
        if path.name[:1].isdigit()
    }
    return SchemaStatus(
        current=current,
        at_head=False,
        compatible=current in bundled,
    )


def ensure_database_revision_is_supported(status: SchemaStatus) -> None:
    if status.compatible:
        return
    raise RuntimeError(
        "Database schema revision "
        f"'{status.current}' is newer than or unknown to this EvoFlux build "
        f"(bundled head: '{SCHEMA_HEAD}'). Install a newer EvoFlux version; "
        "downgrading an existing data directory is not supported."
    )
