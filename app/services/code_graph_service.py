"""Database orchestration for the code knowledge graph.

Persists the in-memory :class:`WorkspaceIndex` produced by the parser pipeline
and exposes read helpers used by agent tools and the API. Parsing runs in a
worker thread (CPU-bound) while all database work stays async.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import asyncio
from uuid import UUID, uuid7

from loguru import logger
from sqlalchemy import delete as sa_delete, func as sa_func
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import current_sqlite_path
from app.core.runtime_settings import load_runtime_settings
from app.models.chat import CodingWorkspace
from app.models.code_graph import CodeEdge, CodeIndexState, CodeNode, CrossRepoEdge
from app.services.code_graph import fts_store as fts
from app.services.code_graph.indexer import (
    ExistingDef,
    UnresolvedImport,
    WorkspaceIndex,
    hash_workspace_files,
    index_files,
    index_workspace,
)
from app.services.code_graph.parsers.registry import ParserRegistry, build_registry
from app.services.code_graph.types import EDGE_IMPORTS

# Cap how many errors we keep on the stats payload.
_MAX_REPORTED_ERRORS = 20

# Single-threaded executor for CPU-heavy indexing work (tree-sitter parsing,
# file hashing). Serializes all code-graph computation to one thread so it
# cannot saturate all cores or spike RAM when multiple workspaces or
# concurrent reindex requests fire simultaneously.
_INDEXER_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="codegraph")

# Separate executor for lightweight query operations (FTS5 lookups) so search
# requests are never blocked behind a running index job.
_QUERY_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cg-query")


async def _run_in_indexer[T](
    fn: Callable[..., T], /, *args: object, **kwargs: object
) -> T:
    """Run ``fn(*args, **kwargs)`` in the dedicated single-thread indexer executor."""
    loop = asyncio.get_running_loop()
    call = partial(fn, *args, **kwargs) if kwargs else partial(fn, *args)
    return await loop.run_in_executor(_INDEXER_EXECUTOR, call)


async def _run_in_query[T](
    fn: Callable[..., T], /, *args: object, **kwargs: object
) -> T:
    """Run ``fn(*args, **kwargs)`` in the query executor (non-blocking vs indexer)."""
    loop = asyncio.get_running_loop()
    call = partial(fn, *args, **kwargs) if kwargs else partial(fn, *args)
    return await loop.run_in_executor(_QUERY_EXECUTOR, call)


# Progress callback: (phase, progress_0_to_1, message) → None
ProgressCallback = Callable[[str, float, str], None]


def _noop_progress(_phase: str, _progress: float, _msg: str) -> None:
    pass


@dataclass(frozen=True, slots=True)
class ReindexStats:
    node_count: int
    edge_count: int
    file_count: int
    error_count: int
    errors: list[str]
    changed_files: int = 0
    deleted_files: int = 0


@dataclass(frozen=True, slots=True)
class WorkspaceOverview:
    node_count: int
    edge_count: int
    file_count: int
    languages: list[str]
    kind_counts: dict[str, int]
    top_files: list[tuple[str, int]]


async def reindex_workspace(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    root_path: str,
    languages: list[str] | None = None,
    incremental: bool = False,
    progress_cb: ProgressCallback | None = None,
) -> ReindexStats:
    """Re-parse ``root_path`` and update the workspace's stored graph.

    With ``incremental=False`` (default) this is a full rebuild: existing
    nodes/edges/state are deleted, then the freshly parsed graph is inserted.

    With ``incremental=True`` only files whose content hash changed (plus any
    deleted files) are re-parsed; stable symbols keep their node ids so
    cross-file edges pointing *into* them survive. See
    :func:`_reindex_incremental`.
    """
    report = progress_cb or _noop_progress
    registry = build_registry(languages)
    if incremental:
        return await _reindex_incremental(
            db,
            workspace_id=workspace_id,
            root_path=root_path,
            registry=registry,
            progress_cb=report,
        )
    report("parsing", 0.0, "Scanning files…")
    index: WorkspaceIndex = await _run_in_indexer(
        index_workspace, root_path, registry=registry
    )
    report(
        "parsing", 0.3, f"Parsed {len(index.files)} files, {len(index.nodes)} symbols"
    )

    report("saving", 0.35, "Saving graph to database…")
    await db.execute(
        sa_delete(CodeEdge).where(col(CodeEdge.workspace_id) == workspace_id)
    )
    await db.execute(
        sa_delete(CodeNode).where(col(CodeNode.workspace_id) == workspace_id)
    )
    await db.execute(
        sa_delete(CodeIndexState).where(
            col(CodeIndexState.workspace_id) == workspace_id
        )
    )

    key_to_id: dict[str, UUID] = {}
    node_rows: list[CodeNode] = []
    for node in index.nodes:
        node_id = uuid7()
        key_to_id[node.key] = node_id
        node_rows.append(
            CodeNode(
                id=node_id,
                workspace_id=workspace_id,
                kind=node.kind,
                name=node.name,
                qualified_name=node.qualified_name,
                file_path=node.file_path,
                language=node.language,
                line_start=node.line_start,
                line_end=node.line_end,
                signature=node.signature,
                docstring=node.docstring,
            )
        )
    db.add_all(node_rows)

    edge_rows: list[CodeEdge] = []
    for edge in index.edges:
        src_id = key_to_id.get(edge.src_key)
        dst_id = key_to_id.get(edge.dst_key)
        if src_id is None or dst_id is None:
            continue
        edge_rows.append(
            CodeEdge(
                workspace_id=workspace_id,
                src_id=src_id,
                dst_id=dst_id,
                kind=edge.kind,
                file_path=edge.file_path,
                line=edge.line,
            )
        )
    db.add_all(edge_rows)

    db.add_all(
        [
            CodeIndexState(
                workspace_id=workspace_id,
                file_path=f.file_path,
                language=f.language,
                content_hash=f.content_hash,
                node_count=f.node_count,
                edge_count=f.edge_count,
            )
            for f in index.files
        ]
    )
    await db.flush()

    await _persist_unresolved_imports(
        db,
        workspace_id=workspace_id,
        unresolved_imports=index.unresolved_imports,
        key_to_id=key_to_id,
    )

    await db.commit()
    report("saving", 0.5, f"Saved {len(node_rows)} nodes, {len(edge_rows)} edges")

    # Rebuild full-text search index (runs in indexer thread, separate sqlite conn).
    await _rebuild_fts(workspace_id=workspace_id, index=index, key_to_id=key_to_id)
    report("saving", 1.0, "Index saved")

    logger.info(
        "code_graph reindex workspace={} files={} nodes={} edges={} errors={}",
        workspace_id,
        len(index.files),
        len(node_rows),
        len(edge_rows),
        len(index.errors),
    )
    return ReindexStats(
        node_count=len(node_rows),
        edge_count=len(edge_rows),
        file_count=len(index.files),
        error_count=len(index.errors),
        errors=index.errors[:_MAX_REPORTED_ERRORS],
    )


async def _persist_unresolved_imports(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    unresolved_imports: list[UnresolvedImport],
    key_to_id: dict[str, UUID],
    affected_files: set[str] | None = None,
) -> None:
    """Record import edges that didn't resolve within this workspace as
    candidate cross-repo references, scoped to every project this workspace
    belongs to. No-ops for a standalone (non-project) workspace.

    Only replaces rows with ``method IS NULL`` (never touched by a
    resolution pass) — rows a resolver has already stamped are left alone so
    this hot reindex path never races with/undoes a resolution pass. On a
    full reindex every file was just reprocessed, so the whole workspace's
    untouched rows are replaced; on an incremental reindex only
    ``affected_files`` (changed + deleted) were reprocessed, so the replace
    is scoped to those files — a deleted file's rows are dropped and never
    reinserted since it no longer appears in ``unresolved_imports``.
    """
    from app.services.coding_project_service import get_projects_for_workspace

    project_ids = await get_projects_for_workspace(db, workspace_id)
    if not project_ids:
        return

    for project_id in project_ids:
        delete_stmt = sa_delete(CrossRepoEdge).where(
            col(CrossRepoEdge.project_id) == project_id,
            col(CrossRepoEdge.src_workspace_id) == workspace_id,
            col(CrossRepoEdge.method).is_(None),
        )
        if affected_files is not None:
            delete_stmt = delete_stmt.where(
                col(CrossRepoEdge.src_file_path).in_(list(affected_files))
            )
        await db.execute(delete_stmt)

        if unresolved_imports:
            db.add_all(
                [
                    CrossRepoEdge(
                        project_id=project_id,
                        src_workspace_id=workspace_id,
                        src_node_id=key_to_id.get(u.src_key),
                        src_file_path=u.file_path,
                        src_line=u.line,
                        raw_reference=u.module_path,
                        dst_name_hint=u.dst_name_hint,
                        kind=EDGE_IMPORTS,
                    )
                    for u in unresolved_imports
                ]
            )


async def _reindex_incremental(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    root_path: str,
    registry: ParserRegistry,
    progress_cb: ProgressCallback = _noop_progress,
) -> ReindexStats:
    """Re-parse only files whose content hash changed since the last index.

    Stable symbols (matched by ``file_path + kind + qualified_name``) keep
    their existing node id, so cross-file edges pointing *into* them survive.
    Symbols that vanished — and every node of a deleted file — are removed
    along with any edge that references them.
    """
    progress_cb("parsing", 0.0, "Checking for changes…")
    current = await _run_in_indexer(hash_workspace_files, root_path, registry=registry)
    stored_states = (
        await db.exec(
            select(CodeIndexState).where(CodeIndexState.workspace_id == workspace_id)
        )
    ).all()
    stored = {s.file_path: s.content_hash for s in stored_states}

    changed = sorted(f for f, h in current.items() if stored.get(f) != h)
    deleted = sorted(f for f in stored if f not in current)
    affected = set(changed) | set(deleted)

    if not affected:
        counts = await get_index_status(db, workspace_id=workspace_id)
        return ReindexStats(
            node_count=counts["nodes"],
            edge_count=counts["edges"],
            file_count=counts["files"],
            error_count=0,
            errors=[],
        )

    progress_cb("parsing", 0.1, f"{len(changed)} changed, {len(deleted)} deleted")
    existing_nodes = (
        await db.exec(select(CodeNode).where(CodeNode.workspace_id == workspace_id))
    ).all()
    # Unchanged files' nodes act as resolution targets for cross-file edges.
    existing_defs = [
        ExistingDef(key=str(n.id), name=n.name, kind=n.kind)
        for n in existing_nodes
        if n.file_path not in affected
    ]

    index = await _run_in_indexer(
        index_files,
        root_path,
        changed,
        registry=registry,
        existing_defs=existing_defs,
    )

    # ── Reconcile nodes of changed files, preserving ids for stable symbols ──
    rows_by_sig: dict[tuple[str, str, str], CodeNode] = {
        (n.file_path, n.kind, n.qualified_name): n
        for n in existing_nodes
        if n.file_path in changed
    }
    key_to_id: dict[str, UUID] = {}
    reused_ids: set[UUID] = set()
    for node in index.nodes:
        sig = (node.file_path, node.kind, node.qualified_name)
        existing = rows_by_sig.get(sig)
        if existing is not None and existing.id not in reused_ids:
            existing.name = node.name
            existing.language = node.language
            existing.line_start = node.line_start
            existing.line_end = node.line_end
            existing.signature = node.signature
            existing.docstring = node.docstring
            node_id = existing.id
            reused_ids.add(node_id)
        else:
            node_id = uuid7()
            db.add(
                CodeNode(
                    id=node_id,
                    workspace_id=workspace_id,
                    kind=node.kind,
                    name=node.name,
                    qualified_name=node.qualified_name,
                    file_path=node.file_path,
                    language=node.language,
                    line_start=node.line_start,
                    line_end=node.line_end,
                    signature=node.signature,
                    docstring=node.docstring,
                )
            )
        key_to_id[node.key] = node_id

    # Symbols that disappeared from changed files, plus all nodes of deleted
    # files, get removed (and their incoming/outgoing edges below).
    removed_ids: set[UUID] = {
        row.id for row in rows_by_sig.values() if row.id not in reused_ids
    }
    removed_ids |= {n.id for n in existing_nodes if n.file_path in deleted}

    # Drop outgoing edges from affected files and every edge touching a removed
    # node (covers incoming edges from unchanged files to vanished symbols).
    await db.execute(
        sa_delete(CodeEdge).where(
            col(CodeEdge.workspace_id) == workspace_id,
            col(CodeEdge.file_path).in_(list(affected)),
        )
    )
    if removed_ids:
        rid = list(removed_ids)
        await db.execute(
            sa_delete(CodeEdge).where(
                col(CodeEdge.workspace_id) == workspace_id,
                or_(col(CodeEdge.src_id).in_(rid), col(CodeEdge.dst_id).in_(rid)),
            )
        )
    # Persist node inserts/updates and edge deletes before adding new edges and
    # deleting removed nodes — keeps foreign keys satisfied at every step.
    await db.flush()

    edge_rows: list[CodeEdge] = []
    for edge in index.edges:
        src_id = key_to_id.get(edge.src_key)
        if src_id is None:
            continue
        dst_id = _resolve_incremental_dst(edge.dst_key, key_to_id)
        if dst_id is None or dst_id in removed_ids:
            continue
        edge_rows.append(
            CodeEdge(
                workspace_id=workspace_id,
                src_id=src_id,
                dst_id=dst_id,
                kind=edge.kind,
                file_path=edge.file_path,
                line=edge.line,
            )
        )
    db.add_all(edge_rows)

    if removed_ids:
        await db.execute(
            sa_delete(CodeNode).where(
                col(CodeNode.workspace_id) == workspace_id,
                col(CodeNode.id).in_(list(removed_ids)),
            )
        )

    # Refresh per-file index state for changed files; drop it for deleted ones.
    await db.execute(
        sa_delete(CodeIndexState).where(
            col(CodeIndexState.workspace_id) == workspace_id,
            col(CodeIndexState.file_path).in_(list(affected)),
        )
    )
    db.add_all(
        [
            CodeIndexState(
                workspace_id=workspace_id,
                file_path=f.file_path,
                language=f.language,
                content_hash=f.content_hash,
                node_count=f.node_count,
                edge_count=f.edge_count,
            )
            for f in index.files
        ]
    )

    await _persist_unresolved_imports(
        db,
        workspace_id=workspace_id,
        unresolved_imports=index.unresolved_imports,
        key_to_id=key_to_id,
        affected_files=affected,
    )

    await db.commit()
    progress_cb("saving", 0.5, "Graph saved")

    # Update FTS index for changed/removed nodes.
    await _update_fts(
        workspace_id=workspace_id,
        index=index,
        key_to_id=key_to_id,
        removed_ids=removed_ids,
    )
    progress_cb("saving", 1.0, "Index saved")

    counts = await get_index_status(db, workspace_id=workspace_id)
    logger.info(
        "code_graph incremental workspace={} changed={} deleted={} nodes={} edges={} errors={}",
        workspace_id,
        len(changed),
        len(deleted),
        counts["nodes"],
        counts["edges"],
        len(index.errors),
    )
    return ReindexStats(
        node_count=counts["nodes"],
        edge_count=counts["edges"],
        file_count=counts["files"],
        error_count=len(index.errors),
        errors=index.errors[:_MAX_REPORTED_ERRORS],
        changed_files=len(changed),
        deleted_files=len(deleted),
    )


def _resolve_incremental_dst(dst_key: str, key_to_id: dict[str, UUID]) -> UUID | None:
    """Map an indexer edge destination key to a node id.

    ``dst_key`` is either a re-parsed node's key (in ``key_to_id``) or the
    ``str(uuid)`` of an unchanged node passed in as an ``ExistingDef``.
    """
    mapped = key_to_id.get(dst_key)
    if mapped is not None:
        return mapped
    try:
        return UUID(dst_key)
    except (ValueError, AttributeError):
        return None


async def _rebuild_fts(
    *,
    workspace_id: UUID,
    index: WorkspaceIndex,
    key_to_id: dict[str, UUID],
) -> None:
    """Rebuild the FTS5 index for a workspace after a full reindex."""
    db_path = current_sqlite_path()
    if db_path is None:
        return
    rows: list[tuple[str, str, str]] = [
        (str(key_to_id[node.key]), node.name, node.qualified_name)
        for node in index.nodes
        if node.key in key_to_id
    ]
    try:
        await _run_in_indexer(
            fts.rebuild_workspace_fts, db_path, str(workspace_id), rows
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("code_graph fts rebuild failed err={}", exc)


async def _update_fts(
    *,
    workspace_id: UUID,
    index: WorkspaceIndex,
    key_to_id: dict[str, UUID],
    removed_ids: set[UUID],
) -> None:
    """Incrementally update the FTS5 index after an incremental reindex."""
    db_path = current_sqlite_path()
    if db_path is None:
        return
    upserts: list[tuple[str, str, str]] = [
        (str(key_to_id[node.key]), node.name, node.qualified_name)
        for node in index.nodes
        if node.key in key_to_id
    ]
    removed = [str(nid) for nid in removed_ids]
    try:
        await _run_in_indexer(
            fts.update_workspace_fts, db_path, str(workspace_id), upserts, removed
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("code_graph fts update failed err={}", exc)


async def get_index_status(db: AsyncSession, *, workspace_id: UUID) -> dict[str, int]:
    """Return basic counts for a workspace's stored graph."""
    files = (
        await db.exec(
            select(CodeIndexState).where(CodeIndexState.workspace_id == workspace_id)
        )
    ).all()
    nodes = (
        await db.exec(select(CodeNode.id).where(CodeNode.workspace_id == workspace_id))
    ).all()
    edges = (
        await db.exec(select(CodeEdge.id).where(CodeEdge.workspace_id == workspace_id))
    ).all()
    return {
        "files": len(files),
        "nodes": len(nodes),
        "edges": len(edges),
    }


