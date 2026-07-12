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
from pathlib import Path
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


def _not_found_message(name: str, *, scope: str, project_id: UUID | None) -> str:
    """Shared "not found" message for code_symbol/code_neighbors/code_references.

    A miss under the default scope='workspace' only means the symbol isn't
    in the ACTIVE repo — in a multi-repo project it may still exist in a
    sibling one. Say so explicitly rather than reading as "doesn't exist
    anywhere": a plain "not found" here has repeatedly led callers (agents
    auditing this tool included) to conclude project-wide absence from a
    single-repo lookup instead of retrying with scope='project'.
    """
    base = f"No symbol named '{name}' in the code index"
    if scope == "workspace" and project_id is not None:
        return (
            f"{base} for the active repo. This project has sibling repos — "
            "retry with scope='project' before concluding the symbol doesn't "
            "exist anywhere."
        )
    return f"{base}."


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
        int,
        Field(description="Maximum number of symbols to return per repo searched (max 50)."),
    ] = 20,
    scope: Annotated[
        Literal["workspace", "project"],
        Field(
            description=(
                "'workspace' (default) searches only the active repo, with a light "
                "taste of sibling repos if this is a multi-repo project. 'project' "
                "searches every repo in the project equally, each up to `limit`."
            )
        ),
    ] = "workspace",
) -> str:
    """Search the code graph for symbols whose name matches ``query``.

    Use this to find where something lives without reading files. Matches are
    case-insensitive substring matches over symbol name and qualified name.
    Returns each hit as ``[kind] qualified_name — file:line`` plus its
    signature. Optionally restrict to a single ``kind``.

    In a multi-repo project, also searches sibling repos and groups results
    by repo so you can see where the symbol lives across the whole project —
    ``scope='project'`` searches every repo equally instead of just a taste.
    """
    capped = max(1, min(limit, 50))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None
        sibling_paths: list[str] = []
        if project_id is not None:
            pairs = await proj_svc.get_project_workspaces(db, project_id)
            sibling_paths = [
                ws.path for _, ws in pairs if str(ws.id) != str(workspace_id)
            ]

        if scope == "project" and sibling_paths:
            results = await svc.search_across_workspaces(
                db,
                workspace_paths=[str(get_sandbox().workspace_root), *sibling_paths],
                query=query,
                kind=kind,
                limit_per_workspace=capped,
            )
            if not results:
                return f"No symbols matched '{query}' in any repo of this project."
            grouped: dict[str, list[CodeNode]] = {}
            for path, _ws_id, node in results:
                grouped.setdefault(path, []).append(node)
            total = sum(len(v) for v in grouped.values())
            header = f"Found {total} symbol(s) for '{query}' across {len(grouped)} repo(s):"
            sections = []
            for path, repo_nodes in grouped.items():
                label = Path(path).name or path
                lines = "\n".join(
                    f"  {i}. [{n.kind}] {n.qualified_name} — {_loc(n)}"
                    for i, n in enumerate(repo_nodes, start=1)
                )
                sections.append(f"{label} ({path}):\n{lines}")
            return f"{header}\n" + "\n\n".join(sections)

        nodes = await svc.search_nodes(
            db, workspace_id=workspace_id, query=query, kind=kind, limit=capped
        )
        cross_repo_nodes: list[tuple[str, UUID, CodeNode]] = []
        if sibling_paths:
            cross_repo_nodes = await svc.search_across_workspaces(
                db,
                workspace_paths=sibling_paths,
                query=query,
                kind=kind,
                limit_per_workspace=min(capped, 5),
            )

    no_siblings_note = (
        "\n\n(scope='project' requested, but this workspace has no sibling "
        "repos to search — showing active-repo results only.)"
        if scope == "project" and not sibling_paths
        else ""
    )

    if not nodes and not cross_repo_nodes:
        return f"No symbols matched '{query}'.{no_siblings_note}"

    sections: list[str] = []
    if nodes:
        header = f"Active repo — {len(nodes)} hit(s) for '{query}':"
        body = "\n".join(_node_line(i, n) for i, n in enumerate(nodes, start=1))
        sections.append(f"{header}\n{body}")

    if cross_repo_nodes:
        grouped: dict[str, list[CodeNode]] = {}
        for path, _ws_id, node in cross_repo_nodes:
            grouped.setdefault(path, []).append(node)
        for path, repo_nodes in grouped.items():
            label = Path(path).name or path
            lines = "\n".join(
                f"  {i}. [{n.kind}] {n.qualified_name} — {_loc(n)}"
                for i, n in enumerate(repo_nodes, start=1)
            )
            sections.append(f"{label} ({path}):\n{lines}")

    return "\n\n".join(sections) + no_siblings_note


