"""Database orchestration for the code knowledge graph.

Persists the in-memory :class:`WorkspaceIndex` produced by the parser pipeline
and exposes read helpers used by agent tools and the API. Parsing runs in a
worker thread (CPU-bound) while all database work stays async.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import asyncio
from uuid import UUID, uuid7

from loguru import logger
from sqlalchemy import delete as sa_delete
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import current_sqlite_path
from app.core.runtime_settings import CodeGraphSettings, load_runtime_settings
from app.models.chat import CodingWorkspace
from app.models.code_graph import CodeEdge, CodeIndexState, CodeNode
from app.services.code_graph import embeddings as emb
from app.services.code_graph import vector_store as vec
from app.services.code_graph.indexer import (
    ExistingDef,
    WorkspaceIndex,
    hash_workspace_files,
    index_files,
    index_workspace,
)
from app.services.code_graph.parsers.registry import ParserRegistry, build_registry

# Cap how many errors we keep on the stats payload.
_MAX_REPORTED_ERRORS = 20

# Symbol kinds worth embedding for semantic search (skip whole-file nodes).
_EMBEDDABLE_KINDS = frozenset({"module", "class", "function", "method", "interface"})

# Reciprocal-rank-fusion constant — dampens the contribution of lower ranks.
_RRF_K = 60


@dataclass(frozen=True, slots=True)
class ReindexStats:
    node_count: int
    edge_count: int
    file_count: int
    error_count: int
    errors: list[str]
    embedded_count: int = 0
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
) -> ReindexStats:
    """Re-parse ``root_path`` and update the workspace's stored graph.

    With ``incremental=False`` (default) this is a full rebuild: existing
    nodes/edges/state are deleted, then the freshly parsed graph is inserted.

    With ``incremental=True`` only files whose content hash changed (plus any
    deleted files) are re-parsed; stable symbols keep their node ids so
    cross-file edges pointing *into* them survive. See
    :func:`_reindex_incremental`.
    """
    registry = build_registry(languages)
    if incremental:
        return await _reindex_incremental(
            db, workspace_id=workspace_id, root_path=root_path, registry=registry
        )
    index: WorkspaceIndex = await asyncio.to_thread(
        index_workspace, root_path, registry=registry
    )

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

    # Commit the graph before embedding: vectors are written from a separate
    # sqlite connection, so the ORM's write transaction must be released first
    # to avoid a self-inflicted "database is locked". The graph persists even
    # if the (optional) embedding step fails.
    await db.commit()

    embedded_count = await _maybe_index_embeddings(
        workspace_id=workspace_id, index=index, key_to_id=key_to_id
    )

    logger.info(
        "code_graph reindex workspace={} files={} nodes={} edges={} "
        "embedded={} errors={}",
        workspace_id,
        len(index.files),
        len(node_rows),
        len(edge_rows),
        embedded_count,
        len(index.errors),
    )
    return ReindexStats(
        node_count=len(node_rows),
        edge_count=len(edge_rows),
        file_count=len(index.files),
        error_count=len(index.errors),
        errors=index.errors[:_MAX_REPORTED_ERRORS],
        embedded_count=embedded_count,
    )


async def _reindex_incremental(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    root_path: str,
    registry: ParserRegistry,
) -> ReindexStats:
    """Re-parse only files whose content hash changed since the last index.

    Stable symbols (matched by ``file_path + kind + qualified_name``) keep
    their existing node id, so cross-file edges pointing *into* them survive.
    Symbols that vanished — and every node of a deleted file — are removed
    along with any edge that references them.
    """
    current = await asyncio.to_thread(
        hash_workspace_files, root_path, registry=registry
    )
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

    existing_nodes = (
        await db.exec(select(CodeNode).where(CodeNode.workspace_id == workspace_id))
    ).all()
    # Unchanged files' nodes act as resolution targets for cross-file edges.
    existing_defs = [
        ExistingDef(key=str(n.id), name=n.name, kind=n.kind)
        for n in existing_nodes
        if n.file_path not in affected
    ]

    index = await asyncio.to_thread(
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
    embed_targets: list[tuple[str, str]] = []
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
        if node.kind in _EMBEDDABLE_KINDS:
            embed_targets.append(
                (
                    str(node_id),
                    emb.node_embedding_text(
                        kind=node.kind,
                        name=node.name,
                        qualified_name=node.qualified_name,
                        signature=node.signature,
                        docstring=node.docstring,
                    ),
                )
            )

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
    await db.commit()

    embedded_count = await _maybe_update_embeddings(
        workspace_id=workspace_id,
        upserts=embed_targets,
        removed_ids=removed_ids,
    )

    counts = await get_index_status(db, workspace_id=workspace_id)
    logger.info(
        "code_graph incremental workspace={} changed={} deleted={} "
        "nodes={} edges={} embedded={} errors={}",
        workspace_id,
        len(changed),
        len(deleted),
        counts["nodes"],
        counts["edges"],
        embedded_count,
        len(index.errors),
    )
    return ReindexStats(
        node_count=counts["nodes"],
        edge_count=counts["edges"],
        file_count=counts["files"],
        error_count=len(index.errors),
        errors=index.errors[:_MAX_REPORTED_ERRORS],
        embedded_count=embedded_count,
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


async def _maybe_index_embeddings(
    *,
    workspace_id: UUID,
    index: WorkspaceIndex,
    key_to_id: dict[str, UUID],
) -> int:
    """Embed indexed symbols and persist vectors when semantic search is on.

    Returns the number of vectors written. Degrades to ``0`` (lexical-only)
    when semantic search is disabled, the DB is in-memory, or the embedding
    backend is unavailable.
    """
    cfg = load_runtime_settings().code_graph
    if not cfg.semantic_enabled:
        return 0
    db_path = current_sqlite_path()
    if db_path is None:
        return 0

    items: list[tuple[str, str]] = []
    for node in index.nodes:
        if node.kind not in _EMBEDDABLE_KINDS:
            continue
        node_id = key_to_id.get(node.key)
        if node_id is None:
            continue
        text = emb.node_embedding_text(
            kind=node.kind,
            name=node.name,
            qualified_name=node.qualified_name,
            signature=node.signature,
            docstring=node.docstring,
        )
        items.append((str(node_id), text))

    if not items:
        # Still clear any stale vectors for a now-empty workspace.
        try:
            await asyncio.to_thread(_clear_vectors, db_path, str(workspace_id))
        except vec.VectorStoreUnavailable as exc:
            logger.warning("code_graph vec clear failed err={}", exc)
        return 0

    try:
        return await asyncio.to_thread(
            _embed_and_store, db_path, str(workspace_id), cfg, items
        )
    except (emb.EmbeddingUnavailable, vec.VectorStoreUnavailable) as exc:
        logger.warning("code_graph embedding skipped err={}", exc)
        return 0


def _embed_and_store(
    db_path: str,
    workspace_id: str,
    cfg: CodeGraphSettings,
    items: list[tuple[str, str]],
) -> int:
    """Embed ``items`` and replace the workspace's stored vectors (sync)."""
    embedder = emb.get_embedder(cfg.embedding_model, cfg.embedding_dim)
    vectors = embedder.embed([text for _, text in items])
    rows = [
        (node_id, vector) for (node_id, _), vector in zip(items, vectors, strict=False)
    ]
    with vec.open_connection(db_path) as conn:
        return vec.replace_workspace_vectors(
            conn, workspace_id=workspace_id, dim=cfg.embedding_dim, rows=rows
        )


