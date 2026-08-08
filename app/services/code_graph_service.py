"""Database orchestration for the code knowledge graph.

Persists the in-memory :class:`WorkspaceIndex` produced by the parser pipeline
and exposes read helpers used by agent tools and the API. Parsing runs in a
worker thread (CPU-bound) while all database work stays async.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import asyncio
import json
from uuid import UUID, uuid7

from loguru import logger
from sqlalchemy import (
    case as sa_case,
    delete as sa_delete,
    func as sa_func,
    insert as sa_insert,
)
from sqlmodel import SQLModel, col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import current_sqlite_path, sqlite_write_guard
from app.models.chat import CodingProjectWorkspace, CodingWorkspace, _utcnow
from app.models.code_graph import (
    CodeAmbiguousEdge,
    CodeEdge,
    CodeIndexState,
    CodeNode,
    CrossRepoEdge,
)
from app.services.code_graph import fts_store as fts
from app.services.code_graph.indexer import (
    ExistingDef,
    UnresolvedReference,
    WorkspaceIndex,
    hash_workspace_files,
    index_files,
)
from app.services.code_graph.manifest import (
    is_likely_external,
    read_declared_dependencies,
)
from app.services.code_graph.parsers.registry import ParserRegistry, build_registry
from app.services.codeindex.reconcile import plan_reconciliation

# Cap how many errors we keep on the stats payload.
_MAX_REPORTED_ERRORS = 20

# Rows per Core executemany() batch during reindex saves, with an
# ``asyncio.sleep(0)`` between batches. A full reindex of a large repo can
# generate tens of thousands of node/edge rows; inserting them as one
# ORM add_all()+flush() previously ran that many object constructions plus
# unit-of-work bookkeeping as one uninterrupted synchronous stretch, freezing
# every other coroutine (including unrelated GET /history reads) for the
# whole save phase. Bulk Core inserts skip the ORM identity-map/dirty-tracking
# overhead entirely, and yielding between batches lets other requests get
# scheduler turns — WAL mode lets reads proceed against the last-committed
# snapshot even while this write transaction is still open.
_REINDEX_BATCH_SIZE = 2000


async def _bulk_insert_chunked(
    db: AsyncSession,
    model: type[SQLModel],
    rows: list[dict],
    *,
    batch_size: int = _REINDEX_BATCH_SIZE,
) -> None:
    """Insert ``rows`` (plain dicts) into ``model``'s table via Core executemany,
    yielding the event loop between batches.

    Bypasses the ORM identity map/unit-of-work — callers must supply every
    column value explicitly (including ``id`` and ``created_at``), since Core
    inserts do not resolve SQLModel ``default_factory`` values.
    """
    if not rows:
        return
    table = model.__table__  # type: ignore[attr-defined]
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        await db.execute(sa_insert(table), chunk)
        if start + batch_size < len(rows):
            await asyncio.sleep(0)


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


@dataclass(frozen=True, slots=True)
class RankedCodeNode:
    """A code-node candidate with an explainable deterministic rank."""

    node: CodeNode
    score: float
    match_reasons: tuple[str, ...]


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

    With ``incremental=False`` (default) every current source component is
    reprocessed through the same desired-state reconciler while stable symbol
    ids are retained.

    With ``incremental=True`` only files whose content hash changed (plus any
    deleted files) are re-parsed; stable symbols keep their node ids so
    cross-file edges pointing *into* them survive. Both modes delete target
    state owned by source components that disappeared.
    """
    report = progress_cb or _noop_progress
    # Extra structural parsers are reserved for future project rulebooks;
    # the registry is exactly the builtin language set.
    registry = build_registry(languages, extra_parsers=[])
    return await _reconcile_workspace(
        db,
        workspace_id=workspace_id,
        root_path=root_path,
        registry=registry,
        force=not incremental,
        progress_cb=report,
    )


