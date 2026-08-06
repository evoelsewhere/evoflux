"""Directional traversal of local and resolved cross-repository graph edges."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_graph import CodeEdge, CodeNode, CrossRepoEdge
from app.services.code_intelligence.models import (
    GraphOperation,
    GraphRelation,
    SymbolMatch,
    WorkspaceScope,
)

_REFERENCE_KINDS = frozenset(
    {
        "calls",
        "references",
        "imports",
        "inherits",
        "implements",
        "uses",
        "overrides",
        "reads",
        "writes",
        "decorated_by",
        "throws",
    }
)
_NEIGHBORHOOD_KINDS = _REFERENCE_KINDS | {"contains"}


@dataclass(frozen=True, slots=True)
class _RawRelation:
    src_workspace_id: UUID
    src_id: UUID
    dst_workspace_id: UUID
    dst_id: UUID
    kind: str
    file_path: str | None
    line: int | None
    cross_repo: bool


async def _edge_rows(
    db: AsyncSession,
    *,
    frontier: set[UUID],
    allowed_workspaces: set[UUID],
) -> list[_RawRelation]:
    if not frontier:
        return []
    local = list(
        (
            await db.exec(
                select(CodeEdge).where(
                    col(CodeEdge.workspace_id).in_(allowed_workspaces),
                    col(CodeEdge.kind).in_(_NEIGHBORHOOD_KINDS),
                    or_(
                        col(CodeEdge.src_id).in_(frontier),
                        col(CodeEdge.dst_id).in_(frontier),
                    ),
                )
            )
        ).all()
    )
    rows = [
        _RawRelation(
            edge.workspace_id,
            edge.src_id,
            edge.workspace_id,
            edge.dst_id,
            edge.kind,
            edge.file_path,
            edge.line,
            False,
        )
        for edge in local
    ]
    if len(allowed_workspaces) < 2:
        return rows
    cross = list(
        (
            await db.exec(
                select(CrossRepoEdge).where(
                    CrossRepoEdge.status == "resolved",
                    col(CrossRepoEdge.src_workspace_id).in_(allowed_workspaces),
                    col(CrossRepoEdge.dst_workspace_id).in_(allowed_workspaces),
                    col(CrossRepoEdge.src_node_id).is_not(None),
                    col(CrossRepoEdge.dst_node_id).is_not(None),
                    or_(
                        col(CrossRepoEdge.src_node_id).in_(frontier),
                        col(CrossRepoEdge.dst_node_id).in_(frontier),
                    ),
                )
            )
        ).all()
    )
    for edge in cross:
        if (
            edge.src_node_id is None
            or edge.dst_node_id is None
            or edge.dst_workspace_id is None
        ):
            continue
        rows.append(
            _RawRelation(
                edge.src_workspace_id,
                edge.src_node_id,
                edge.dst_workspace_id,
                edge.dst_node_id,
                edge.kind,
                edge.src_file_path,
                edge.src_line,
                True,
            )
        )
    return rows


def _admit(
    edge: _RawRelation,
    *,
    frontier: set[tuple[UUID, UUID]],
    operation: GraphOperation,
) -> tuple[bool, tuple[UUID, UUID] | None]:
    src = (edge.src_workspace_id, edge.src_id)
    dst = (edge.dst_workspace_id, edge.dst_id)
    outbound = src in frontier
    inbound = dst in frontier
    if operation == "callers":
        # A statically named callable passed to a dispatcher (asyncio.to_thread,
        # executor.submit, event handlers, and similar APIs) is indexed as a
        # reference because the framework controls invocation time.  It still
        # belongs in "where can this function be invoked?" results.
        return inbound and edge.kind in {
            "calls",
            "references",
        }, src if inbound else None
    if operation == "callees":
        return outbound and edge.kind == "calls", dst if outbound else None
    if operation in {"references", "impact"}:
        return inbound and edge.kind in _REFERENCE_KINDS, src if inbound else None
    if operation == "neighborhood":
        if outbound and edge.kind in _NEIGHBORHOOD_KINDS:
            return True, dst
        if inbound and edge.kind in _NEIGHBORHOOD_KINDS:
            return True, src
    return False, None


async def traverse_symbol_graph(
    db: AsyncSession,
    *,
    roots: tuple[SymbolMatch, ...],
    scopes: tuple[WorkspaceScope, ...],
    operation: GraphOperation,
    depth: int,
    limit: int,
) -> tuple[list[GraphRelation], bool]:
    """Traverse only the direction and edge kinds requested by the caller."""
    if not roots or operation == "definition":
        return [], False
    scopes_by_id = {scope.workspace_id: scope for scope in scopes}
    allowed_workspaces = set(scopes_by_id)
    known: dict[tuple[UUID, UUID], SymbolMatch] = {
        root.identity: root for root in roots
    }
    visited = set(known)
    frontier = set(known)
    relations: list[GraphRelation] = []
    seen_edges: set[tuple[tuple[UUID, UUID], tuple[UUID, UUID], str, int | None]] = (
        set()
    )
    truncated = False

    for current_depth in range(1, max(1, depth) + 1):
        rows = await _edge_rows(
            db,
            frontier={node_id for _, node_id in frontier},
            allowed_workspaces=allowed_workspaces,
        )
        admitted: list[tuple[_RawRelation, tuple[UUID, UUID]]] = []
        wanted: set[UUID] = set()
        for edge in rows:
            keep, neighbor = _admit(edge, frontier=frontier, operation=operation)
            if not keep or neighbor is None:
                continue
            key = (
                (edge.src_workspace_id, edge.src_id),
                (edge.dst_workspace_id, edge.dst_id),
                edge.kind,
                edge.line,
            )
            if key in seen_edges:
                continue
            seen_edges.add(key)
            admitted.append((edge, neighbor))
            if neighbor not in known:
                wanted.add(neighbor[1])

        if wanted:
            nodes = list(
                (
                    await db.exec(
                        select(CodeNode).where(
                            col(CodeNode.id).in_(wanted),
                            col(CodeNode.workspace_id).in_(allowed_workspaces),
                        )
                    )
                ).all()
            )
            for node in nodes:
                scope = scopes_by_id.get(node.workspace_id)
                if scope is not None:
                    known[(node.workspace_id, node.id)] = SymbolMatch(
                        node=node,
                        scope=scope,
                        resolution="qualified",
                    )

        next_frontier: set[tuple[UUID, UUID]] = set()
        admitted.sort(
            key=lambda item: (
                item[0].kind,
                str(item[0].src_workspace_id),
                str(item[0].src_id),
                str(item[0].dst_workspace_id),
                str(item[0].dst_id),
                item[0].line or 0,
            )
        )
        for edge, neighbor in admitted:
            source = known.get((edge.src_workspace_id, edge.src_id))
            target = known.get((edge.dst_workspace_id, edge.dst_id))
            if source is None or target is None:
                continue
            if len(relations) >= limit:
                truncated = True
                break
            callsite_file = edge.file_path or source.node.file_path
            callsite_line = edge.line or source.node.line_start
            relations.append(
                GraphRelation(
                    source=source,
                    target=target,
                    kind=edge.kind,
                    depth=current_depth,
                    cross_repo=edge.cross_repo,
                    callsite_file=callsite_file,
                    callsite_line=callsite_line,
                )
            )
            if neighbor not in visited:
                visited.add(neighbor)
                next_frontier.add(neighbor)
        if truncated or not next_frontier:
            break
        frontier = next_frontier
    return relations, truncated
