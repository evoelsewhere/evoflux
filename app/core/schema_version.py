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
SCHEMA_HEAD = "00000066"

#: Revisions this build no longer ships, mapped to the newest ancestor it does.
#:
#: `00000055`–`00000062` built the EASD `trace_*` tables and the
#: `delegation_tasks.trace_run_id` column. Those migrations are gone, so a
#: database stamped with one of their ids would strand Alembic on
#: "Can't locate revision" and the app would refuse to start.
#:
#: Stamping forward is safe precisely because `00000065` drops everything those
#: revisions created: replaying `00000063` onward from `00000054` reaches the
#: same schema whether or not the retired ones ever ran.
RETIRED_REVISIONS: dict[str, str] = {
    "00000055": "00000054",
    "00000060": "00000054",
    "00000061": "00000054",
    "00000062": "00000054",
}


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
        compatible=current in bundled or current in RETIRED_REVISIONS,
    )


def repair_retired_revision(sqlite_path: str | Path | None = None) -> str | None:
    """Move a database off a revision this build no longer ships.

    Returns the ancestor it was stamped to, or `None` when nothing changed.
    Alembic calls this from `env.py` before it resolves anything, because that
    is the one place every migration path goes through — the server's automatic
    upgrade, `make migrate`, and a bare `alembic upgrade head` alike. Without it
    a database left on a retired id fails with "Can't locate revision", which
    reads like corruption and is not.

    `sqlite_path` names the database this run is about to touch; callers that
    omit it get the process-wide engine's.
    """

    raw_path = sqlite_path if sqlite_path is not None else current_sqlite_path()
    if raw_path is None:
        return None
    db_path = Path(raw_path).expanduser()
    if not db_path.is_file():
        return None

    try:
        with sqlite3.connect(db_path, timeout=5) as db:
            row = db.execute("SELECT version_num FROM alembic_version").fetchone()
            current = str(row[0]) if row and row[0] else None
            ancestor = RETIRED_REVISIONS.get(current or "")
            if ancestor is None:
                return None
            db.execute("UPDATE alembic_version SET version_num = ?", (ancestor,))
    except sqlite3.OperationalError as exc:
        logger.warning("schema_retired_revision_repair_failed error={}", exc)
        return None

    logger.info("schema_retired_revision_repaired from={} to={}", current, ancestor)
    return ancestor


def ensure_database_revision_is_supported(status: SchemaStatus) -> None:
    if status.compatible:
        return
    raise RuntimeError(
        "Database schema revision "
        f"'{status.current}' is newer than or unknown to this EvoFlux build "
        f"(bundled head: '{SCHEMA_HEAD}'). Install a newer EvoFlux version; "
        "downgrading an existing data directory is not supported."
    )
