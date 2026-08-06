"""Exact symbol resolution for the native code graph.

This module deliberately does not accept prose and does not use FTS.  The
agent supplies a symbol spelling; the resolver either finds exact graph nodes
or returns a small prefix-only suggestion list.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_graph import CodeNode
from app.services.code_intelligence.models import SymbolMatch, WorkspaceScope


@dataclass(frozen=True, slots=True)
class SymbolResolution:
    matches: tuple[SymbolMatch, ...]
    suggestions: tuple[SymbolMatch, ...]
    total_matches: int = 0


def _selected_scopes(
    scopes: tuple[WorkspaceScope, ...], repository: str | None
) -> tuple[WorkspaceScope, ...]:
    if repository is None:
        return scopes
    wanted = repository.casefold()
    return tuple(
        scope
        for scope in scopes
        if scope.label.casefold() == wanted or scope.root.name.casefold() == wanted
    )


def _path_matches(file_path: str, path: str | None) -> bool:
    if not path:
        return True
    actual = file_path.replace("\\", "/").casefold().strip("/")
    wanted = path.replace("\\", "/").casefold().strip("/")
    return actual == wanted or actual.endswith("/" + wanted) or wanted in actual


def _as_match(
    node: CodeNode,
    scope: WorkspaceScope,
    *,
    symbol: str,
    suggestion: bool = False,
) -> SymbolMatch:
    if suggestion:
        resolution = "suggestion"
    elif node.qualified_name == symbol:
        resolution = "qualified"
    elif node.name == symbol:
        resolution = "name"
    else:
        resolution = "casefold"
    return SymbolMatch(node=node, scope=scope, resolution=resolution)


async def resolve_symbol(
    db: AsyncSession,
    *,
    scopes: tuple[WorkspaceScope, ...],
    symbol: str,
    path: str | None = None,
    repository: str | None = None,
    match_limit: int = 12,
    suggestion_limit: int = 12,
) -> SymbolResolution:
    """Resolve a raw identifier or qualified symbol across authorized repos."""
    selected = _selected_scopes(scopes, repository)
    if not selected:
        return SymbolResolution((), ())
    workspace_ids = [scope.workspace_id for scope in selected]
    folded = symbol.casefold()
    exact_rows = list(
        (
            await db.exec(
                select(CodeNode).where(
                    col(CodeNode.workspace_id).in_(workspace_ids),
                    CodeNode.kind != "file",
                    or_(
                        CodeNode.name == symbol,
                        CodeNode.qualified_name == symbol,
                        sa.func.lower(CodeNode.name) == folded,
                        sa.func.lower(CodeNode.qualified_name) == folded,
                    ),
                )
            )
        ).all()
    )
    exact_rows = [node for node in exact_rows if _path_matches(node.file_path, path)]

    # A qualified spelling is an explicit disambiguator.  An unqualified name
    # intentionally returns every exact definition rather than silently
    # choosing whichever repository happened to sort first.
    qualified_request = any(separator in symbol for separator in (".", "::", "/"))
    if qualified_request:
        strongest = [node for node in exact_rows if node.qualified_name == symbol]
    else:
        strongest = [node for node in exact_rows if node.name == symbol]
    if not strongest:
        strongest = [
            node
            for node in exact_rows
            if node.name.casefold() == folded
            or node.qualified_name.casefold() == folded
        ]

    by_workspace = {scope.workspace_id: scope for scope in selected}
    strongest.sort(
        key=lambda node: (
            by_workspace[node.workspace_id].label.casefold(),
            node.file_path,
            node.line_start,
            node.qualified_name,
        )
    )
    total = len(strongest)
    matches = tuple(
        _as_match(node, by_workspace[node.workspace_id], symbol=symbol)
        for node in strongest[:match_limit]
    )
    if matches:
        return SymbolResolution(matches, (), total)

    # Suggestions are not traversal roots.  They exist only to let the agent
    # correct a partial or misspelled identifier without turning the graph into
    # natural-language retrieval.
    escaped = folded.replace("%", "\\%").replace("_", "\\_")
    suggestion_rows = list(
        (
            await db.exec(
                select(CodeNode)
                .where(
                    col(CodeNode.workspace_id).in_(workspace_ids),
                    CodeNode.kind != "file",
                    or_(
                        sa.func.lower(CodeNode.name).like(f"{escaped}%", escape="\\"),
                        sa.func.lower(CodeNode.qualified_name).like(
                            f"%{escaped}%", escape="\\"
                        ),
                    ),
                )
                .limit(max(40, suggestion_limit * 4))
            )
        ).all()
    )
    suggestion_rows = [
        node for node in suggestion_rows if _path_matches(node.file_path, path)
    ]
    suggestion_rows.sort(
        key=lambda node: (
            0 if node.name.casefold().startswith(folded) else 1,
            len(node.name),
            by_workspace[node.workspace_id].label.casefold(),
            node.file_path,
            node.line_start,
        )
    )
    suggestions = tuple(
        _as_match(
            node,
            by_workspace[node.workspace_id],
            symbol=symbol,
            suggestion=True,
        )
        for node in suggestion_rows[:suggestion_limit]
    )
    return SymbolResolution((), suggestions)
