"""Consolidated code graph tools — 4 tools instead of 7.

This module provides 4 simple, effective tools for code graph navigation:

1. code_search  — Unified search + symbol lookup
2. code_graph   — Unified relationship view (callers, callees, cross-repo)
3. code_overview — Statistics, languages, and most-referenced symbols
4. code_path    — Shortest dependency path between two symbols

Design principles:
- Auto-detect scope (workspace vs project)
- Combined inbound/outbound relationships
- Token-efficient output
- Simple parameters for agents to use
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.models.code_graph import CodeAmbiguousEdge, CodeNode, CrossRepoEdge
from app.services import code_graph_service as svc
from app.services import coding_project_service as proj_svc

_NOT_INDEXED = (
    "This workspace has no code index yet. Build one first "
    "(reindex the workspace), then retry."
)

_DOCSTRING_CLAMP = 320

_RELATION_LABELS = {
    "calls": ("calls", "called by"),
    "inherits": ("extends", "extended by"),
    "implements": ("implements", "implemented by"),
    "imports": ("imports", "imported by"),
    "uses": ("uses", "used by"),
    "references": ("references", "referenced by"),
    "decorated_by": ("decorated by", "decorates"),
    "contains": ("contains", "contained by"),
    "overrides": ("overrides", "overridden by"),
    "throws": ("throws", "thrown by"),
    "reads": ("reads", "read by"),
    "writes": ("writes", "written by"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


async def _resolve_workspace(db: AsyncSession):
    """Get workspace ID for current sandbox."""
    sandbox = get_sandbox()
    return await svc.resolve_workspace_id(db, path=str(sandbox.workspace_root))


def _loc(node: CodeNode) -> str:
    return f"{node.file_path}:{node.line_start}-{node.line_end}"


def _node_line(index: int, node: CodeNode) -> str:
    line = f"{index}. [{node.kind}] {node.qualified_name} — {_loc(node)}"
    if node.signature:
        line += f"\n   sig: {node.signature}"
    return line


async def _resolve_name_anywhere(
    db: AsyncSession,
    *,
    workspace_id,
    project_id,
    name: str,
    local_limit: int = 10,
    sibling_limit: int = 5,
):
    """Resolve name in active workspace, fall back to siblings if not found."""
    matches = [
        (workspace_id, n)
        for n in await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=local_limit
        )
    ]
    if matches or project_id is None:
        return matches

    # Fall back to sibling repos
    pairs = await proj_svc.get_project_workspaces(db, project_id)
    sibling_paths = [ws.path for _, ws in pairs if str(ws.id) != str(workspace_id)]
    if not sibling_paths:
        return matches

    cross_results = await svc.search_across_workspaces(
        db,
        workspace_paths=sibling_paths,
        query=name,
        kind=None,
        limit_per_workspace=sibling_limit,
    )
    for path, ws_id, node in cross_results:
        matches.append((ws_id, node))

    return matches


async def _find_cross_repo_references(
    db, project_ids, node_id, *, direction: str = "both"
):
    """Find cross-repo references for this node.

    Args:
        direction: 'in' (who references me), 'out' (what I reference), 'both'
    """
    if not project_ids:
        return []

    from app.models.code_graph import CrossRepoEdge
    from sqlmodel import col, select

    conditions = [
        col(CrossRepoEdge.project_id).in_(project_ids),
        col(CrossRepoEdge.status) == "resolved",
    ]

    # Add direction filter
    if direction == "in":
        conditions.append(col(CrossRepoEdge.dst_node_id) == node_id)
    elif direction == "out":
        conditions.append(col(CrossRepoEdge.src_node_id) == node_id)
    else:  # both
        from sqlmodel import or_

        conditions.append(
            or_(
                col(CrossRepoEdge.dst_node_id) == node_id,
                col(CrossRepoEdge.src_node_id) == node_id,
            )
        )

    refs = (await db.exec(select(CrossRepoEdge).where(*conditions))).all()
    return refs


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 1: code_search — Unified search + symbol lookup
# ═══════════════════════════════════════════════════════════════════════════════


async def _code_search(
    query: Annotated[str, Field(description="Symbol name or fragment to search for.")],
    kind: Annotated[
        Literal[
            "file",
            "module",
            "class",
            "function",
            "method",
            "interface",
            "variable",
            "field",
            "property",
            "enum",
            "struct",
            "namespace",
        ]
        | None,
        Field(description="Restrict results to a single symbol kind."),
    ] = None,
    limit: Annotated[
        int, Field(description="Maximum results to return (max 50).")
    ] = 20,
) -> str:
    """Search the code graph for symbols and get detailed info.

    Combines search with symbol lookup:
    - Search phase: find matching symbols (FTS5 + substring fallback)
    - Detail phase: for top matches, show signature, relationships, cross-repo refs

    Auto-detects scope: searches active repo, then sibling repos if in a project.
    """
    capped = max(1, min(limit, 50))

    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        # Search active repo
        nodes = await svc.search_nodes(
            db, workspace_id=workspace_id, query=query, kind=kind, limit=capped
        )

        # If few results and we have siblings, search them too
        cross_repo_nodes = []
        if project_id and len(nodes) < capped:
            pairs = await proj_svc.get_project_workspaces(db, project_id)
            sibling_paths = [
                ws.path for _, ws in pairs if str(ws.id) != str(workspace_id)
            ]
            if sibling_paths:
                cross_repo_nodes = await svc.search_across_workspaces(
                    db,
                    workspace_paths=sibling_paths,
                    query=query,
                    kind=kind,
                    limit_per_workspace=min(capped, 5),
                )

    if not nodes and not cross_repo_nodes:
        return f"No symbols matched '{query}'."

    # Build response
    sections = []

    if nodes:
        header = f"Active repo — {len(nodes)} hit(s) for '{query}':"
        body = "\n".join(_node_line(i, n) for i, n in enumerate(nodes, start=1))
        sections.append(f"{header}\n{body}")

    if cross_repo_nodes:
        grouped = {}
        for path, _ws_id, node in cross_repo_nodes:
            grouped.setdefault(path, []).append(node)
        for path, repo_nodes in grouped.items():
            label = Path(path).name or path
            lines = "\n".join(
                f"  {i}. [{n.kind}] {n.qualified_name} — {_loc(n)}"
                for i, n in enumerate(repo_nodes, start=1)
            )
            sections.append(f"{label} ({path}):\n{lines}")

    return "\n\n".join(sections)


code_search = Tool(
    _code_search,
    name="code_search",
    description=(
        "Search the code graph for symbols by name or fragment. Returns "
        "symbol references (kind, qualified name, file:line, signature) "
        "without reading source files. Auto-detects workspace vs project scope."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Search the indexed code graph for symbols by name or fragment.",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 2: code_graph — Unified relationship view
# ═══════════════════════════════════════════════════════════════════════════════


async def _code_graph(
    name: Annotated[
        str, Field(description="Symbol name or qualified name to explore.")
    ],
    direction: Annotated[
        Literal["in", "out", "both"],
        Field(
            description="Which relationships to show: 'in' (callers), 'out' (calls), 'both'."
        ),
    ] = "both",
    limit: Annotated[
        int, Field(description="Maximum relationships to return (max 100).")
    ] = 40,
) -> str:
    """Explore a symbol's relationships — who calls it, what it calls, inheritance, etc.

    Shows both inbound (callers, importers) and outbound (calls, inherits) relationships
    in a single view. Includes cross-repo references when in a multi-repo project.
    """
    capped = max(1, min(limit, 100))

    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        matches = await _resolve_name_anywhere(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            local_limit=5,
            sibling_limit=3,
        )

        if not matches:
            msg = f"No symbol named '{name}' in the code index."
            if project_id:
                msg += " This project has sibling repos — try a broader search."
            return msg

        # Label every repo in the project — covers both a matched symbol
        # living in a sibling workspace and a cross-repo edge's own source/
        # destination workspace, which aren't necessarily the same one.
        repo_labels = {}
        if project_id:
            pairs = await proj_svc.get_project_workspaces(db, project_id)
            repo_labels = {
                ws.id: (ws.name or Path(ws.path).name) for _link, ws in pairs
            }

        sections = []
        for match_ws_id, node in matches:
            # Get outbound relationships
            out_edges = []
            import_note: str | None = None
            if direction in ("out", "both"):
                out_edges = await svc.get_neighbors(
                    db, workspace_id=match_ws_id, node_id=node.id, direction="out"
                )
                # Import edges attach to the file node, not to whatever
                # class/method textually contains the import statement — a
                # class-level lookup would otherwise never show what its
                # file imports. Merge the file's outbound imports in.
                if node.kind != "file" and not any(
                    k == "imports" for k, _ in out_edges
                ):
                    file_node = await svc.find_file_node(
                        db, workspace_id=match_ws_id, file_path=node.file_path
                    )
                    if file_node is not None:
                        file_imports = [
                            pair
                            for pair in await svc.get_neighbors(
                                db,
                                workspace_id=match_ws_id,
                                node_id=file_node.id,
                                direction="out",
                            )
                            if pair[0] == "imports"
                        ]
                        if file_imports:
                            out_edges = out_edges + file_imports
                            import_note = (
                                f"imports are file-level — showing "
                                f"{file_node.file_path}'s imports"
                            )

            # Get inbound relationships
            in_edges = []
            if direction in ("in", "both"):
                in_edges = await svc.get_neighbors(
                    db, workspace_id=match_ws_id, node_id=node.id, direction="in"
                )

            ambiguous_edges = []
            if direction in ("out", "both"):
                ambiguous_edges = await svc.get_ambiguous_relationships(
                    db, workspace_id=match_ws_id, node_id=node.id
                )

            # Get cross-repo references (both directions)
            cross_repo = await _find_cross_repo_references(
                db, project_ids, node.id, direction=direction
            )

            sections.append(
                _render_graph(
                    node,
                    out_edges,
                    in_edges,
                    cross_repo,
                    # Only prefix the head line for a match in a *foreign*
                    # workspace — no need to tell the agent it's looking at
                    # its own active repo. cross_repo_labels stays unfiltered
                    # since a cross-repo edge can legitimately point back at
                    # the active workspace while describing a foreign match.
                    repo_label=(
                        repo_labels.get(match_ws_id)
                        if match_ws_id != workspace_id
                        else None
                    ),
                    limit=capped,
                    import_note=import_note,
                    cross_repo_labels=repo_labels,
                    ambiguous_edges=ambiguous_edges,
                )
            )

    return "\n\n".join(sections)


def _render_graph(
    node: CodeNode,
    out_edges: list[tuple[str, CodeNode]],
    in_edges: list[tuple[str, CodeNode]],
    cross_repo: Sequence[CrossRepoEdge] = (),
    repo_label: str | None = None,
    limit: int = 40,
    import_note: str | None = None,
    cross_repo_labels: dict | None = None,
    ambiguous_edges: Sequence[tuple[CodeAmbiguousEdge, list[CodeNode]]] = (),
) -> str:
    head = f"[{node.kind}] {node.qualified_name} — {_loc(node)}"
    if repo_label:
        head = f"[{repo_label}] {head}"

    lines = [head]

    if node.signature:
        lines.append(f"  sig: {node.signature}")

    if node.docstring:
        doc = node.docstring.strip().replace("\n", " ")
        if len(doc) > _DOCSTRING_CLAMP:
            doc = doc[:_DOCSTRING_CLAMP] + "…"
        lines.append(f"  doc: {doc}")

    def _joined(names: list[str]) -> str:
        shown = ", ".join(names[:limit])
        if len(names) > limit:
            shown += f" … and {len(names) - limit} more"
        return shown

    def _append_relationships(
        edges: list[tuple[str, CodeNode]], *, label_index: int
    ) -> None:
        grouped: dict[str, list[str]] = {}
        for kind, related in edges:
            grouped.setdefault(kind, []).append(related.qualified_name)

        ordered_kinds = [kind for kind in _RELATION_LABELS if kind in grouped]
        ordered_kinds.extend(kind for kind in grouped if kind not in _RELATION_LABELS)
        for kind in ordered_kinds:
            names = grouped[kind]
            labels = _RELATION_LABELS.get(kind, (kind, f"{kind} by"))
            lines.append(f"  {labels[label_index]} ({len(names)}): {_joined(names)}")
            if kind == "imports" and label_index == 0 and import_note:
                lines.append(f"  ({import_note})")

    _append_relationships(out_edges, label_index=0)
    _append_relationships(in_edges, label_index=1)

    for relationship, candidates in ambiguous_edges[:limit]:
        candidate_labels = [
            f"{candidate.qualified_name} — {_loc(candidate)}"
            for candidate in candidates
        ]
        lines.append(
            f"  ambiguous {relationship.kind} '{relationship.dst_name}' "
            f"({len(candidates)} candidates): {_joined(candidate_labels)}"
        )

    # Cross-repo inbound (who references me from other repos)
    cross_in = [e for e in cross_repo if e.dst_node_id == node.id]
    cross_out = [e for e in cross_repo if e.src_node_id == node.id]
    labels = cross_repo_labels or {}

    if cross_in:
        lines.append(f"  referenced by ({len(cross_in)} cross-repo):")
        for edge in cross_in[:limit]:
            loc = (
                f"{edge.src_file_path}:{edge.src_line}"
                if edge.src_line
                else edge.src_file_path
            )
            src_label = labels.get(edge.src_workspace_id)
            prefix = f"{src_label}/" if src_label else ""
            lines.append(f"    ← {prefix}{loc} (`{edge.raw_reference}`)")
        if len(cross_in) > limit:
            lines.append(f"    … and {len(cross_in) - limit} more")

    if cross_out:
        lines.append(f"  references ({len(cross_out)} cross-repo):")
        for edge in cross_out[:limit]:
            loc = (
                f"{edge.src_file_path}:{edge.src_line}"
                if edge.src_line
                else edge.src_file_path
            )
            dst_label = labels.get(edge.dst_workspace_id)
            prefix = f"{dst_label}/" if dst_label else ""
            lines.append(f"    → {prefix}{loc} (`{edge.raw_reference}`)")
        if len(cross_out) > limit:
            lines.append(f"    … and {len(cross_out) - limit} more")

    return "\n".join(lines)


code_graph = Tool(
    _code_graph,
    name="code_graph",
    description=(
        "Explore a symbol's callers, callees, imports, inheritance, type and DI "
        "references, decorators, containment, ambiguous targets, and cross-repo "
        "links. Shows inbound and outbound relationships in one view."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Explore structural relationships, ambiguity, and cross-repo links.",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 3: code_overview — Unified overview + ranking
# ═══════════════════════════════════════════════════════════════════════════════


async def _code_overview(
    budget: Annotated[
        int, Field(description="Number of top symbols to include (max 50).")
    ] = 25,
) -> str:
    """Get an overview of the codebase: statistics, languages, and most-used symbols.

    Shows:
    - File, node, and edge counts
    - Per-language breakdown
    - Top symbols by usage (in-degree ranking)
    - Cross-repo stats (if multi-repo project)
    """
    capped = max(1, min(budget, 50))

    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        # Get stats for active workspace
        stats = await svc.get_index_status(db, workspace_id=workspace_id)

        sections = [f"Workspace: {Path(get_sandbox().workspace_root).name}"]
        sections.append(
            f"  Files: {stats['files']} | Symbols: {stats['nodes']} | Edges: {stats['edges']}"
        )

        # Per-language breakdown
        from app.models.code_graph import CodeNode
        from sqlmodel import col, func, select

        lang_stats = (
            await db.exec(
                select(CodeNode.language, func.count())
                .where(col(CodeNode.workspace_id) == workspace_id)
                .group_by(CodeNode.language)
            )
        ).all()
        if lang_stats:
            lang_str = ", ".join(
                f"{lang}: {count}" for lang, count in lang_stats if lang
            )
            sections.append(f"  Languages: {lang_str}")

        # Top symbols
        ranked = await svc.get_ranked_symbols(
            db, workspace_id=workspace_id, budget=capped
        )
        if ranked:
            sections.append(f"\nTop {len(ranked)} most-referenced symbols:")
            for i, (node, count) in enumerate(ranked, start=1):
                line = f"{i}. [{node.kind}] {node.qualified_name} — {_loc(node)} (refs: {count})"
                if node.signature:
                    line += f"\n   sig: {node.signature}"
                sections.append(line)

        # Multi-repo overview
        if project_id:
            pairs = await proj_svc.get_project_workspaces(db, project_id)
            if len(pairs) > 1:
                sections.append(f"\nProject: {len(pairs)} repos")
                for _link, ws in pairs:
                    if str(ws.id) != str(workspace_id):
                        ws_stats = await svc.get_index_status(db, workspace_id=ws.id)
                        sections.append(
                            f"  - {ws.name or Path(ws.path).name}: "
                            f"{ws_stats['files']} files, {ws_stats['nodes']} symbols"
                        )

    return "\n".join(sections)


code_overview = Tool(
    _code_overview,
    name="code_overview",
    description=(
        "Overview of the codebase: file/symbol/edge counts, language breakdown, "
        "and most-referenced symbols. Shows project-wide stats in multi-repo mode."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Show indexed codebase statistics, languages, and important symbols.",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 4: code_path — Shortest path
# ═══════════════════════════════════════════════════════════════════════════════


async def _code_path(
    source: Annotated[str, Field(description="Source symbol name or qualified name.")],
    target: Annotated[str, Field(description="Target symbol name or qualified name.")],
    max_hops: Annotated[
        int, Field(description="Maximum hops to search (max 8, default 6).")
    ] = 6,
) -> str:
    """Find the shortest dependency path between two symbols.

    Traces through calls, imports, inheritance, and references to show
    how symbol A reaches symbol B. Useful for impact analysis and
    understanding data flow across the codebase.
    """
    hops = max(1, min(max_hops, 8))

    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        # Resolve source
        src_matches = await _resolve_name_anywhere(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            name=source,
            local_limit=3,
            sibling_limit=3,
        )
        if not src_matches:
            return f"No symbol named '{source}' in the code index."

        # Resolve target
        dst_matches = await _resolve_name_anywhere(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            name=target,
            local_limit=3,
            sibling_limit=3,
        )
        if not dst_matches:
            return f"No symbol named '{target}' in the code index."

        # Try all combinations, return first real path
        same_symbol = None
        for src_ws_id, src_node in src_matches:
            for dst_ws_id, dst_node in dst_matches:
                if src_node.id == dst_node.id:
                    if same_symbol is None:
                        same_symbol = (src_node, dst_node)
                    continue

                path = await svc.find_shortest_path(
                    db,
                    src_workspace_id=src_ws_id,
                    src_id=src_node.id,
                    dst_id=dst_node.id,
                    max_hops=hops,
                    project_id=project_id,
                )
                if path is not None:
                    return _render_path(src_node, dst_node, path)

        if same_symbol is not None:
            return _render_path(*same_symbol, [])

    return f"No path found between '{source}' and '{target}' within {hops} hops."


def _render_path(src, dst, path):
    if not path:
        return f"'{src.qualified_name}' and '{dst.qualified_name}' are the same symbol."
    head = (
        f"Path from [{src.kind}] {src.qualified_name} → "
        f"[{dst.kind}] {dst.qualified_name} ({len(path)} hops):"
    )
    rows = [
        f"  {i}. [{f.kind}] {f.qualified_name} —{kind}→ [{t.kind}] {t.qualified_name}"
        for i, (f, kind, t) in enumerate(path, start=1)
    ]
    return head + "\n" + "\n".join(rows)


code_path = Tool(
    _code_path,
    name="code_path",
    description=(
        "Find the shortest dependency path between two symbols — trace how "
        "module A reaches module B through calls, imports, and inheritance."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Find a dependency path between two indexed code symbols.",
)