async def _code_symbol(
    name: Annotated[
        str, Field(description="Exact symbol name or fully qualified name.")
    ],
    cross_repo_limit: Annotated[
        int,
        Field(description="Maximum cross-repo references to show per match (max 30)."),
    ] = 10,
    scope: Annotated[
        Literal["workspace", "project"],
        Field(
            description=(
                "'workspace' (default) resolves the symbol in the active repo only. "
                "'project' ALSO searches sibling repos in a multi-repo project — "
                "required to resolve a symbol that lives in a different repo than "
                "the active one. If a lookup with the default scope reports no "
                "match in a multi-repo project, retry with scope='project' before "
                "concluding the symbol doesn't exist anywhere."
            )
        ),
    ] = "workspace",
) -> str:
    """Look up a symbol by exact name or qualified name and summarise it.

    Returns the symbol's kind, location, signature, docstring (truncated), and
    a one-line tally (max 15 each) of its direct relationships (what it calls,
    who calls it, what it inherits) — a preview, not the full list. For the
    full outbound list use code_neighbors; for the full inbound list use
    code_references. In a multi-repo project, resolved cross-repo references
    pointing at this symbol are always shown (capped by cross_repo_limit,
    default 10, max 30); scope='project' additionally searches sibling repos
    to resolve the symbol itself when it isn't found in the active workspace —
    the default scope='workspace' cannot see a symbol that lives only in a
    sibling repo, so "not found" under the default scope does not mean the
    symbol doesn't exist in the project.
    """
    capped_cross_repo = max(0, min(cross_repo_limit, 30))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        if scope == "project":
            matches = await _resolve_name_anywhere_in_project(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                name=name,
                local_limit=10,
                sibling_limit=10,
            )
        else:
            matches = [
                (workspace_id, n)
                for n in await svc.find_nodes_by_name(
                    db, workspace_id=workspace_id, name=name, limit=10
                )
            ]
        if not matches:
            return _not_found_message(name, scope=scope, project_id=project_id)

        repo_labels = await _label_foreign_workspaces(db, workspace_id, matches)
        sections: list[str] = []
        for match_ws_id, node in matches:
            out_edges = await svc.get_neighbors(
                db, workspace_id=match_ws_id, node_id=node.id, direction="out"
            )
            in_edges = await svc.get_neighbors(
                db, workspace_id=match_ws_id, node_id=node.id, direction="in"
            )
            cross_repo = await _find_cross_repo_references(db, project_ids, node.id)
            sections.append(
                _render_symbol(
                    node,
                    out_edges,
                    in_edges,
                    cross_repo,
                    repo_label=repo_labels.get(match_ws_id),
                    cross_repo_limit=capped_cross_repo,
                )
            )
    return "\n\n".join(sections)


