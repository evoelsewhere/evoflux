"""sqlite-vec vector store for code symbol embeddings.

A single persistent ``vec0`` virtual table (``vec_code_node``) holds one vector
per :class:`~app.models.code_graph.CodeNode`, partitioned by ``workspace_id`` so
KNN queries and bulk deletes stay scoped to one workspace.

All operations use a dedicated raw :mod:`sqlite3` connection (the loadable
extension is enabled per-connection) and are synchronous; callers run them in a
worker thread via ``asyncio.to_thread``. The connection targets the same file as
the ORM engine, resolved through :func:`app.core.db.current_sqlite_path`.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator, Sequence

from loguru import logger

_TABLE = "vec_code_node"


class VectorStoreUnavailable(RuntimeError):
    """Raised when sqlite-vec cannot be loaded or the DB path is unknown."""


@contextmanager
def open_connection(db_path: str) -> Iterator[sqlite3.Connection]:
    """Open a sqlite3 connection with the sqlite-vec extension loaded."""
    try:
        import sqlite_vec
    except Exception as exc:  # pragma: no cover - dependency guard
        raise VectorStoreUnavailable(f"sqlite-vec import failed: {exc}") from exc

    conn = sqlite3.connect(db_path)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA busy_timeout=5000")
        yield conn
    finally:
        conn.close()


def _serialize(vector: Sequence[float]):
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(vector))


def ensure_table(conn: sqlite3.Connection, dim: int) -> None:
    """Create the vec0 table if missing (vector dimension fixed at ``dim``).

    ``node_id`` is the primary key so individual symbol vectors can be deleted
    or replaced during an incremental re-index; ``workspace_id`` is the
    partition key so KNN and bulk deletes stay scoped to one workspace.
    """
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING vec0("
        "node_id text primary key, "
        "workspace_id text partition key, "
        f"embedding float[{dim}]"
        ")"
    )


def delete_workspace(conn: sqlite3.Connection, workspace_id: str) -> None:
    """Remove every vector for ``workspace_id``."""
    conn.execute(f"DELETE FROM {_TABLE} WHERE workspace_id = ?", (workspace_id,))


def delete_nodes(conn: sqlite3.Connection, node_ids: Sequence[str]) -> None:
    """Remove vectors for the given ``node_ids`` (incremental re-index)."""
    for node_id in node_ids:
        conn.execute(f"DELETE FROM {_TABLE} WHERE node_id = ?", (node_id,))


def upsert_rows(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    dim: int,
    rows: Sequence[tuple[str, Sequence[float]]],
) -> int:
    """Insert or replace individual ``(node_id, vector)`` rows.

    Unlike :func:`replace_workspace_vectors` this leaves the workspace's other
    vectors untouched — used by incremental re-index to refresh only the
    symbols that changed. Returns the number of vectors written.
    """
    ensure_table(conn, dim)
    written = 0
    for node_id, vector in rows:
        if len(vector) != dim:
            continue
        # vec0 has no UPSERT; delete the old row (if any) before inserting.
        conn.execute(f"DELETE FROM {_TABLE} WHERE node_id = ?", (node_id,))
        conn.execute(
            f"INSERT INTO {_TABLE}(node_id, workspace_id, embedding) VALUES (?, ?, ?)",
            (node_id, workspace_id, _serialize(vector)),
        )
        written += 1
    return written


def replace_workspace_vectors(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    dim: int,
    rows: Sequence[tuple[str, Sequence[float]]],
) -> int:
    """Replace all vectors for a workspace with ``rows`` of ``(node_id, vector)``.

    Returns the number of vectors written.
    """
    ensure_table(conn, dim)
    delete_workspace(conn, workspace_id)
    written = 0
    for node_id, vector in rows:
        if len(vector) != dim:
            continue
        conn.execute(
            f"INSERT INTO {_TABLE}(workspace_id, node_id, embedding) VALUES (?, ?, ?)",
            (workspace_id, node_id, _serialize(vector)),
        )
        written += 1
    conn.commit()
    logger.info("code_graph vec upsert workspace={} written={}", workspace_id, written)
    return written


def knn(
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
    query_vector: Sequence[float],
    k: int,
) -> list[tuple[str, float]]:
    """Return up to ``k`` ``(node_id, distance)`` pairs nearest to the query."""
    try:
        cursor = conn.execute(
            f"SELECT node_id, distance FROM {_TABLE} "
            "WHERE workspace_id = ? AND embedding MATCH ? AND k = ? "
            "ORDER BY distance",
            (workspace_id, _serialize(query_vector), k),
        )
    except sqlite3.OperationalError:
        # Table not created yet (no embeddings indexed) — treat as empty.
        return []
    return [(str(row[0]), float(row[1])) for row in cursor.fetchall()]


def count_workspace(conn: sqlite3.Connection, workspace_id: str) -> int:
    """Return how many vectors are stored for ``workspace_id``."""
    try:
        cursor = conn.execute(
            f"SELECT count(*) FROM {_TABLE} WHERE workspace_id = ?",
            (workspace_id,),
        )
    except sqlite3.OperationalError:
        return 0
    row = cursor.fetchone()
    return int(row[0]) if row else 0