def _clear_vectors(db_path: str, workspace_id: str) -> None:
    with vec.open_connection(db_path) as conn:
        vec.delete_workspace(conn, workspace_id)
        conn.commit()


async def _maybe_update_embeddings(
    *,
    workspace_id: UUID,
    upserts: list[tuple[str, str]],
    removed_ids: set[UUID],
) -> int:
    """Refresh vectors for changed symbols and drop them for removed ones.

    Returns the number of vectors (re)written. No-op (returns ``0``) when
    semantic search is disabled, the DB is in-memory, or the embedding backend
    is unavailable.
    """
    cfg = load_runtime_settings().code_graph
    if not cfg.semantic_enabled:
        return 0
    db_path = current_sqlite_path()
    if db_path is None:
        return 0
    if not upserts and not removed_ids:
        return 0
    try:
        return await asyncio.to_thread(
            _embed_and_upsert,
            db_path,
            str(workspace_id),
            cfg,
            upserts,
            [str(node_id) for node_id in removed_ids],
        )
    except (emb.EmbeddingUnavailable, vec.VectorStoreUnavailable) as exc:
        logger.warning("code_graph incremental embedding skipped err={}", exc)
        return 0


def _embed_and_upsert(
    db_path: str,
    workspace_id: str,
    cfg: CodeGraphSettings,
    upserts: list[tuple[str, str]],
    removed_node_ids: list[str],
) -> int:
    """Delete removed vectors and (re)embed changed symbols (sync)."""
    with vec.open_connection(db_path) as conn:
        vec.ensure_table(conn, cfg.embedding_dim)
        if removed_node_ids:
            vec.delete_nodes(conn, removed_node_ids)
        written = 0
        if upserts:
            embedder = emb.get_embedder(cfg.embedding_model, cfg.embedding_dim)
            vectors = embedder.embed([text for _, text in upserts])
            rows = [
                (node_id, vector)
                for (node_id, _), vector in zip(upserts, vectors, strict=False)
            ]
            written = vec.upsert_rows(
                conn, workspace_id=workspace_id, dim=cfg.embedding_dim, rows=rows
            )
        conn.commit()
        return written


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