def _render_symbol(
    node: CodeNode,
    out_edges: list[tuple[str, CodeNode]],
    in_edges: list[tuple[str, CodeNode]],
    cross_repo: Sequence[tuple[CrossRepoEdge, str]] = (),
    repo_label: str | None = None,
    cross_repo_limit: int = 10,
) -> str:
    lines = [
        f"[{repo_label}] [{node.kind}] {node.qualified_name}"
        if repo_label
        else f"[{node.kind}] {node.qualified_name}",
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
    if cross_repo:
        lines.append(f"  cross-repo refs ({len(cross_repo)}):")
        for edge, repo_label in cross_repo[:cross_repo_limit]:
            loc = (
                f"{edge.src_file_path}:{edge.src_line}"
                if edge.src_line
                else edge.src_file_path
            )
            lines.append(f"    ← {repo_label}/{loc} (`{edge.raw_reference}`)")
        extra = len(cross_repo) - cross_repo_limit
        if extra > 0:
            lines.append(f"    … and {extra} more (raise cross_repo_limit to see more)")
    return "\n".join(lines)


async def _code_neighbors(
    name: Annotated[str, Field(description="Symbol name or qualified name to expand.")],
    edge_kind: Annotated[
        Literal["calls", "inherits", "implements", "contains", "imports"] | None,
        Field(description="Restrict to a single relationship kind."),
    ] = None,
    limit: Annotated[
        int, Field(description="Maximum neighbours to return per symbol (max 100).")
    ] = _MAX_NEIGHBORS,
    scope: Annotated[
        Literal["workspace", "project"],
        Field(
            description=(
                "'workspace' (default) resolves the symbol in the active repo only. "
                "'project' also searches sibling repos in a multi-repo project when "
                "the symbol isn't found locally."
            )
        ),
    ] = "workspace",
) -> str:
    """List a symbol's OUTBOUND graph neighbours — what it calls, extends,
    implements, imports, or contains — one hop out.

    For INBOUND usage (who calls/imports/extends it), use code_references
    instead. Optionally filter to a single edge_kind. Imports are a
    file-level concept: requesting edge_kind='imports' for a class or method
    transparently reports the containing file's imports instead of an empty
    result. In a multi-repo project, resolved cross-repo references pointing
    at this symbol are always shown; scope='project' additionally searches
    sibling repos to resolve the symbol itself when it isn't found in the
    active workspace.
    """
    capped = max(1, min(limit, 100))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        if scope == "project":
            matches = await _resolve_name_anywhere_in_project(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                name=name,
                local_limit=5,
                sibling_limit=5,
            )
        else:
            matches = [
                (workspace_id, n)
                for n in await svc.find_nodes_by_name(
                    db, workspace_id=workspace_id, name=name, limit=5
                )
            ]
        if not matches:
            return _not_found_message(name, scope=scope, project_id=project_id)

        repo_labels = await _label_foreign_workspaces(db, workspace_id, matches)
        sections: list[str] = []
        for match_ws_id, node in matches:
            query_node_id = node.id
            note: str | None = None
            if edge_kind == "imports" and node.kind != "file":
                # Import edges are attached to the file node, not to whatever
                # class/method textually contains the import statement — a
                # class-level lookup would otherwise always report "no
                # matching neighbours" even though the file plainly imports.
                file_node = await svc.find_file_node(
                    db, workspace_id=match_ws_id, file_path=node.file_path
                )
                if file_node is not None:
                    query_node_id = file_node.id
                    note = f"imports are file-level — showing {file_node.file_path}'s imports"
            neighbours = await svc.get_neighbors(
                db,
                workspace_id=match_ws_id,
                node_id=query_node_id,
                direction="out",
                edge_kind=edge_kind,
            )
            cross_repo = await _find_cross_repo_references(db, project_ids, node.id)
            sections.append(
                _render_neighbors(
                    node,
                    neighbours,
                    cross_repo,
                    repo_label=repo_labels.get(match_ws_id),
                    limit=capped,
                    note=note,
                )
            )
    return "\n\n".join(sections)


async def _label_foreign_workspaces(
    db: AsyncSession, active_workspace_id: UUID, matches: list[tuple[UUID, CodeNode]]
) -> dict[UUID, str]:
    """Repo directory-name labels for any match NOT in the active workspace.

    Used to annotate sibling-repo hits so ``scope='project'`` output makes
    clear which repo a symbol came from — matches in the active workspace
    need no label and are omitted from the returned map.
    """
    foreign_ids = {ws_id for ws_id, _ in matches if ws_id != active_workspace_id}
    if not foreign_ids:
        return {}
    workspaces = (
        await db.exec(select(CodingWorkspace).where(col(CodingWorkspace.id).in_(foreign_ids)))
    ).all()
    return {ws.id: (ws.name or Path(ws.path).name) for ws in workspaces}


def _render_neighbors(
    node: CodeNode,
    neighbours: list[tuple[str, CodeNode]],
    cross_repo: Sequence[tuple[CrossRepoEdge, str]] = (),
    repo_label: str | None = None,
    limit: int = _MAX_NEIGHBORS,
    note: str | None = None,
) -> str:
    head = f"[{node.kind}] {node.qualified_name} — {_loc(node)}"
    if repo_label:
        head = f"[{repo_label}] {head}"
    if note:
        head += f"\n  ({note})"
    if not neighbours and not cross_repo:
        return f"{head}\n  (no matching neighbours)"
    rows = [
        f"  {kind} → [{n.kind}] {n.qualified_name} — {_loc(n)}"
        for kind, n in neighbours[:limit]
    ]
    extra = len(neighbours) - limit
    if extra > 0:
        rows.append(f"  … and {extra} more")
    if cross_repo:
        rows.append("  Cross-repo:")
        for edge, repo_label in cross_repo[:10]:
            loc = (
                f"{edge.src_file_path}:{edge.src_line}"
                if edge.src_line
                else edge.src_file_path
            )
            rows.append(f"    → {repo_label}/{loc} (`{edge.raw_reference}`)")
    return head + "\n" + "\n".join(rows)


async def _code_overview() -> str:
    """Summarise the indexed codebase: totals, languages, and densest files.

    In a multi-repo project, shows a per-repo breakdown plus cross-repo edge
    statistics so you can see the full project picture.
    """
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        if project_ids:
            project_id = project_ids[0]
            overviews = await svc.get_project_overview(db, project_id=project_id)
            if len(overviews) > 1:
                sections: list[str] = []
                total_nodes = 0
                total_edges = 0
                for path, ov in overviews.items():
                    label = Path(path).name or path
                    total_nodes += ov.node_count
                    total_edges += ov.edge_count
                    kinds = ", ".join(
                        f"{k}={v}" for k, v in sorted(ov.kind_counts.items())
                    )
                    sections.append(
                        f"  {label}: {ov.node_count} nodes, {ov.edge_count} edges, "
                        f"{ov.file_count} files — {kinds}"
                    )
                header = (
                    f"Project overview: {total_nodes} nodes, {total_edges} edges "
                    f"across {len(overviews)} repos:"
                )
                return header + "\n" + "\n".join(sections)

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
        "file bodies — fast, token-cheap code location. scope='workspace' "
        "(default) searches the active repo plus a light taste of sibling repos "
        "in a multi-repo project; scope='project' searches every repo equally "
        "when the active repo alone is not enough."
    ),
    concurrency_safe=True,
    read_only=True,
)

