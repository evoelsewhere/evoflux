"""SQLite FTS5 full-text search for code symbol names.

Maintains a ``code_node_fts`` virtual table that enables fast prefix/substring
token matching on ``name``, ``qualified_name``, and ``docstring``.  The table
is auto-created on first use and rebuilt during reindex.

All operations are synchronous and run in a worker thread via the query
executor.  The FTS table targets the same SQLite file as the ORM engine.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Iterator

from loguru import logger

_FTS_TABLE = "code_node_fts"


@contextmanager
def _open(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    finally:
        conn.close()


def ensure_fts_table(db_path: str) -> None:
    """Create the FTS5 virtual table if it doesn't exist."""
    with _open(db_path) as conn:
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE}
            USING fts5(
                node_id UNINDEXED,
                workspace_id UNINDEXED,
                name,
                qualified_name,
                tokenize='unicode61 remove_diacritics 2 tokenchars _'
            )
        """)
        conn.commit()


def rebuild_workspace_fts(
    db_path: str,
    workspace_id: str,
    rows: Sequence[tuple[str, str, str]],
) -> int:
    """Replace all FTS entries for a workspace.

    Each row is ``(node_id, name, qualified_name)``.
    Returns the number of rows written.
    """
    with _open(db_path) as conn:
        ensure_fts_table(db_path)
        conn.execute(
            f"DELETE FROM {_FTS_TABLE} WHERE workspace_id = ?", (workspace_id,)
        )
        conn.executemany(
            f"INSERT INTO {_FTS_TABLE}(node_id, workspace_id, name, qualified_name) "
            "VALUES (?, ?, ?, ?)",
            [(node_id, workspace_id, name, qn) for node_id, name, qn in rows],
        )
        conn.commit()
        return len(rows)


def update_workspace_fts(
    db_path: str,
    workspace_id: str,
    upserts: Sequence[tuple[str, str, str]],
    removed_ids: Sequence[str],
) -> None:
    """Incrementally update FTS entries for changed/removed nodes."""
    with _open(db_path) as conn:
        ensure_fts_table(db_path)
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            conn.execute(
                f"DELETE FROM {_FTS_TABLE} WHERE node_id IN ({placeholders})",
                list(removed_ids),
            )
        # Upsert: delete then reinsert (FTS5 has no UPDATE for content)
        if upserts:
            for node_id, name, qn in upserts:
                conn.execute(f"DELETE FROM {_FTS_TABLE} WHERE node_id = ?", (node_id,))
            conn.executemany(
                f"INSERT INTO {_FTS_TABLE}(node_id, workspace_id, name, qualified_name) "
                "VALUES (?, ?, ?, ?)",
                [(node_id, workspace_id, name, qn) for node_id, name, qn in upserts],
            )
        conn.commit()


def _search_fts_conn(
    conn: sqlite3.Connection, workspace_id: str, query: str, limit: int
) -> list[str]:
    try:
        conn.execute(f"SELECT 1 FROM {_FTS_TABLE} LIMIT 0")
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet

    # Sanitize: strip FTS5 special chars, split into tokens, add prefix *
    tokens = _tokenize_query(query)
    if not tokens:
        return []

    fts_expr = " AND ".join(f'"{t}"*' for t in tokens)
    try:
        cursor = conn.execute(
            f"SELECT node_id FROM {_FTS_TABLE} "
            f"WHERE workspace_id = ? AND {_FTS_TABLE} MATCH ? "
            f"ORDER BY rank LIMIT ?",
            (workspace_id, fts_expr, limit),
        )
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.debug("fts_search_error query={} err={}", query, exc)
        return []


def search_fts(
    db_path: str,
    workspace_id: str,
    query: str,
    limit: int = 50,
) -> list[str]:
    """Search FTS5 and return matching ``node_id`` strings, ranked by relevance.

    The query is tokenized and matched with implicit prefix: ``hello`` matches
    ``hello_world``. Multi-word queries use AND logic.
    """
    with _open(db_path) as conn:
        return _search_fts_conn(conn, workspace_id, query, limit)


def search_fts_many(
    db_path: str,
    lookups: Sequence[tuple[str, str]],
    limit: int = 50,
) -> list[list[str]]:
    """Run several ``search_fts`` lookups over one shared connection.

    ``lookups`` is ``(workspace_id, query)`` pairs; results come back in the
    same order. Cross-repo resolution calls this once per unresolved
    reference (one lookup per sibling repo) instead of opening a fresh
    connection per sibling — connection setup is the dominant cost for a
    project with many sibling repos and many unresolved rows.
    """
    if not lookups:
        return []
    with _open(db_path) as conn:
        return [
            _search_fts_conn(conn, workspace_id, query, limit)
            for workspace_id, query in lookups
        ]


def _tokenize_query(query: str) -> list[str]:
    """Split query into clean tokens for FTS5 MATCH expression."""
    # Remove FTS5 operators/special chars
    cleaned = ""
    for ch in query:
        if ch.isalnum() or ch in ("_", " "):
            cleaned += ch
        else:
            cleaned += " "
    return [t for t in cleaned.split() if len(t) >= 2]