async def search_nodes(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[CodeNode]:
    """Search the graph for symbols matching ``query`` (lexical, FTS5-backed)."""
    return await _lexical_search(
        db, workspace_id=workspace_id, query=query, kind=kind, limit=limit
    )


async def _lexical_search(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None,
    limit: int,
) -> list[CodeNode]:
    # Try FTS5 first — O(log N) token lookup instead of LIKE '%q%' full scan.
    db_path = current_sqlite_path()
    if db_path is not None:
        try:
            fts_ids = await _run_in_query(
                fts.search_fts, db_path, str(workspace_id), query, limit
            )
        except Exception:  # noqa: BLE001
            fts_ids = []
        if fts_ids:
            stmt = select(CodeNode).where(
                CodeNode.workspace_id == workspace_id,
                col(CodeNode.id).in_([UUID(nid) for nid in fts_ids]),
            )
            if kind:
                stmt = stmt.where(CodeNode.kind == kind)
            nodes = list((await db.exec(stmt)).all())
            # Preserve FTS rank order
            id_order = {UUID(nid): i for i, nid in enumerate(fts_ids)}
            nodes.sort(key=lambda n: id_order.get(n.id, limit))
            return nodes[:limit]

    # Fallback: ILIKE substring search (no FTS table yet, or in-memory DB)
    pattern = f"%{query}%"
    stmt = select(CodeNode).where(
        CodeNode.workspace_id == workspace_id,
        or_(
            col(CodeNode.name).ilike(pattern),
            col(CodeNode.qualified_name).ilike(pattern),
        ),
    )
    if kind:
        stmt = stmt.where(CodeNode.kind == kind)
    stmt = stmt.limit(limit)
    return list((await db.exec(stmt)).all())


async def get_neighbors(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    node_id: UUID,
    direction: str = "out",
    edge_kind: str | None = None,
) -> list[tuple[str, CodeNode]]:
    """Return ``(edge_kind, node)`` pairs adjacent to ``node_id`` (single hop)."""
    results: list[tuple[str, CodeNode]] = []
    if direction in {"out", "both"}:
        results.extend(
            await _adjacent(
                db,
                workspace_id=workspace_id,
                node_id=node_id,
                edge_kind=edge_kind,
                outgoing=True,
            )
        )
    if direction in {"in", "both"}:
        results.extend(
            await _adjacent(
                db,
                workspace_id=workspace_id,
                node_id=node_id,
                edge_kind=edge_kind,
                outgoing=False,
            )
        )
    return results


async def _adjacent(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    node_id: UUID,
    edge_kind: str | None,
    outgoing: bool,
) -> list[tuple[str, CodeNode]]:
    """Fetch neighbors in a single JOIN — one DB roundtrip instead of two."""
    if outgoing:
        stmt = (
            select(CodeEdge.kind, CodeNode)
            .join(CodeNode, col(CodeEdge.dst_id) == col(CodeNode.id))
            .where(
                CodeEdge.workspace_id == workspace_id,
                CodeEdge.src_id == node_id,
            )
        )
    else:
        stmt = (
            select(CodeEdge.kind, CodeNode)
            .join(CodeNode, col(CodeEdge.src_id) == col(CodeNode.id))
            .where(
                CodeEdge.workspace_id == workspace_id,
                CodeEdge.dst_id == node_id,
            )
        )
    if edge_kind:
        stmt = stmt.where(CodeEdge.kind == edge_kind)
    rows = (await db.exec(stmt)).all()
    return [(ek, node) for ek, node in rows]


async def resolve_workspace_id(db: AsyncSession, *, path: str) -> UUID | None:
    """Map a filesystem path to its registered coding-workspace id, if any."""
    resolved = str(Path(path).expanduser().resolve())
    return (
        await db.exec(
            select(CodingWorkspace.id).where(CodingWorkspace.path == resolved)
        )
    ).first()


async def find_nodes_by_name(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
    limit: int = 10,
) -> list[CodeNode]:
    """Exact lookup by symbol ``name`` or fully ``qualified_name``."""
    stmt = (
        select(CodeNode)
        .where(
            CodeNode.workspace_id == workspace_id,
            or_(CodeNode.name == name, CodeNode.qualified_name == name),
        )
        .limit(limit)
    )
    return list((await db.exec(stmt)).all())


async def get_node(
    db: AsyncSession, *, workspace_id: UUID, node_id: UUID
) -> CodeNode | None:
    """Fetch a single node scoped to its workspace."""
    return (
        await db.exec(
            select(CodeNode).where(
                CodeNode.workspace_id == workspace_id, CodeNode.id == node_id
            )
        )
    ).first()


async def get_overview(
    db: AsyncSession, *, workspace_id: UUID, top_files: int = 10
) -> WorkspaceOverview:
    """Aggregate counts, languages, and the densest files for a workspace."""
    files = (
        await db.exec(
            select(CodeIndexState).where(CodeIndexState.workspace_id == workspace_id)
        )
    ).all()
    kinds = (
        await db.exec(
            select(CodeNode.kind).where(CodeNode.workspace_id == workspace_id)
        )
    ).all()
    # Use COUNT(*) instead of fetching all edge ids — avoids loading thousands of
    # rows into memory just to count them.
    edge_count_result = (
        await db.exec(
            select(sa_func.count()).where(CodeEdge.workspace_id == workspace_id)
        )
    ).one()
    edge_count = edge_count_result or 0

    languages = sorted({f.language for f in files if f.language})
    ranked = sorted(files, key=lambda f: f.node_count, reverse=True)[:top_files]
    return WorkspaceOverview(
        node_count=len(kinds),
        edge_count=edge_count,
        file_count=len(files),
        languages=languages,
        kind_counts=dict(Counter(kinds)),
        top_files=[(f.file_path, f.node_count) for f in ranked],
    )


# ---------------------------------------------------------------------------
# P4: Find all references to a symbol
# ---------------------------------------------------------------------------

# Edge kinds that represent a "usage" of the target symbol.
_REFERENCE_EDGE_KINDS = frozenset(
    {"calls", "references", "imports", "inherits", "implements", "decorated_by"}
)


async def find_references(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    node_id: UUID,
    limit: int = 50,
) -> list[tuple[str, CodeNode, int | None]]:
    """Find all locations that reference ``node_id``.

    Returns ``(edge_kind, source_node, line)`` tuples ordered by file path then
    line number. ``line`` is the edge's originating line (if available).
    """
    stmt = (
        select(CodeEdge.kind, CodeNode, CodeEdge.line)
        .join(CodeNode, col(CodeEdge.src_id) == col(CodeNode.id))
        .where(
            CodeEdge.workspace_id == workspace_id,
            CodeEdge.dst_id == node_id,
            col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
        )
        .order_by(CodeNode.file_path, CodeEdge.line)
        .limit(limit)
    )
    rows = (await db.exec(stmt)).all()
    return [(ek, node, line) for ek, node, line in rows]


# ---------------------------------------------------------------------------
# P5: PageRank-inspired context budget repo map
# ---------------------------------------------------------------------------


async def get_ranked_symbols(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    budget: int = 30,
) -> list[tuple[CodeNode, int]]:
    """Return the top ``budget`` symbols ranked by in-degree (usage count).

    A simple approximation of PageRank: symbols referenced/called more often are
    more important entry points for understanding the codebase. Returns
    ``(node, reference_count)`` ordered by descending count.
    """
    stmt = (
        select(CodeNode, sa_func.count(CodeEdge.id).label("ref_count"))
        .join(CodeNode, col(CodeEdge.dst_id) == col(CodeNode.id))
        .where(
            CodeEdge.workspace_id == workspace_id,
            col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
            # Exclude file nodes — they inflate counts via "contains" edges
            CodeNode.kind != "file",
        )
        .group_by(CodeNode.id)
        .order_by(sa_func.count(CodeEdge.id).desc())
        .limit(budget)
    )
    rows = (await db.exec(stmt)).all()
    return [(node, count) for node, count in rows]


# ---------------------------------------------------------------------------
# P6: Shortest path between two symbols
# ---------------------------------------------------------------------------


async def find_shortest_path(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    src_id: UUID,
    dst_id: UUID,
    max_hops: int = 6,
) -> list[tuple[CodeNode, str, CodeNode]] | None:
    """BFS shortest path from ``src_id`` to ``dst_id`` in the call/dependency graph.

    Returns a list of ``(from_node, edge_kind, to_node)`` hops, or ``None`` if
    no path exists within ``max_hops``. Only follows ``calls``, ``imports``,
    ``inherits``, ``implements``, and ``references`` edges (both directions).
    """
    if src_id == dst_id:
        return []

    # BFS in Python over the DB — acceptable for max_hops ≤ 6 and typical
    # workspace sizes (< 50k nodes). We load adjacency lazily per frontier.
    visited: dict[UUID, tuple[UUID | None, str | None, bool]] = {
        src_id: (None, None, True)
    }  # node_id -> (prev_id, edge_kind, is_forward)
    frontier: list[UUID] = [src_id]

    for _depth in range(max_hops):
        if not frontier:
            break
        # Batch-fetch all edges from/to the current frontier.
        out_stmt = select(CodeEdge.src_id, CodeEdge.dst_id, CodeEdge.kind).where(
            CodeEdge.workspace_id == workspace_id,
            col(CodeEdge.src_id).in_(frontier),
            col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
        )
        in_stmt = select(CodeEdge.src_id, CodeEdge.dst_id, CodeEdge.kind).where(
            CodeEdge.workspace_id == workspace_id,
            col(CodeEdge.dst_id).in_(frontier),
            col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
        )
        out_rows = (await db.exec(out_stmt)).all()
        in_rows = (await db.exec(in_stmt)).all()

        next_frontier: list[UUID] = []
        for src, dst, kind in out_rows:
            if dst not in visited:
                visited[dst] = (src, kind, True)
                next_frontier.append(dst)
                if dst == dst_id:
                    return await _reconstruct_path(db, workspace_id, visited, dst_id)
        for src, dst, kind in in_rows:
            if src not in visited:
                visited[src] = (dst, kind, False)
                next_frontier.append(src)
                if src == dst_id:
                    return await _reconstruct_path(db, workspace_id, visited, dst_id)
        frontier = next_frontier

    return None  # No path within max_hops


async def _reconstruct_path(
    db: AsyncSession,
    workspace_id: UUID,
    visited: dict[UUID, tuple[UUID | None, str | None, bool]],
    target_id: UUID,
) -> list[tuple[CodeNode, str, CodeNode]]:
    """Walk the BFS parent map back to src and fetch node objects."""
    # Collect the id sequence
    path_ids: list[UUID] = []
    current = target_id
    while current is not None:
        path_ids.append(current)
        prev, _, _ = visited[current]
        current = prev
    path_ids.reverse()

    # Fetch all nodes in one query
    nodes_stmt = select(CodeNode).where(
        CodeNode.workspace_id == workspace_id,
        col(CodeNode.id).in_(path_ids),
    )
    all_nodes = list((await db.exec(nodes_stmt)).all())
    node_map = {n.id: n for n in all_nodes}

    # Build hop list
    hops: list[tuple[CodeNode, str, CodeNode]] = []
    for i in range(1, len(path_ids)):
        nid = path_ids[i]
        prev_id, edge_kind, is_forward = visited[nid]
        if prev_id is None or edge_kind is None:
            continue
        from_node = node_map.get(prev_id if is_forward else nid)
        to_node = node_map.get(nid if is_forward else prev_id)
        if from_node and to_node:
            hops.append((from_node, edge_kind, to_node))
    return hops


async def search_across_workspaces(
    db: AsyncSession,
    *,
    workspace_paths: list[str],
    query: str,
    kind: str | None = None,
    limit_per_workspace: int = 10,
) -> list[tuple[str, CodeNode]]:
    """Fan-out search across multiple workspaces and return merged results.

    Returns ``(workspace_path, CodeNode)`` tuples ordered by workspace order.
    Results from each workspace are capped at ``limit_per_workspace``.
    """
    results: list[tuple[str, CodeNode]] = []
    coros = []
    valid_paths: list[str] = []
    for path in workspace_paths:
        ws_id = await resolve_workspace_id(db, path=path)
        if ws_id is None:
            continue
        coros.append(
            search_nodes(db, workspace_id=ws_id, query=query, kind=kind, limit=limit_per_workspace)
        )
        valid_paths.append(path)

    if not coros:
        return results

    per_workspace = await asyncio.gather(*coros)
    for path, nodes in zip(valid_paths, per_workspace):
        for node in nodes:
            results.append((path, node))
    return results