code_symbol = Tool(
    _code_symbol,
    name="code_symbol",
    description=(
        "Summarise a single symbol from the code graph: signature, docstring, "
        "and a short preview of its direct callers/callees/base types (max 15 "
        "each). Use before opening a file. For the full outbound list use "
        "code_neighbors; for the full inbound list use code_references. "
        "cross_repo_limit caps cross-repo references shown per match (default "
        "10, max 30). scope='project' also searches sibling repos in a "
        "multi-repo project."
    ),
    concurrency_safe=True,
    read_only=True,
)

code_neighbors = Tool(
    _code_neighbors,
    name="code_neighbors",
    description=(
        "List a symbol's OUTBOUND graph neighbours — what it calls, extends, "
        "implements, imports, or contains — one hop out. Use to trace what a "
        "symbol depends on. For INBOUND usage (who calls/imports/extends it), "
        "use code_references instead. `limit` caps how many neighbours are "
        "returned per symbol (default 40, max 100) — lower it for symbols "
        "with a large fan-out. edge_kind='imports' resolves to the "
        "containing file's imports when the symbol itself isn't a file. "
        "scope='project' also searches sibling repos in a multi-repo "
        "project."
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
    scope: Annotated[
        Literal["workspace", "project"],
        Field(
            description=(
                "'workspace' (default) resolves the symbol in the active repo only. "
                "'project' also searches sibling repos in a multi-repo project when "
                "the symbol isn't found locally."
            )
        ),
    ] = "workspace",
) -> str:
    """Find all INBOUND usages of a symbol: callers, importers, subclasses,
    decorators.

    The canonical answer to "where is X used?" / "what breaks if I change
    X?" — without grepping. Returns each reference as
    ``[edge_kind] source_symbol — file:line``. Resolves by exact name or
    qualified name. In a multi-repo project, resolved cross-repo references
    pointing at this symbol are always shown, sharing the same ``limit``
    budget as same-repo references (intra-repo hits are spent first);
    scope='project' additionally searches sibling repos to resolve the
    symbol itself when it isn't found in the active workspace.
    """
    capped = max(1, min(limit, 60))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED
        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        project_id = project_ids[0] if project_ids else None

        if scope == "project":
            matches = await _resolve_name_anywhere_in_project(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                name=name,
                local_limit=5,
                sibling_limit=5,
            )
        else:
            matches = [
                (workspace_id, n)
                for n in await svc.find_nodes_by_name(
                    db, workspace_id=workspace_id, name=name, limit=5
                )
            ]
        if not matches:
            return _not_found_message(name, scope=scope, project_id=project_id)

        # A symbol can also be the resolution target of a cross-repo reference
        # from a sibling repo in the same project — surface those alongside
        # same-repo references so "where is X used?" covers the whole project
        # even in workspace scope.
        repo_labels = await _label_foreign_workspaces(db, workspace_id, matches)
        sections: list[str] = []
        for match_ws_id, node in matches:
            refs = await svc.find_references(
                db, workspace_id=match_ws_id, node_id=node.id, limit=capped
            )
            # limit is a combined budget across intra- and cross-repo refs —
            # only spend what find_references' own limit left unused, so a
            # low intra-repo count doesn't get topped off with an unbounded
            # cross-repo dump.
            cross_repo_all = await _find_cross_repo_references(db, project_ids, node.id)
            cross_repo = cross_repo_all[: max(0, capped - len(refs))]
            sections.append(
                _render_references(
                    node,
                    refs,
                    cross_repo,
                    repo_label=repo_labels.get(match_ws_id),
                    cross_repo_total=len(cross_repo_all),
                )
            )
    return "\n\n".join(sections)


async def _resolve_name_anywhere_in_project(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID | None,
    name: str,
    local_limit: int,
    sibling_limit: int,
) -> list[tuple[UUID, CodeNode]]:
    """Resolve ``name`` in the active workspace; only on a miss, and only if
    this workspace belongs to a project, fall back to searching every sibling
    repo. Local matches take priority and are returned alone when present —
    cross-repo fallback is last-resort, not merged with local results, so a
    same-name local symbol is never shadowed by a same-name sibling symbol.
    """
    matches = await svc.find_nodes_by_name(
        db, workspace_id=workspace_id, name=name, limit=local_limit
    )
    if matches:
        return [(workspace_id, n) for n in matches]
    if project_id is None:
        return []
    sibling_paths = await proj_svc.get_project_workspace_paths(db, project_id)
    found = await svc.search_across_workspaces(
        db, workspace_paths=sibling_paths, query=name, limit_per_workspace=sibling_limit
    )
    return [(ws_id, node) for _path, ws_id, node in found]


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
    repo_label: str | None = None,
    cross_repo_total: int | None = None,
) -> str:
    head = f"References to [{node.kind}] {node.qualified_name} — {_loc(node)}"
    if repo_label:
        head = f"[{repo_label}] {head}"
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
    hidden = (cross_repo_total or 0) - len(cross_repo)
    if hidden > 0:
        rows.append(f"  … and {hidden} more cross-repo ref(s) not shown (raise limit to see more)")
    return head + f" ({total} refs)\n" + "\n".join(rows)