@dataclass(frozen=True, slots=True)
class SemanticStatus:
    enabled: bool
    model: str
    vector_count: int


async def get_semantic_status(*, workspace_id: UUID) -> SemanticStatus:
    """Report whether semantic search is on and how many vectors are stored."""
    cfg = load_runtime_settings().code_graph
    vectors = 0
    db_path = current_sqlite_path()
    if db_path is not None:
        try:
            vectors = await asyncio.to_thread(
                _count_vectors, db_path, str(workspace_id)
            )
        except vec.VectorStoreUnavailable:
            vectors = 0
    return SemanticStatus(
        enabled=cfg.semantic_enabled,
        model=cfg.embedding_model,
        vector_count=vectors,
    )


def _count_vectors(db_path: str, workspace_id: str) -> int:
    with vec.open_connection(db_path) as conn:
        return vec.count_workspace(conn, workspace_id)


async def search_nodes(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[CodeNode]:
    """Search the graph for symbols matching ``query``.

    Always runs a lexical (case-insensitive substring) pass. When semantic
    search is enabled and the embedding backend is available, a vector KNN
    pass is fused with the lexical results via reciprocal rank fusion so
    meaning-based matches surface alongside exact name matches. Falls back to
    lexical-only on any embedding/vector failure.
    """
    cfg = load_runtime_settings().code_graph
    fetch = max(limit, 50) if cfg.semantic_enabled else limit
    lexical = await _lexical_search(
        db, workspace_id=workspace_id, query=query, kind=kind, limit=fetch
    )

    if not cfg.semantic_enabled:
        return lexical[:limit]
    db_path = current_sqlite_path()
    if db_path is None:
        return lexical[:limit]

    try:
        semantic_hits = await asyncio.to_thread(
            _semantic_query, db_path, cfg, str(workspace_id), query, fetch
        )
    except (emb.EmbeddingUnavailable, vec.VectorStoreUnavailable) as exc:
        logger.warning("code_graph semantic search disabled err={}", exc)
        return lexical[:limit]
    if not semantic_hits:
        return lexical[:limit]

    semantic_ids: list[UUID] = []
    for node_id, _distance in semantic_hits:
        try:
            semantic_ids.append(UUID(node_id))
        except ValueError:
            continue

    fused = _reciprocal_rank_fusion(
        [n.id for n in lexical], semantic_ids, cfg.semantic_weight
    )

    rows_by_id: dict[UUID, CodeNode] = {n.id: n for n in lexical}
    missing = [nid for nid in fused if nid not in rows_by_id]
    if missing:
        extra = (
            await db.exec(
                select(CodeNode).where(
                    CodeNode.workspace_id == workspace_id,
                    col(CodeNode.id).in_(missing),
                )
            )
        ).all()
        for node in extra:
            rows_by_id[node.id] = node

    ranked: list[CodeNode] = []
    for node_id in fused:
        node = rows_by_id.get(node_id)
        if node is None:
            continue
        if kind and node.kind != kind:
            continue
        ranked.append(node)
        if len(ranked) >= limit:
            break
    return ranked


async def _lexical_search(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    query: str,
    kind: str | None,
    limit: int,
) -> list[CodeNode]:
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


def _semantic_query(
    db_path: str,
    cfg: CodeGraphSettings,
    workspace_id: str,
    query: str,
    k: int,
) -> list[tuple[str, float]]:
    """Embed ``query`` and run a KNN search against the vector store (sync)."""
    embedder = emb.get_embedder(cfg.embedding_model, cfg.embedding_dim)
    query_vector = embedder.embed_one(query)
    with vec.open_connection(db_path) as conn:
        return vec.knn(conn, workspace_id=workspace_id, query_vector=query_vector, k=k)


def _reciprocal_rank_fusion(
    lexical_ids: list[UUID],
    semantic_ids: list[UUID],
    semantic_weight: float,
) -> list[UUID]:
    """Fuse two ranked id lists into one via weighted reciprocal rank fusion."""
    weight = min(max(semantic_weight, 0.0), 1.0)
    scores: dict[UUID, float] = {}
    for rank, node_id in enumerate(lexical_ids):
        scores[node_id] = scores.get(node_id, 0.0) + (1.0 - weight) / (
            _RRF_K + rank + 1
        )
    for rank, node_id in enumerate(semantic_ids):
        scores[node_id] = scores.get(node_id, 0.0) + weight / (_RRF_K + rank + 1)
    return [
        node_id
        for node_id, _score in sorted(
            scores.items(), key=lambda kv: kv[1], reverse=True
        )
    ]


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
    if outgoing:
        edge_stmt = select(CodeEdge).where(
            CodeEdge.workspace_id == workspace_id, CodeEdge.src_id == node_id
        )
    else:
        edge_stmt = select(CodeEdge).where(
            CodeEdge.workspace_id == workspace_id, CodeEdge.dst_id == node_id
        )
    if edge_kind:
        edge_stmt = edge_stmt.where(CodeEdge.kind == edge_kind)
    edges = list((await db.exec(edge_stmt)).all())
    if not edges:
        return []

    target_ids = [e.dst_id if outgoing else e.src_id for e in edges]
    nodes = (
        await db.exec(
            select(CodeNode).where(
                CodeNode.workspace_id == workspace_id,
                col(CodeNode.id).in_(target_ids),
            )
        )
    ).all()
    node_by_id = {n.id: n for n in nodes}
    out: list[tuple[str, CodeNode]] = []
    for edge in edges:
        target = node_by_id.get(edge.dst_id if outgoing else edge.src_id)
        if target is not None:
            out.append((edge.kind, target))
    return out


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
    edge_count = len(
        (
            await db.exec(
                select(CodeEdge.id).where(CodeEdge.workspace_id == workspace_id)
            )
        ).all()
    )

    languages = sorted({f.language for f in files})
    ranked = sorted(files, key=lambda f: f.node_count, reverse=True)[:top_files]
    return WorkspaceOverview(
        node_count=len(kinds),
        edge_count=edge_count,
        file_count=len(files),
        languages=languages,
        kind_counts=dict(Counter(kinds)),
        top_files=[(f.file_path, f.node_count) for f in ranked],
    )