async def _persist_unresolved_references(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    root_path: str,
    unresolved_references: list[UnresolvedReference],
    key_to_id: dict[str, UUID],
    affected_files: set[str] | None = None,
) -> None:
    """Record edges that didn't resolve within this workspace as candidate
    cross-repo references, scoped to every project this workspace belongs
    to. No-ops for a standalone (non-project) workspace.

    Covers unresolved imports plus a handful of other edge kinds precise
    enough to be worth cross-repo resolution — DI-wired fields, base
    classes/interfaces (see ``_CROSS_REPO_CANDIDATE_KINDS`` in the indexer) —
    each carrying its own ``kind`` through to the stored row.

    Only replaces rows with ``method IS NULL`` (never touched by a
    resolution pass) — rows a resolver has already stamped are left alone so
    this hot reindex path never races with/undoes a resolution pass. On a
    full reindex every file was just reprocessed, so the whole workspace's
    untouched rows are replaced; on an incremental reindex only
    ``affected_files`` (changed + deleted) were reprocessed, so the replace
    is scoped to those files — a deleted file's rows are dropped and never
    reinserted since it no longer appears in ``unresolved_references``.

    The indexer has no notion of resolution state — it reports the same
    reference as "unresolved" on every reparse regardless of whether a
    resolver already stamped a row for it. Re-inserting one row per
    ``unresolved_references`` entry unconditionally would duplicate that row
    on every reindex of the file (the ``method IS NOT NULL`` row survives the
    delete above, untouched, so nothing here would remove the duplicate
    either). Skip inserting for any ``(file, raw reference, kind)`` that
    already has a stamped row.

    Each candidate is pre-filtered with ``is_likely_external`` against this
    workspace's own manifest — a reference that's almost certainly to a
    third-party library (the JDK, a well-known package, something this
    repo's own manifest already declares as a dependency) is stored with
    ``status="external"`` instead of ``"unresolved"`` so it never inflates
    the unresolved count or gets attempted by Tier A/B, without losing the
    row outright (still visible/auditable via the edges list).
    """
    from app.services.coding_project_service import get_projects_for_workspace

    project_ids = await get_projects_for_workspace(db, workspace_id)
    if not project_ids:
        return

    declared_dependencies = read_declared_dependencies(root_path)

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

        # A resolver may have already stamped a row for one of these exact
        # call sites (method IS NOT NULL, so the delete above left it alone,
        # by design — see docstring). The indexer re-derives
        # unresolved_references from a fresh parse with no memory of that,
        # so without this check every reindex of an unchanged reference
        # would pile up a duplicate "unresolved" row next to the resolved
        # one. Identity is (file, raw reference, kind) — line number isn't
        # part of it since an edit elsewhere in the file can shift it
        # without changing what the reference points at.
        already_handled: set[tuple[str, str, str]] = set()
        if unresolved_references:
            existing = (
                await db.exec(
                    select(
                        CrossRepoEdge.src_file_path,
                        CrossRepoEdge.raw_reference,
                        CrossRepoEdge.kind,
                    ).where(
                        col(CrossRepoEdge.project_id) == project_id,
                        col(CrossRepoEdge.src_workspace_id) == workspace_id,
                        col(CrossRepoEdge.method).is_not(None),
                    )
                )
            ).all()
            already_handled = set(existing)

        fresh_references = [
            u
            for u in unresolved_references
            if (u.file_path, u.raw_reference, u.kind) not in already_handled
        ]
        if fresh_references:
            db.add_all(
                [
                    CrossRepoEdge(
                        project_id=project_id,
                        src_workspace_id=workspace_id,
                        src_node_id=key_to_id.get(u.src_key),
                        src_file_path=u.file_path,
                        src_line=u.line,
                        raw_reference=u.raw_reference,
                        dst_name_hint=u.dst_name_hint,
                        kind=u.kind,
                        status=(
                            "external"
                            if is_likely_external(
                                u.raw_reference,
                                file_path=u.file_path,
                                declared_dependencies=declared_dependencies,
                            )
                            else "unresolved"
                        ),
                    )
                    for u in fresh_references
                ]
            )


