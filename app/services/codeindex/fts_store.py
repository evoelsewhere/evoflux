"""Persistent FTS5 projection for parser-aligned source chunks."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from loguru import logger

from app.services.code_graph.query import identifier_search_text

_FTS_TABLE = "code_index_chunk_fts"
_FTS_COLUMNS = (
    "chunk_id",
    "workspace_id",
    "file_path",
    "name",
    "qualified_name",
    "identifiers",
    "signature",
    "docstring",
    "content",
    "kind",
    "language",
    "line_start",
    "line_end",
)
_SQLITE_BATCH = 400


@dataclass(frozen=True, slots=True)
class FtsHit:
    chunk_id: str
    rank: float


@contextmanager
def _open(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    finally:
        conn.close()


def ensure_fts_table(db_path: str) -> None:
    """Create or replace the derived table when its schema version changes."""
    with _open(db_path) as conn:
        current = tuple(
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_FTS_TABLE})").fetchall()
        )
        if current == _FTS_COLUMNS:
            return
        conn.execute("BEGIN IMMEDIATE")
        current = tuple(
            row[1]
            for row in conn.execute(f"PRAGMA table_info({_FTS_TABLE})").fetchall()
        )
        if current and current != _FTS_COLUMNS:
            conn.execute(f"DROP TABLE {_FTS_TABLE}")
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE}
            USING fts5(
                chunk_id UNINDEXED,
                workspace_id UNINDEXED,
                file_path,
                name,
                qualified_name,
                identifiers,
                signature,
                docstring,
                content,
                kind UNINDEXED,
                language UNINDEXED,
                line_start UNINDEXED,
                line_end UNINDEXED,
                tokenize='unicode61 remove_diacritics 2 tokenchars _'
            )
        """)
        conn.commit()


def refresh_workspace_files(
    db_path: str,
    workspace_id: str,
    file_paths: Sequence[str],
) -> None:
    """Refresh only affected source components from the authoritative table."""
    if not file_paths:
        return
    ensure_fts_table(db_path)
    unique_paths = tuple(dict.fromkeys(file_paths))
    with _open(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for start in range(0, len(unique_paths), _SQLITE_BATCH):
            batch = unique_paths[start : start + _SQLITE_BATCH]
            placeholders = ",".join("?" for _ in batch)
            conn.execute(
                f"DELETE FROM {_FTS_TABLE} "
                f"WHERE workspace_id = ? AND file_path IN ({placeholders})",
                (workspace_id, *batch),
            )
            rows = conn.execute(
                """
                SELECT CAST(id AS TEXT), file_path, name, qualified_name,
                       COALESCE(signature, ''), COALESCE(docstring, ''), content,
                       kind, language, line_start, line_end
                FROM code_index_chunks
                WHERE REPLACE(CAST(workspace_id AS TEXT), '-', '') = ?
                """
                + f" AND file_path IN ({placeholders})",
                (workspace_id.replace("-", ""), *batch),
            ).fetchall()
            _insert_rows(conn, workspace_id, rows)
        conn.commit()


def _bootstrap_workspace(conn: sqlite3.Connection, workspace_id: str) -> None:
    present = conn.execute(
        f"SELECT 1 FROM {_FTS_TABLE} WHERE workspace_id = ? LIMIT 1",
        (workspace_id,),
    ).fetchone()
    if present is not None:
        return
    try:
        rows = conn.execute(
            """
            SELECT CAST(id AS TEXT), file_path, name, qualified_name,
                   COALESCE(signature, ''), COALESCE(docstring, ''), content,
                   kind, language, line_start, line_end
            FROM code_index_chunks
            WHERE REPLACE(CAST(workspace_id AS TEXT), '-', '') = ?
            """,
            (workspace_id.replace("-", ""),),
        ).fetchall()
        _insert_rows(conn, workspace_id, rows)
        conn.commit()
    except sqlite3.OperationalError as exc:
        logger.debug("codeindex_fts_bootstrap_error workspace={} err={}", workspace_id, exc)


def _insert_rows(
    conn: sqlite3.Connection,
    workspace_id: str,
    rows: Sequence[tuple],
) -> None:
    conn.executemany(
        f"""INSERT INTO {_FTS_TABLE}(
            chunk_id, workspace_id, file_path, name, qualified_name, identifiers,
            signature, docstring, content, kind, language, line_start, line_end
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                chunk_id,
                workspace_id,
                file_path,
                name,
                qualified_name,
                identifier_search_text(
                    file_path, name, qualified_name, signature, docstring
                ),
                signature,
                docstring,
                content,
                kind,
                language,
                str(line_start),
                str(line_end),
            )
            for (
                chunk_id,
                file_path,
                name,
                qualified_name,
                signature,
                docstring,
                content,
                kind,
                language,
                line_start,
                line_end,
            ) in rows
        ],
    )


def search_many(
    db_path: str,
    lookups: Sequence[tuple[str, str]],
    *,
    path: str | None = None,
    language: str | None = None,
    limit: int = 100,
) -> list[list[FtsHit]]:
    """Search several repositories over one connection for cheap cross-repo merge."""
    if not lookups:
        return []
    ensure_fts_table(db_path)
    with _open(db_path) as conn:
        return [
            _search_connection(
                conn,
                workspace_id,
                query,
                path=path,
                language=language,
                limit=limit,
            )
            for workspace_id, query in lookups
        ]


def _search_connection(
    conn: sqlite3.Connection,
    workspace_id: str,
    query: str,
    *,
    path: str | None,
    language: str | None,
    limit: int,
) -> list[FtsHit]:
    _bootstrap_workspace(conn, workspace_id)
    tokens = _query_tokens(query)
    if not tokens:
        return []
    expression = " OR ".join(f'"{token}"*' for token in tokens)
    clauses = ["workspace_id = ?", f"{_FTS_TABLE} MATCH ?"]
    parameters: list[str | int] = [workspace_id, expression]
    if path:
        clauses.append("file_path LIKE ?")
        parameters.append(f"%{path.replace('\\', '/')}%")
    if language:
        clauses.append("language = ?")
        parameters.append(language)
    parameters.append(limit)
    try:
        rows = conn.execute(
            f"SELECT chunk_id, bm25({_FTS_TABLE}, 0, 0, 3, 15, 12, 10, 8, 5, 1, 0, 0, 0, 0) "
            f"FROM {_FTS_TABLE} WHERE {' AND '.join(clauses)} "
            f"ORDER BY bm25({_FTS_TABLE}, 0, 0, 3, 15, 12, 10, 8, 5, 1, 0, 0, 0, 0) "
            "LIMIT ?",
            parameters,
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.debug("codeindex_fts_search_error query={} err={}", query, exc)
        return []
    return [FtsHit(chunk_id=row[0], rank=-float(row[1])) for row in rows]


def _query_tokens(query: str) -> tuple[str, ...]:
    expanded = identifier_search_text(query).split()
    return tuple(dict.fromkeys(token for token in expanded if len(token) >= 2))


__all__ = ["FtsHit", "ensure_fts_table", "refresh_workspace_files", "search_many"]