code_references = Tool(
    _code_references,
    name="code_references",
    description=(
        "Find all INBOUND usages of a symbol: callers, importers, subclasses, "
        "decorators. The canonical answer to 'where is X used?' / 'what breaks "
        "if I change X?' — without grepping. `limit` bounds the combined "
        "intra-repo + cross-repo total, not just intra-repo. scope='project' "
        "also searches sibling repos in a multi-repo project."
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
    scope: Annotated[
        Literal["workspace", "project"],
        Field(
            description=(
                "'workspace' (default) shows ranked symbols from the active repo only. "
                "'project' aggregates across all repos in a multi-repo project."
            )
        ),
    ] = "workspace",
) -> str:
    """Produce a ranked map of the most-referenced symbols in the codebase.

    Symbols are ranked by usage count (in-degree) — the more a function/class
    is called or referenced, the higher it ranks. In a multi-repo project,
    ``scope='project'`` ranks across all repos in the project.
    """
    capped = max(1, min(budget, 50))
    async with async_session_factory() as db:
        workspace_id = await _resolve_workspace(db)
        if workspace_id is None:
            return _NOT_INDEXED

        project_ids = await proj_svc.get_projects_for_workspace(db, workspace_id)
        if scope == "project" and project_ids:
            project_id = project_ids[0]
            pairs = await proj_svc.get_project_workspaces(db, project_id)
            all_ranked: list[tuple[CodeNode, int]] = []
            for _link, ws in pairs:
                # `ws` is already the resolved CodingWorkspace row — no need
                # to round-trip its id through a path lookup.
                ranked = await svc.get_ranked_symbols(
                    db, workspace_id=ws.id, budget=capped
                )
                for node, count in ranked:
                    all_ranked.append((node, count))
            all_ranked.sort(key=lambda x: x[1], reverse=True)
            all_ranked = all_ranked[:capped]
            if all_ranked:
                header = f"Top {len(all_ranked)} symbols by usage across project:"
                rows = [
                    f"{i}. [{node.kind}] {node.qualified_name} — {_loc(node)}  (refs: {count})"
                    + (f"\n   sig: {node.signature}" if node.signature else "")
                    for i, (node, count) in enumerate(all_ranked, start=1)
                ]
                return header + "\n" + "\n".join(rows)

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

        src_matches = await _resolve_name_anywhere_in_project(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            name=source,
            local_limit=3,
            sibling_limit=3,
        )
        if not src_matches:
            return f"No symbol named '{source}' in the code index."

        dst_matches = await _resolve_name_anywhere_in_project(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            name=target,
            local_limit=3,
            sibling_limit=3,
        )
        if not dst_matches:
            return f"No symbol named '{target}' in the code index."

        # Try all combinations (usually 1×1), return the first REAL path
        # found. A combination that resolves to the same node on both sides
        # (possible when the sibling-repo fallback's substring search returns
        # more than one candidate, e.g. "RestHelperService" also matching
        # "RestHelperServiceImpl") is degenerate, not an answer — defer it
        # and keep trying other combinations instead of reporting "same
        # symbol" while a real path between two genuinely different
        # candidates was never attempted.
        same_symbol: tuple[CodeNode, CodeNode] | None = None
        for src_ws_id, src_node in src_matches:
            for dst_ws_id, dst_node in dst_matches:
                if src_node.id == dst_node.id:
                    if same_symbol is None:
                        same_symbol = (src_node, dst_node)
                    continue
                # src_ws_id is wherever THIS candidate actually resolved to —
                # not necessarily the active session workspace — the BFS
                # must seed from the symbol's own workspace or its very
                # first iteration queries the wrong repo's edges and finds
                # nothing (see find_shortest_path's src_workspace_id doc).
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
