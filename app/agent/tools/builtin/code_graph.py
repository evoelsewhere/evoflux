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

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.core.db import async_session_factory
from app.models.code_graph import CodeNode
from app.services import code_graph_service as svc

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
)

code_symbol = Tool(
    _code_symbol,
    name="code_symbol",
    description=(
        "Summarise a single symbol from the code graph: signature, docstring, "
        "and its direct callers/callees/base types. Use before opening a file."
    ),
)

code_neighbors = Tool(
    _code_neighbors,
    name="code_neighbors",
    description=(
        "List graph neighbours of a symbol — callers, callees, subtypes, "
        "containment — to trace impact and dependencies without reading files."
    ),
)

code_overview = Tool(
    _code_overview,
    name="code_overview",
    description=(
        "High-level map of the indexed codebase: node/edge/file totals, "
        "languages, symbol-kind breakdown, and the densest files."
    ),
)