async def _reconcile_workspace(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    root_path: str,
    registry: ParserRegistry,
    force: bool,
    progress_cb: ProgressCallback = _noop_progress,
) -> ReindexStats:
    """Reconcile a keyed source snapshot into graph target state.

    The same path owns both explicit full refreshes and incremental updates.
    Stable symbols (``file_path + kind + qualified_name``) keep their ids;
    missing source components delete their target states. ``force`` reprocesses
    all current components for parser upgrades without discarding identity.
    """
    progress_cb("parsing", 0.0, "Checking for changes…")
    current = await _run_in_indexer(hash_workspace_files, root_path, registry=registry)
    stored_states = (
        await db.exec(
            select(CodeIndexState).where(CodeIndexState.workspace_id == workspace_id)
        )
    ).all()
    stored = {s.file_path: s.content_hash for s in stored_states}

    plan = plan_reconciliation(current, stored, force=force)
    changed = list(plan.reprocess)
    deleted = list(plan.deletes)
    affected = set(plan.affected)

    if plan.is_noop:
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
        ExistingDef(
            key=str(n.id),
            name=n.name,
            kind=n.kind,
            file_path=n.file_path,
            qualified_name=n.qualified_name,
            language=n.language,
        )
        for n in existing_nodes
        if n.file_path not in affected
    ]

    index = await _run_in_indexer(
        index_files,
        root_path,
        changed,
        registry=registry,
        existing_defs=existing_defs,
        known_file_paths=frozenset(current.keys()),
    )

    # ── Reconcile nodes of changed files, preserving ids for stable symbols ──
    # Everything below mutates the graph, so it all runs under the write
    # guard: the reconciliation loop stages dirty ``existing.*`` attributes
    # that flush on the very first ``db.execute()``/autoflush below, not at
    # the point they're assigned.
    async with sqlite_write_guard():
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
        await db.execute(
            sa_delete(CodeAmbiguousEdge).where(
                col(CodeAmbiguousEdge.workspace_id) == workspace_id,
                col(CodeAmbiguousEdge.file_path).in_(list(affected)),
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

        now = _utcnow()
        edge_rows: list[dict] = []
        for edge in index.edges:
            src_id = key_to_id.get(edge.src_key)
            if src_id is None:
                continue
            dst_id = _resolve_incremental_dst(edge.dst_key, key_to_id)
            if dst_id is None or dst_id in removed_ids:
                continue
            edge_rows.append(
                {
                    "id": uuid7(),
                    "workspace_id": workspace_id,
                    "src_id": src_id,
                    "dst_id": dst_id,
                    "kind": edge.kind,
                    "file_path": edge.file_path,
                    "line": edge.line,
                    "created_at": now,
                }
            )
        # Nodes were flushed just above, so their ids already satisfy these
        # edges' FKs — safe to bulk-insert via Core without an ORM flush.
        await _bulk_insert_chunked(db, CodeEdge, edge_rows)

        ambiguous_rows: list[dict] = []
        for ambiguous in index.ambiguous_edges:
            src_id = key_to_id.get(ambiguous.src_key)
            if src_id is None:
                continue
            candidate_ids = {
                candidate_id
                for key in ambiguous.candidate_keys
                if (candidate_id := _resolve_incremental_dst(key, key_to_id))
                is not None
                and candidate_id not in removed_ids
            }
            if len(candidate_ids) < 2:
                continue
            ambiguous_rows.append(
                {
                    "id": uuid7(),
                    "workspace_id": workspace_id,
                    "src_id": src_id,
                    "dst_name": ambiguous.dst_name,
                    "kind": ambiguous.kind,
                    "candidate_node_ids": json.dumps(
                        sorted(str(candidate_id) for candidate_id in candidate_ids)
                    ),
                    "file_path": ambiguous.file_path,
                    "line": ambiguous.line,
                    "created_at": now,
                }
            )
        await _bulk_insert_chunked(db, CodeAmbiguousEdge, ambiguous_rows)

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
        await _bulk_insert_chunked(
            db,
            CodeIndexState,
            [
                {
                    "id": uuid7(),
                    "workspace_id": workspace_id,
                    "file_path": f.file_path,
                    "language": f.language,
                    "content_hash": f.content_hash,
                    "node_count": f.node_count,
                    "edge_count": f.edge_count,
                    "indexed_at": now,
                }
                for f in index.files
            ],
        )

        await _persist_unresolved_references(
            db,
            workspace_id=workspace_id,
            root_path=root_path,
            unresolved_references=index.unresolved_references,
            key_to_id=key_to_id,
            affected_files=affected,
        )

        await db.commit()
        progress_cb("saving", 0.5, "Graph saved")

        # Update FTS index for changed/removed nodes — same guard, since it
        # writes to the same on-disk file as the ORM.
        await _update_fts(
            workspace_id=workspace_id,
            index=index,
            key_to_id=key_to_id,
            removed_ids=removed_ids,
        )
    progress_cb("saving", 1.0, "Index saved")

    counts = await get_index_status(db, workspace_id=workspace_id)
    logger.info(
        "codeindex reconcile workspace={} force={} changed={} deleted={} nodes={} edges={} errors={}",
        workspace_id,
        force,
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
    rows: list[fts.FtsRow] = [
        (
            str(key_to_id[node.key]),
            node.name,
            node.qualified_name,
            node.file_path,
            node.signature or "",
            node.docstring or "",
            node.kind,
            node.language,
        )
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
    upserts: list[fts.FtsRow] = [
        (
            str(key_to_id[node.key]),
            node.name,
            node.qualified_name,
            node.file_path,
            node.signature or "",
            node.docstring or "",
            node.kind,
            node.language,
        )
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
            select(sa_func.count()).where(CodeIndexState.workspace_id == workspace_id)
        )
    ).first() or 0
    nodes = (
        await db.exec(
            select(sa_func.count()).where(CodeNode.workspace_id == workspace_id)
        )
    ).first() or 0
    edges = (
        await db.exec(
            select(sa_func.count()).where(CodeEdge.workspace_id == workspace_id)
        )
    ).first() or 0
    return {
        "files": files,
        "nodes": nodes,
        "edges": edges,
    }


async def requires_project_graph_bootstrap(
    db: AsyncSession, *, project_id: UUID, workspace_id: UUID
) -> bool:
    """Whether this workspace's graph predates its project membership.

    Cross-repo candidates are materialized while indexing and are scoped to
    projects the workspace belongs to at that moment.  Reusing a graph that
    was built before the repo joined a project therefore leaves no candidates
    for unchanged files.  The oldest per-file timestamp is the durable marker:
    a full project-aware build refreshes every file after the membership row
    was created, while an unrelated incremental edit refreshes only a subset.
    """
    joined_at = (
        await db.exec(
            select(CodingProjectWorkspace.created_at).where(
                col(CodingProjectWorkspace.project_id) == project_id,
                col(CodingProjectWorkspace.workspace_id) == workspace_id,
            )
        )
    ).first()
    if joined_at is None:
        return False

    oldest_indexed_at = (
        await db.exec(
            select(sa_func.min(CodeIndexState.indexed_at)).where(
                col(CodeIndexState.workspace_id) == workspace_id
            )
        )
    ).first()
    return oldest_indexed_at is None or oldest_indexed_at < joined_at


# Priority order for graph visualization: structural containers first, then
# callable symbols, then fine-grained variables. This lets the UI cap nodes
# per repo while keeping the most "connection-dense" symbols visible.
_GRAPH_NODE_KIND_PRIORITY: dict[str, int] = {
    "file": 0,
    "module": 0,
    "class": 1,
    "interface": 1,
    "function": 2,
    "method": 3,
    "variable": 4,
}


async def get_workspace_graph_data(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    node_limit: int = 500,
    edge_limit: int = 2000,
) -> tuple[list[CodeNode], list[CodeEdge], int, int]:
    """Return a renderable slice of a workspace's graph.

    Strategy: fetch edges first (capped), then include every node those
    edges reference *plus* the highest-priority standalone nodes up to the
    node limit.  This guarantees every returned edge has both endpoints
    visible — the previous "cap nodes first" approach silently dropped edges
    whenever one endpoint was filtered out.
    """
    total_nodes_result = await db.exec(
        select(sa_func.count()).where(CodeNode.workspace_id == workspace_id)
    )
    total_edges_result = await db.exec(
        select(sa_func.count()).where(CodeEdge.workspace_id == workspace_id)
    )
    total_node_count = total_nodes_result.first() or 0
    total_edge_count = total_edges_result.first() or 0

    # Step 1: fetch edges capped in SQL, ordered by id for stable results.
    edges = list(
        (
            await db.exec(
                select(CodeEdge)
                .where(CodeEdge.workspace_id == workspace_id)
                .order_by(col(CodeEdge.id))
                .limit(edge_limit)
            )
        ).all()
    )

    # Step 2: collect every node id referenced by the edge set.
    edge_node_ids: set[UUID] = set()
    for e in edges:
        edge_node_ids.add(e.src_id)
        edge_node_ids.add(e.dst_id)

    def _priority_key(n: CodeNode) -> tuple[int, str]:
        return (
            _GRAPH_NODE_KIND_PRIORITY.get(n.kind, 5),
            n.qualified_name or n.name,
        )

    # Step 3: nodes referenced by edges must always be included so every
    # edge renders; fetch just those instead of the whole workspace.
    edge_nodes: list[CodeNode] = []
    if edge_node_ids:
        edge_nodes = list(
            (
                await db.exec(
                    select(CodeNode).where(
                        CodeNode.workspace_id == workspace_id,
                        col(CodeNode.id).in_(edge_node_ids),
                    )
                )
            ).all()
        )
        edge_nodes.sort(key=_priority_key)

    # Step 4: top up to the node limit with the highest-priority standalone
    # nodes, ranking in SQL via a CASE mirror of _GRAPH_NODE_KIND_PRIORITY.
    remaining_slots = max(0, node_limit - len(edge_nodes))
    remaining_nodes: list[CodeNode] = []
    if remaining_slots:
        kind_priority = sa_case(
            _GRAPH_NODE_KIND_PRIORITY, value=col(CodeNode.kind), else_=5
        )
        stmt = (
            select(CodeNode)
            .where(CodeNode.workspace_id == workspace_id)
            .order_by(
                kind_priority,
                sa_func.coalesce(CodeNode.qualified_name, CodeNode.name),
            )
            .limit(remaining_slots)
        )
        if edge_node_ids:
            stmt = stmt.where(col(CodeNode.id).notin_(edge_node_ids))
        remaining_nodes = list((await db.exec(stmt)).all())
    nodes = edge_nodes + remaining_nodes

    return nodes, edges, total_node_count, total_edge_count


async def search_nodes(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[CodeNode]:
    """Search the graph using hybrid lexical fields and deterministic ranking."""
    ranked = await search_nodes_ranked(
        db, workspace_id=workspace_id, query=query, kind=kind, limit=limit
    )
    return [item.node for item in ranked]


async def search_nodes_ranked(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None = None,
    language: str | None = None,
    paths: Sequence[str] = (),
    limit: int = 20,
) -> list[RankedCodeNode]:
    """Search indexed symbol names for the human Graph panel.

    This is deliberately not the model-facing graph navigator and does not
    interpret prose.  It finds symbol/name/path fragments so a user can choose
    an exact node; structural traversal starts only after that selection.
    """
    folded = query.strip().casefold()
    if not folded:
        return []
    candidate_limit = max(100, min(1000, limit * 10))
    nodes: list[CodeNode] = []
    db_path = current_sqlite_path()
    if db_path is not None:
        candidate_ids = await _run_in_query(
            fts.search_fts,
            db_path,
            str(workspace_id),
            query,
            candidate_limit,
            kind,
            language,
        )
        parsed_ids: list[UUID] = []
        for value in candidate_ids:
            try:
                parsed_ids.append(UUID(value))
            except ValueError:
                continue
        if parsed_ids:
            nodes = list(
                (
                    await db.exec(
                        select(CodeNode).where(
                            CodeNode.workspace_id == workspace_id,
                            col(CodeNode.id).in_(parsed_ids),
                        )
                    )
                ).all()
            )

    # FTS prefix matching cannot implement arbitrary infix queries (``store``
    # matching ``restore``). Preserve that legacy behavior as a slow fallback,
    # while common exact/prefix/token searches stay on the indexed fast path.
    if not nodes:
        clauses = [
            CodeNode.workspace_id == workspace_id,
            or_(
                sa_func.lower(CodeNode.name).contains(folded),
                sa_func.lower(CodeNode.qualified_name).contains(folded),
                sa_func.lower(CodeNode.file_path).contains(folded),
            ),
        ]
        if kind:
            clauses.append(CodeNode.kind == kind)
        if language:
            clauses.append(CodeNode.language == language)
        nodes = list(
            (
                await db.exec(select(CodeNode).where(*clauses).limit(candidate_limit))
            ).all()
        )
    normalized_paths = tuple(
        value.replace("\\", "/").casefold().strip("/")
        for value in paths
        if value.replace("\\", "/").strip("/")
    )
    if normalized_paths:
        nodes = [
            node
            for node in nodes
            if any(
                node.file_path.casefold() == prefix
                or node.file_path.casefold().startswith(prefix + "/")
                for prefix in normalized_paths
            )
        ]

    def rank(node: CodeNode) -> tuple[float, tuple[str, ...]]:
        name = node.name.casefold()
        qualified = node.qualified_name.casefold()
        if qualified == folded:
            return 120.0, ("exact qualified symbol",)
        if name == folded:
            return 110.0, ("exact symbol name",)
        if name.startswith(folded):
            return 80.0, ("symbol-name prefix",)
        if folded in name:
            return 65.0, ("symbol-name fragment",)
        if folded in qualified:
            return 50.0, ("qualified-symbol fragment",)
        if folded in node.file_path.casefold():
            return 20.0, ("file-path fragment",)
        if node.signature and folded in node.signature.casefold():
            return 15.0, ("signature fragment",)
        return 10.0, ("documentation fragment",)

    ranked = [
        RankedCodeNode(node=node, score=score, match_reasons=reasons)
        for node in nodes
        for score, reasons in (rank(node),)
    ]
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.node.qualified_name,
            item.node.file_path,
            item.node.line_start,
        )
    )
    return ranked[: max(1, min(limit, 100))]


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


async def get_ambiguous_relationships(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    node_id: UUID,
) -> list[tuple[CodeAmbiguousEdge, list[CodeNode]]]:
    """Return unresolved outbound relationships and their candidate nodes."""
    import json

    relationships = list(
        (
            await db.exec(
                select(CodeAmbiguousEdge)
                .where(
                    CodeAmbiguousEdge.workspace_id == workspace_id,
                    CodeAmbiguousEdge.src_id == node_id,
                )
                .order_by(col(CodeAmbiguousEdge.id))
            )
        ).all()
    )
    if not relationships:
        return []

    ids_by_relationship: list[list[UUID]] = []
    all_ids: set[UUID] = set()
    for relationship in relationships:
        parsed_ids: list[UUID] = []
        try:
            raw_ids = json.loads(relationship.candidate_node_ids)
        except (TypeError, ValueError):
            raw_ids = []
        if isinstance(raw_ids, list):
            for raw_id in raw_ids:
                try:
                    candidate_id = UUID(str(raw_id))
                except (TypeError, ValueError):
                    continue
                parsed_ids.append(candidate_id)
                all_ids.add(candidate_id)
        ids_by_relationship.append(parsed_ids)

    nodes_by_id: dict[UUID, CodeNode] = {}
    if all_ids:
        candidates = (
            await db.exec(
                select(CodeNode).where(
                    CodeNode.workspace_id == workspace_id,
                    col(CodeNode.id).in_(all_ids),
                )
            )
        ).all()
        nodes_by_id = {candidate.id: candidate for candidate in candidates}

    return [
        (
            relationship,
            [nodes_by_id[node_id] for node_id in node_ids if node_id in nodes_by_id],
        )
        for relationship, node_ids in zip(
            relationships, ids_by_relationship, strict=True
        )
    ]


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


async def find_file_node(
    db: AsyncSession, *, workspace_id: UUID, file_path: str
) -> CodeNode | None:
    """Look up the file-level ``CodeNode`` for ``file_path`` in a workspace.

    Import edges are attached to the file node rather than to whichever
    class/method textually contains the import statement — callers wanting
    a non-file symbol's imports must redirect to this node first (see
    ``get_neighbors`` callers filtering on ``edge_kind="imports"``).
    """
    return (
        await db.exec(
            select(CodeNode).where(
                CodeNode.workspace_id == workspace_id,
                CodeNode.file_path == file_path,
                CodeNode.kind == "file",
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
    {
        "calls",
        "references",
        "imports",
        "inherits",
        "implements",
        "decorated_by",
        "uses",
        "overrides",
        "reads",
        "writes",
        "throws",
    }
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
    src_workspace_id: UUID,
    src_id: UUID,
    dst_id: UUID,
    max_hops: int = 6,
    project_id: UUID | None = None,
) -> list[tuple[CodeNode, str, CodeNode]] | None:
    """BFS shortest path from ``src_id`` to ``dst_id`` in the call/dependency graph.

    ``src_workspace_id`` must be ``src_id``'s OWN workspace — not necessarily
    the caller's "active"/session workspace. In a multi-repo project, a
    caller that resolved ``src_id`` via a project-wide symbol search (rather
    than assuming it lives in the caller's own workspace) MUST pass that
    resolved workspace here, or the very first BFS iteration queries the
    wrong workspace's edges and silently finds nothing.

    Returns a list of ``(from_node, edge_kind, to_node)`` hops, or ``None`` if
    no path exists within ``max_hops``. Only follows ``calls``, ``imports``,
    ``inherits``, ``implements``, and ``references`` edges (both directions).

    When ``project_id`` is set, the BFS can also hop across resolved
    ``CrossRepoEdge`` rows within that project, allowing paths that span sibling
    repos in the same CodingProject. Once a hop lands in a sibling repo, later
    intra-repo hops are scoped to *that* repo's own edges — each node's home
    workspace is tracked as it's discovered (from the ``CrossRepoEdge`` row for
    cross-repo hops, inherited from its frontier neighbour otherwise) so the
    frontier can legitimately span more than one workspace at once.
    """
    if src_id == dst_id:
        return []

    cross_repo = project_id is not None

    # BFS in Python over the DB — acceptable for max_hops ≤ 6 and typical
    # workspace sizes (< 50k nodes). We load adjacency lazily per frontier.
    visited: dict[UUID, tuple[UUID | None, str | None, bool]] = {
        src_id: (None, None, True)
    }  # node_id -> (prev_id, edge_kind, is_forward)
    node_workspace: dict[UUID, UUID] = {src_id: src_workspace_id}
    frontier: list[UUID] = [src_id]

    for _depth in range(max_hops):
        if not frontier:
            break
        frontier_set = set(frontier)

        # Group by each node's own workspace rather than filtering on the
        # single starting `workspace_id` — once BFS has crossed into a
        # sibling repo the frontier spans >1 workspace, and each group still
        # hits the (workspace_id, src_id/dst_id, kind) index instead of
        # forcing a cross-workspace table scan.
        by_workspace: dict[UUID, list[UUID]] = {}
        for node_id in frontier:
            by_workspace.setdefault(node_workspace[node_id], []).append(node_id)

        out_rows: list[tuple[UUID, UUID, str]] = []
        in_rows: list[tuple[UUID, UUID, str]] = []
        for ws_id, node_ids in by_workspace.items():
            out_stmt = select(CodeEdge.src_id, CodeEdge.dst_id, CodeEdge.kind).where(
                CodeEdge.workspace_id == ws_id,
                col(CodeEdge.src_id).in_(node_ids),
                col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
            )
            in_stmt = select(CodeEdge.src_id, CodeEdge.dst_id, CodeEdge.kind).where(
                CodeEdge.workspace_id == ws_id,
                col(CodeEdge.dst_id).in_(node_ids),
                col(CodeEdge.kind).in_(_REFERENCE_EDGE_KINDS),
            )
            out_rows.extend((await db.exec(out_stmt)).all())
            in_rows.extend((await db.exec(in_stmt)).all())

        next_frontier: list[UUID] = []

        def _visit(
            node_id: UUID, prev_id: UUID, kind: str, forward: bool, ws_id: UUID
        ) -> bool:
            if node_id not in visited:
                visited[node_id] = (prev_id, kind, forward)
                node_workspace[node_id] = ws_id
                next_frontier.append(node_id)
                if node_id == dst_id:
                    return True
            return False

        for src, dst, kind in out_rows:
            if _visit(dst, src, kind, True, node_workspace[src]):
                return await _reconstruct_path(
                    db, src_workspace_id, visited, dst_id, cross_repo=cross_repo
                )
        for src, dst, kind in in_rows:
            if _visit(src, dst, kind, False, node_workspace[dst]):
                return await _reconstruct_path(
                    db, src_workspace_id, visited, dst_id, cross_repo=cross_repo
                )

        if cross_repo:
            cross_stmt = select(
                CrossRepoEdge.src_node_id,
                CrossRepoEdge.src_workspace_id,
                CrossRepoEdge.dst_node_id,
                CrossRepoEdge.dst_workspace_id,
                CrossRepoEdge.kind,
            ).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "resolved",
                col(CrossRepoEdge.src_node_id).is_not(None),
                col(CrossRepoEdge.dst_node_id).is_not(None),
                or_(
                    col(CrossRepoEdge.src_node_id).in_(frontier),
                    col(CrossRepoEdge.dst_node_id).in_(frontier),
                ),
            )
            cross_rows = (await db.exec(cross_stmt)).all()
            for src, src_ws, dst, dst_ws, kind in cross_rows:
                if src in frontier_set and src is not None:
                    if _visit(dst, src, kind, True, dst_ws):
                        return await _reconstruct_path(
                            db, src_workspace_id, visited, dst_id, cross_repo=cross_repo
                        )
                if dst in frontier_set and dst is not None:
                    if _visit(src, dst, kind, False, src_ws):
                        return await _reconstruct_path(
                            db, src_workspace_id, visited, dst_id, cross_repo=cross_repo
                        )

        frontier = next_frontier

    return None  # No path within max_hops


async def _reconstruct_path(
    db: AsyncSession,
    src_workspace_id: UUID,
    visited: dict[UUID, tuple[UUID | None, str | None, bool]],
    target_id: UUID,
    cross_repo: bool = False,
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

    # Fetch all nodes in one query. Paths that span repos must be
    # workspace-unscoped because CodeNode.id is a global uuid7 PK.
    if cross_repo:
        nodes_stmt = select(CodeNode).where(col(CodeNode.id).in_(path_ids))
    else:
        nodes_stmt = select(CodeNode).where(
            CodeNode.workspace_id == src_workspace_id,
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
) -> list[tuple[str, UUID, CodeNode]]:
    """Fan-out search across multiple workspaces and return merged results.

    Returns ``(workspace_path, workspace_id, CodeNode)`` tuples ordered by
    workspace order. Results from each workspace are capped at
    ``limit_per_workspace``. ``workspace_id`` is included (not just the path)
    so callers can run further workspace-scoped queries — e.g. neighbors or
    references — against whichever sibling workspace a match came from.
    """
    results: list[tuple[str, UUID, CodeNode]] = []
    coros = []
    valid_paths: list[str] = []
    valid_ids: list[UUID] = []
    for path in workspace_paths:
        ws_id = await resolve_workspace_id(db, path=path)
        if ws_id is None:
            continue
        coros.append(
            search_nodes(
                db,
                workspace_id=ws_id,
                query=query,
                kind=kind,
                limit=limit_per_workspace,
            )
        )
        valid_paths.append(path)
        valid_ids.append(ws_id)

    if not coros:
        return results

    per_workspace = await asyncio.gather(*coros)
    for path, ws_id, nodes in zip(valid_paths, valid_ids, per_workspace):
        for node in nodes:
            results.append((path, ws_id, node))
    return results


async def get_project_overview(
    db: AsyncSession, *, project_id: UUID
) -> dict[str, WorkspaceOverview]:
    """Aggregate ``WorkspaceOverview`` for every workspace in a project.

    Returns a mapping from workspace path to its overview, in project order.
    """
    from app.services.coding_project_service import get_project_workspaces

    pairs = await get_project_workspaces(db, project_id)
    if not pairs:
        return {}

    coros = [get_overview(db, workspace_id=ws.id) for _, ws in pairs]
    overviews = await asyncio.gather(*coros)
    return {ws.path: overview for (_, ws), overview in zip(pairs, overviews)}
