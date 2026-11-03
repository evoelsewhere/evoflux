"""Shared helpers for the memory-search contract (wiki store and the two search routes)."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}

SEARCH_APP = "/api/team/search-app"
SEARCH_EVERYWHERE = "/api/team/workspace/search-everywhere"

#: (method, path, json body) for every route of the unit, used by the auth tests.
ROUTES = [
    ("GET", "/api/wiki/tree", None),
    ("GET", "/api/wiki/file?path=USER.md", None),
    ("PUT", "/api/wiki/file", {"path": "topics/x.md", "content": "x"}),
    ("DELETE", "/api/wiki/file?path=topics/x.md", None),
    ("POST", SEARCH_APP, {"query": "x"}),
    ("POST", SEARCH_EVERYWHERE + "?workspace=.", {"query": "x"}),
]

SECTIONS = (
    "system",
    "notes",
    "topics",
    "entities",
    "sources",
    "comparisons",
    "imports",
)
INFO_KEYS = {"path", "description", "updated", "tags", "confidence", "sources"}


def hex_id(n: int) -> str:
    return uuid.UUID(int=n).hex


def uid(n: int) -> str:
    """The canonical (dashed) form the API returns for ``hex_id(n)``."""
    return str(uuid.UUID(int=n))


def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "evoflux.db"


def insert_session(tmp_path: Path, n: int, title: str | None, **columns: object) -> str:
    """Insert one ``chat_sessions`` row (32-hex id derived from *n*) and return the id."""
    row = {
        "id": hex_id(n),
        "title": title,
        "created_at": "2026-01-01 00:00:00.000000",
        "updated_at": f"2026-01-01 00:00:{n:02d}.000000",
        **columns,
    }
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with closing(sqlite3.connect(db_path(tmp_path), timeout=30)) as conn, conn:
        conn.execute(
            f"INSERT INTO chat_sessions ({names}) VALUES ({marks})", tuple(row.values())
        )
    return str(row["id"])


def insert_message(
    tmp_path: Path,
    n: int,
    session_id: str,
    role: str,
    content: str | None,
    **columns: object,
) -> str:
    row = {
        "id": hex_id(1000 + n),
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": f"2026-01-01 00:01:{n:02d}.000000",
        **columns,
    }
    names = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with closing(sqlite3.connect(db_path(tmp_path), timeout=30)) as conn, conn:
        conn.execute(
            f"INSERT INTO session_messages ({names}) VALUES ({marks})",
            tuple(row.values()),
        )
    return str(row["id"])


def scrub(value: object) -> object:
    """Replace ids and timestamps that differ between runs."""
    import re

    text = __import__("json").dumps(value, sort_keys=True)
    text = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", text
    )
    text = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?", "<ts>", text)
    return __import__("json").loads(text)
