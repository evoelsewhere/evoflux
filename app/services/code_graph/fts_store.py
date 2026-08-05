"""SQLite FTS5 full-text search for code symbols.

Maintains the canonical ``code_node_fts`` virtual table for fast prefix
matching across symbol names, paths, signatures, and documentation.  FTS is a
derived index: when its schema no longer matches the current definition it is
recreated in place and lazily populated from ``code_nodes``.

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
_FTS_COLUMNS = (
    "node_id",
    "workspace_id",
    "name",
    "qualified_name",
    "file_path",
    "signature",
    "docstring",
    "kind",
    "language",
)

FtsRow = tuple[str, str, str, str, str, str, str, str]


@contextmanager
def _open(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    finally:
        conn.close()


def ensure_fts_table(db_path: str) -> None:
    """Ensure the one canonical FTS table has the current derived schema."""
    with _open(db_path) as conn:
        current_columns = tuple(
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_FTS_TABLE})").fetchall()
        )
        if current_columns == _FTS_COLUMNS:
            return

        # Schema replacement is rare, but two first-use queries can race. Take
        # the write lock only on the slow path and re-check after acquiring it.
        conn.execute("BEGIN IMMEDIATE")
        current_columns = tuple(
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_FTS_TABLE})").fetchall()
        )
        if current_columns and current_columns != _FTS_COLUMNS:
            logger.info(
                "code_graph rebuilding outdated FTS schema columns={}",
                current_columns,
            )
            conn.execute(f"DROP TABLE {_FTS_TABLE}")
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE}
            USING fts5(
                node_id UNINDEXED,
                workspace_id UNINDEXED,
                name,
                qualified_name,
                file_path,
                signature,
                docstring,
                kind UNINDEXED,
                language UNINDEXED,
                tokenize='unicode61 remove_diacritics 2 tokenchars _'
            )
        """)
        conn.commit()


def _bootstrap_workspace(conn: sqlite3.Connection, workspace_id: str) -> None:
    """Populate a newly-created FTS workspace from the authoritative table."""
    present = conn.execute(
        f"SELECT 1 FROM {_FTS_TABLE} WHERE workspace_id = ? LIMIT 1",
        (workspace_id,),
    ).fetchone()
    if present is not None:
        return
    try:
        conn.execute(
            f"""
            INSERT INTO {_FTS_TABLE}(
                node_id, workspace_id, name, qualified_name, file_path,
                signature, docstring, kind, language
            )
            SELECT CAST(id AS TEXT), ?, name,
                   qualified_name, file_path, COALESCE(signature, ''),
                   COALESCE(docstring, ''), kind, language
            FROM code_nodes
            WHERE REPLACE(CAST(workspace_id AS TEXT), '-', '') = ?
            """,
            (workspace_id, workspace_id.replace("-", "")),
        )
        conn.commit()
    except sqlite3.OperationalError as exc:
        logger.debug("fts_bootstrap_error workspace={} err={}", workspace_id, exc)


def rebuild_workspace_fts(
    db_path: str,
    workspace_id: str,
    rows: Sequence[FtsRow],
) -> int:
    """Replace all FTS entries for a workspace.

    Each row is ``(node_id, name, qualified_name, file_path, signature,
    docstring, kind, language)``.
    Returns the number of rows written.
    """
    ensure_fts_table(db_path)
    with _open(db_path) as conn:
        conn.execute(
            f"DELETE FROM {_FTS_TABLE} WHERE workspace_id = ?", (workspace_id,)
        )
        conn.executemany(
            f"""INSERT INTO {_FTS_TABLE}(
                node_id, workspace_id, name, qualified_name, file_path,
                signature, docstring, kind, language
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(node_id, workspace_id, *values) for node_id, *values in rows],
        )
        conn.commit()
        return len(rows)


def update_workspace_fts(
    db_path: str,
    workspace_id: str,
    upserts: Sequence[FtsRow],
    removed_ids: Sequence[str],
) -> None:
    """Incrementally update FTS entries for changed/removed nodes."""
    ensure_fts_table(db_path)
    with _open(db_path) as conn:
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            conn.execute(
                f"DELETE FROM {_FTS_TABLE} WHERE node_id IN ({placeholders})",
                list(removed_ids),
            )
        # Upsert: delete then reinsert (FTS5 has no UPDATE for content)
        if upserts:
            for node_id, *_values in upserts:
                conn.execute(f"DELETE FROM {_FTS_TABLE} WHERE node_id = ?", (node_id,))
            conn.executemany(
                f"""INSERT INTO {_FTS_TABLE}(
                    node_id, workspace_id, name, qualified_name, file_path,
                    signature, docstring, kind, language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(node_id, workspace_id, *values) for node_id, *values in upserts],
            )
        conn.commit()


def _search_fts_conn(
    conn: sqlite3.Connection,
    workspace_id: str,
    query: str,
    limit: int,
    kind: str | None = None,
    language: str | None = None,
) -> list[str]:
    try:
        conn.execute(f"SELECT 1 FROM {_FTS_TABLE} LIMIT 0")
    except sqlite3.OperationalError:
        return []  # table doesn't exist yet

    _bootstrap_workspace(conn, workspace_id)

    # Sanitize: strip FTS5 special chars, split into tokens, add prefix *.
    tokens = _tokenize_query(query)
    if not tokens:
        return []

    fts_expr = " AND ".join(f'"{t}"*' for t in tokens)
    try:
        clauses = ["workspace_id = ?", f"{_FTS_TABLE} MATCH ?"]
        params: list[str | int] = [workspace_id, fts_expr]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if language:
            clauses.append("language = ?")
            params.append(language)
        params.append(limit)
        cursor = conn.execute(
            f"SELECT node_id FROM {_FTS_TABLE} "
            f"WHERE {' AND '.join(clauses)} ORDER BY rank LIMIT ?",
            params,
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
    kind: str | None = None,
    language: str | None = None,
) -> list[str]:
    """Search FTS5 and return matching ``node_id`` strings, ranked by relevance.

    The query is tokenized and matched with implicit prefix: ``hello`` matches
    ``hello_world``. Multi-word queries use AND logic.
    """
    ensure_fts_table(db_path)
    with _open(db_path) as conn:
        return _search_fts_conn(
            conn, workspace_id, query, limit, kind=kind, language=language
        )


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
    ensure_fts_table(db_path)
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
