"""Code knowledge-graph tools — token-efficient codebase navigation.

These tools query the pre-built code graph for the active coding workspace
instead of reading whole files. They return symbol references (kind, qualified
name, ``file:line``, signature) rather than source bodies, so the agent can
locate and reason about code while spending far fewer tokens.

The graph is workspace-scoped: the active sandbox root is mapped to its
registered coding workspace. If the workspace has not been indexed yet, the
tools say so instead of guessing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.models.chat import CodingWorkspace
from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services import code_graph_service as svc
from app.services import coding_project_service as proj_svc

_NOT_INDEXED = (
    "This workspace has no code index yet. Build one first "
    "(reindex the workspace), then retry."
)

# Cap on how many neighbours we render per symbol to keep output compact.
_MAX_NEIGHBORS = 40
_DOCSTRING_CLAMP = 320


async def _resolve_workspace(db: AsyncSession) -> UUID | None:
    sandbox = get_sandbox()
    return await svc.resolve_workspace_id(db, path=str(sandbox.workspace_root))


def _loc(node: CodeNode) -> str:
    return f"{node.file_path}:{node.line_start}-{node.line_end}"


def _node_line(index: int, node: CodeNode) -> str:
    line = f"{index}. [{node.kind}] {node.qualified_name} — {_loc(node)}"
    if node.signature:
        line += f"\n   sig: {node.signature}"
    return line


async def _code_search(
    query: Annotated[str, Field(description="Symbol name or fragment to search for.")],
    kind: Annotated[
        Literal["file", "class", "function", "method", "interface"] | None,
        Field(description="Restrict results to a single symbol kind."),
    ] = None,
    limit: Annotated[
        int, Field(description="Maximum number of symbols to return (max 50).")
    ] = 20,
) -> str:
    """Search the code graph for symbols whose name matches ``query``.

    Use this to find where something lives without reading files. Matches are
    case-insensitive substring matches over symbol name and qualified name.
    Returns each hit as ``[kind] qualified_name — file:line`` plus its
    signature. Optionally restrict to a single ``kind``.
    """
    capped = max(1, min(limit, 50))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        nodes = await svc.search_nodes(
            db, workspace_id=workspace_id, query=query, kind=kind, limit=capped
        )
    if not nodes:
        return f"No symbols matched '{query}'."
    header = f"Found {len(nodes)} symbol(s) for '{query}':"
    body = "\n".join(_node_line(i, n) for i, n in enumerate(nodes, start=1))
    return f"{header}\n{body}"


async def _code_symbol(
    name: Annotated[
        str, Field(description="Exact symbol name or fully qualified name.")
    ],
) -> str:
    """Look up a symbol by exact name or qualified name and summarise it.

    Returns the symbol's kind, location, signature, docstring (truncated), and
    a one-line tally of its direct relationships (what it calls, who calls it,
    what it inherits). Use this to understand a specific function/class/method
    before deciding whether to open the file.
    """
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=10
        )
        if not matches:
            return f"No symbol named '{name}' in the code index."
        sections: list[str] = []
        for node in matches:
            out_edges = await svc.get_neighbors(
                db, workspace_id=workspace_id, node_id=node.id, direction="out"
            )
            in_edges = await svc.get_neighbors(
                db, workspace_id=workspace_id, node_id=node.id, direction="in"
            )
            sections.append(_render_symbol(node, out_edges, in_edges))
    return "\n\n".join(sections)


def _render_symbol(
    node: CodeNode,
    out_edges: list[tuple[str, CodeNode]],
    in_edges: list[tuple[str, CodeNode]],
) -> str:
    lines = [
        f"[{node.kind}] {node.qualified_name}",
        f"  location: {_loc(node)}  ({node.language})",
    ]
    if node.signature:
        lines.append(f"  signature: {node.signature}")
    if node.docstring:
        doc = node.docstring.strip().replace("\n", " ")
        if len(doc) > _DOCSTRING_CLAMP:
            doc = doc[:_DOCSTRING_CLAMP] + "…"
        lines.append(f"  doc: {doc}")
    calls = [n.qualified_name for k, n in out_edges if k == "calls"]
    callers = [n.qualified_name for k, n in in_edges if k == "calls"]
    bases = [n.qualified_name for k, n in out_edges if k in ("inherits", "implements")]
    if calls:
        lines.append(f"  calls ({len(calls)}): {', '.join(calls[:15])}")
    if callers:
        lines.append(f"  called by ({len(callers)}): {', '.join(callers[:15])}")
    if bases:
        lines.append(f"  extends/implements: {', '.join(bases[:15])}")
    return "\n".join(lines)


async def _code_neighbors(
    name: Annotated[str, Field(description="Symbol name or qualified name to expand.")],
    direction: Annotated[
        Literal["out", "in", "both"],
        Field(description="'out' = dependencies, 'in' = dependents, 'both' = either."),
    ] = "both",
    edge_kind: Annotated[
        Literal["calls", "inherits", "implements", "contains"] | None,
        Field(description="Restrict to a single relationship kind."),
    ] = None,
) -> str:
    """List the graph neighbours of a symbol (callers, callees, subtypes…).

    ``direction='out'`` shows what the symbol depends on (it calls / inherits);
    ``'in'`` shows what depends on it (callers / subclasses); ``'both'`` shows
    both. Optionally filter to a single ``edge_kind``. Resolve the symbol by
    exact name or qualified name first via ``code_search`` if unsure.
    """
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=5
        )
        if not matches:
            return f"No symbol named '{name}' in the code index."
        sections: list[str] = []
        for node in matches:
            neighbours = await svc.get_neighbors(
                db,
                workspace_id=workspace_id,
                node_id=node.id,
                direction=direction,
                edge_kind=edge_kind,
            )
            sections.append(_render_neighbors(node, neighbours))
    return "\n\n".join(sections)


def _render_neighbors(node: CodeNode, neighbours: list[tuple[str, CodeNode]]) -> str:
    head = f"[{node.kind}] {node.qualified_name} — {_loc(node)}"
    if not neighbours:
        return f"{head}\n  (no matching neighbours)"
    rows = [
        f"  {kind} → [{n.kind}] {n.qualified_name} — {_loc(n)}"
        for kind, n in neighbours[:_MAX_NEIGHBORS]
    ]
    extra = len(neighbours) - _MAX_NEIGHBORS
    if extra > 0:
        rows.append(f"  … and {extra} more")
    return head + "\n" + "\n".join(rows)


async def _code_overview() -> str:
    """Summarise the indexed codebase: totals, languages, and densest files.

    Use this at the start of a task to orient yourself: how big the graph is,
    which languages are present, the symbol-kind breakdown, and which files
    carry the most symbols (good entry points).
    """
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        ov = await svc.get_overview(db, workspace_id=workspace_id)
    if ov.file_count == 0:
        return "The code index is empty for this workspace."
    kinds = ", ".join(f"{k}={v}" for k, v in sorted(ov.kind_counts.items()))
    top = "\n".join(f"  {path} ({count} symbols)" for path, count in ov.top_files)
    return (
        f"Code index: {ov.node_count} nodes, {ov.edge_count} edges, "
        f"{ov.file_count} files.\n"
        f"Languages: {', '.join(ov.languages) or 'none'}\n"
        f"Symbol kinds: {kinds}\n"
        f"Densest files:\n{top}"
    )


code_search = Tool(
    _code_search,
    name="code_search",
    description=(
        "Search the code knowledge graph for symbols by name. Returns symbol "
        "references (kind, qualified name, file:line, signature) without reading "
        "file bodies — fast, token-cheap code location."
    ),
    concurrency_safe=True,
    read_only=True,
)

code_symbol = Tool(
    _code_symbol,
    name="code_symbol",
    description=(
        "Summarise a single symbol from the code graph: signature, docstring, "
        "and its direct callers/callees/base types. Use before opening a file."
    ),
    concurrency_safe=True,
    read_only=True,
)

code_neighbors = Tool(
    _code_neighbors,
    name="code_neighbors",
    description=(
        "List graph neighbours of a symbol — callers, callees, subtypes, "
        "containment — to trace impact and dependencies without reading files."
    ),
    concurrency_safe=True,
    read_only=True,
)

code_overview = Tool(
    _code_overview,
    name="code_overview",
    description=(
        "High-level map of the indexed codebase: node/edge/file totals, "
        "languages, symbol-kind breakdown, and the densest files."
    ),
    concurrency_safe=True,
    read_only=True,
)


# ---------------------------------------------------------------------------
# P4: code_references — find all usages of a symbol
# ---------------------------------------------------------------------------


async def _code_references(
    name: Annotated[
        str, Field(description="Symbol name or qualified name to look up.")
    ],
    limit: Annotated[
        int, Field(description="Maximum references to return (max 60).")
    ] = 30,
) -> str:
    """Find all places that reference a symbol (callers, importers, subclasses, decorators).

    Use this to answer "where is X used?" without manually grepping. Returns
    each reference as ``[edge_kind] source_symbol — file:line``. Resolves by
    exact name or qualified name.
    """
    capped = max(1, min(limit, 60))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=name, limit=5
        )
        if not matches:
            return f"No symbol named '{name}' in the code index."
        # A symbol can be the resolution target of a cross-repo reference from
        # a sibling repo in the same project — surface those alongside
        # same-repo references so "where is X used?" covers the whole project,
        # not just the active workspace.
        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        sections: list[str] = []
        for node in matches:
            refs = await svc.find_references(
                db, workspace_id=workspace_id, node_id=node.id, limit=capped
            )
            cross_repo = await _find_cross_repo_references(db, project_ids, node.id)
            sections.append(_render_references(node, refs, cross_repo))
    return "\n\n".join(sections)


async def _find_cross_repo_references(
    db: AsyncSession, project_ids: list[UUID], node_id: UUID
) -> list[tuple[CrossRepoEdge, str]]:
    """Resolved CrossRepoEdge rows from a sibling repo pointing at ``node_id``.

    Returns ``(edge, src_repo_label)`` pairs — the label is the source repo's
    directory name, resolved in one batched query rather than per-edge.
    """
    if not project_ids:
        return []
    edges = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.project_id).in_(project_ids),
                col(CrossRepoEdge.dst_node_id) == node_id,
                col(CrossRepoEdge.status) == "resolved",
            )
        )
    ).all()
    if not edges:
        return []
    ws_ids = {edge.src_workspace_id for edge in edges}
    workspaces = (
        await db.exec(
            select(CodingWorkspace).where(col(CodingWorkspace.id).in_(ws_ids))
        )
    ).all()
    label_by_ws = {ws.id: (ws.name or ws.path.rsplit("/", 1)[-1]) for ws in workspaces}
    return [(edge, label_by_ws.get(edge.src_workspace_id, "?")) for edge in edges]


def _render_references(
    node: CodeNode,
    refs: list[tuple[str, CodeNode, int | None]],
    cross_repo: Sequence[tuple[CrossRepoEdge, str]] = (),
) -> str:
    head = f"References to [{node.kind}] {node.qualified_name} — {_loc(node)}"
    if not refs and not cross_repo:
        return f"{head}\n  (no references found)"
    rows: list[str] = []
    for edge_kind, src_node, line in refs:
        loc = f"{src_node.file_path}:{line}" if line else _loc(src_node)
        rows.append(
            f"  {edge_kind} ← [{src_node.kind}] {src_node.qualified_name} — {loc}"
        )
    total = len(refs) + len(cross_repo)
    if cross_repo:
        rows.append("  Cross-repo:")
        for edge, repo_label in cross_repo:
            loc = (
                f"{edge.src_file_path}:{edge.src_line}"
                if edge.src_line
                else edge.src_file_path
            )
            rows.append(
                f"    {edge.kind} ← {repo_label}/{loc} (`{edge.raw_reference}`)"
            )
    return head + f" ({total} refs)\n" + "\n".join(rows)


code_references = Tool(
    _code_references,
    name="code_references",
    description=(
        "Find all usages of a symbol: callers, importers, subclasses, "
        "decorators. Answers 'where is X used?' without grepping."
    ),
    concurrency_safe=True,
    read_only=True,
)


# ---------------------------------------------------------------------------
# P5: code_map — context-budget repo map ranked by importance
# ---------------------------------------------------------------------------


async def _code_map(
    budget: Annotated[
        int,
        Field(description="How many top symbols to include (max 50, default 25)."),
    ] = 25,
) -> str:
    """Produce a ranked map of the most-referenced symbols in the codebase.

    Symbols are ranked by usage count (in-degree) — the more a function/class
    is called or referenced, the higher it ranks. This is the codebase's
    "table of contents": the key entry points and shared abstractions.
    Use this to understand what matters most before diving into details.
    """
    capped = max(1, min(budget, 50))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        ranked = await svc.get_ranked_symbols(
            db, workspace_id=workspace_id, budget=capped
        )
    if not ranked:
        return "No ranked symbols — the index may be empty or have no cross-references."
    header = f"Top {len(ranked)} symbols by usage (most-referenced first):"
    rows = [
        f"{i}. [{node.kind}] {node.qualified_name} — {_loc(node)}  (refs: {count})"
        + (f"\n   sig: {node.signature}" if node.signature else "")
        for i, (node, count) in enumerate(ranked, start=1)
    ]
    return header + "\n" + "\n".join(rows)


code_map = Tool(
    _code_map,
    name="code_map",
    description=(
        "Ranked map of the most-referenced symbols in the codebase — the key "
        "entry points and shared abstractions. Like a table of contents sorted "
        "by importance."
    ),
    concurrency_safe=True,
    read_only=True,
)


# ---------------------------------------------------------------------------
# P6: code_path — shortest path between two symbols
# ---------------------------------------------------------------------------


async def _code_path(
    source: Annotated[str, Field(description="Source symbol name or qualified name.")],
    target: Annotated[str, Field(description="Target symbol name or qualified name.")],
    max_hops: Annotated[
        int, Field(description="Maximum hops to search (max 8, default 6).")
    ] = 6,
) -> str:
    """Find the shortest dependency path between two symbols.

    Traces through calls, imports, inheritance, and references in both
    directions to show how symbol A relates to symbol B. Use this for impact
    analysis ("how does module X reach module Y?") or understanding data flow.
    """
    hops = max(1, min(max_hops, 8))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        src_matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=source, limit=3
        )
        if not src_matches and project_id is not None:
            sibling_paths = [
                ws.path
                for _, ws in await proj_svc.get_project_workspaces(db, project_id)
            ]
            src_matches = [
                node
                for _path, node in await svc.search_across_workspaces(
                    db,
                    workspace_paths=sibling_paths,
                    query=source,
                    limit_per_workspace=3,
                )
            ]
        if not src_matches:
            return f"No symbol named '{source}' in the code index."

        dst_matches = await svc.find_nodes_by_name(
            db, workspace_id=workspace_id, name=target, limit=3
        )
        if not dst_matches and project_id is not None:
            sibling_paths = [
                ws.path
                for _, ws in await proj_svc.get_project_workspaces(db, project_id)
            ]
            dst_matches = [
                node
                for _path, node in await svc.search_across_workspaces(
                    db,
                    workspace_paths=sibling_paths,
                    query=target,
                    limit_per_workspace=3,
                )
            ]
        if not dst_matches:
            return f"No symbol named '{target}' in the code index."

        # Try all combinations (usually 1×1), return first path found.
        for src_node in src_matches:
            for dst_node in dst_matches:
                path = await svc.find_shortest_path(
                    db,
                    workspace_id=workspace_id,
                    src_id=src_node.id,
                    dst_id=dst_node.id,
                    max_hops=hops,
                    project_id=project_id,
                )
                if path is not None:
                    return _render_path(src_node, dst_node, path)

    return f"No path found between '{source}' and '{target}' within {hops} hops."


def _render_path(
    src: CodeNode, dst: CodeNode, path: list[tuple[CodeNode, str, CodeNode]]
) -> str:
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
)
