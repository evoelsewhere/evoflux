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
    suffix: bool = False,
) -> SymbolMatch:
    if suggestion:
        resolution = "suggestion"
    elif suffix:
        resolution = "suffix"
    elif node.qualified_name == symbol:
        resolution = "qualified"
    elif node.name == symbol:
        resolution = "name"
    else:
        resolution = "casefold"
    return SymbolMatch(node=node, scope=scope, resolution=resolution)


def _qualified_suffixes(symbol: str) -> tuple[str, ...]:
    """Storage-compatible suffixes, longest and most specific first.

    Some parsers can derive a package/namespace from source (Java/C#), while
    others intentionally store only the lexical symbol path (Python, Go,
    JavaScript). An agent may still know the full module path. Suffix matching
    bridges those representations deterministically without fuzzy retrieval.
    """
    parts = [part for part in symbol.split(".") if part]
    if len(parts) < 2:
        return ()
    return tuple(".".join(parts[index:]) for index in range(1, len(parts)))


def _module_matches_raw_suffix(
    node: CodeNode, *, requested: str, candidate: str
) -> bool:
    """Guard a bare-name suffix with evidence from the node's source path."""
    if "." in candidate:
        return True
    dropped = requested[: -len(candidate)].rstrip(".").casefold()
    if not dropped:
        return False
    module_path = node.file_path.replace("\\", "/")
    if "." in module_path.rsplit("/", 1)[-1]:
        module_path = module_path.rsplit(".", 1)[0]
    module = module_path.replace("/", ".").strip(".").casefold()
    if module.endswith(".__init__"):
        module = module.removesuffix(".__init__")
    return (
        module == dropped
        or module.endswith(f".{dropped}")
        or dropped.endswith(f".{module}")
    )


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
    # Parsers store a language-neutral dotted qualified name. Accept native
    # qualified spellings such as Rust/C++ ``Type::method`` and PHP namespace
    # separators without forcing callers to know the storage convention.
    canonical_symbol = symbol.replace("::", ".").replace("\\", ".")
    folded = canonical_symbol.casefold()
    exact_rows = list(
        (
            await db.exec(
                select(CodeNode).where(
                    col(CodeNode.workspace_id).in_(workspace_ids),
                    CodeNode.kind != "file",
                    or_(
                        CodeNode.name == canonical_symbol,
                        CodeNode.qualified_name == canonical_symbol,
                    ),
                )
            )
        ).all()
    )
    # The common exact spelling above uses the workspace/name indexes. Only
    # pay for SQLite's non-sargable lower(column) scan when exact case did not
    # match (useful for user-entered symbols in case-sensitive languages).
    if not exact_rows:
        exact_rows = list(
            (
                await db.exec(
                    select(CodeNode).where(
                        col(CodeNode.workspace_id).in_(workspace_ids),
                        CodeNode.kind != "file",
                        or_(
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
    qualified_request = any(separator in symbol for separator in (".", "::", "\\", "/"))
    if qualified_request:
        strongest = [
            node for node in exact_rows if node.qualified_name == canonical_symbol
        ]
    else:
        strongest = [node for node in exact_rows if node.name == canonical_symbol]
    if not strongest:
        strongest = [
            node
            for node in exact_rows
            if node.name.casefold() == folded
            or node.qualified_name.casefold() == folded
        ]

    suffix_match = False
    if not strongest:
        suffixes = _qualified_suffixes(canonical_symbol)
        if suffixes:
            suffix_rows = list(
                (
                    await db.exec(
                        select(CodeNode).where(
                            col(CodeNode.workspace_id).in_(workspace_ids),
                            CodeNode.kind != "file",
                            or_(
                                col(CodeNode.qualified_name).in_(suffixes),
                                CodeNode.name == suffixes[-1],
                            ),
                        )
                    )
                ).all()
            )
            suffix_rows = [
                node for node in suffix_rows if _path_matches(node.file_path, path)
            ]
            for candidate in suffixes:
                strongest = [
                    node
                    for node in suffix_rows
                    if node.qualified_name == candidate
                    and _module_matches_raw_suffix(
                        node, requested=canonical_symbol, candidate=candidate
                    )
                ]
                if strongest:
                    break
            if not strongest:
                strongest = [
                    node
                    for node in suffix_rows
                    if node.name == suffixes[-1]
                    and _module_matches_raw_suffix(
                        node, requested=canonical_symbol, candidate=suffixes[-1]
                    )
                ]
            suffix_match = bool(strongest)

            # Case-insensitive suffix resolution remains a last resort and is
            # only paid for when every indexed exact candidate failed.
            if not strongest:
                folded_suffixes = tuple(item.casefold() for item in suffixes)
                suffix_rows = list(
                    (
                        await db.exec(
                            select(CodeNode).where(
                                col(CodeNode.workspace_id).in_(workspace_ids),
                                CodeNode.kind != "file",
                                or_(
                                    sa.func.lower(CodeNode.qualified_name).in_(
                                        folded_suffixes
                                    ),
                                    sa.func.lower(CodeNode.name) == folded_suffixes[-1],
                                ),
                            )
                        )
                    ).all()
                )
                suffix_rows = [
                    node for node in suffix_rows if _path_matches(node.file_path, path)
                ]
                for candidate in folded_suffixes:
                    strongest = [
                        node
                        for node in suffix_rows
                        if node.qualified_name.casefold() == candidate
                        and _module_matches_raw_suffix(
                            node, requested=canonical_symbol, candidate=candidate
                        )
                    ]
                    if strongest:
                        break
                if not strongest:
                    strongest = [
                        node
                        for node in suffix_rows
                        if node.name.casefold() == folded_suffixes[-1]
                        and _module_matches_raw_suffix(
                            node,
                            requested=canonical_symbol,
                            candidate=folded_suffixes[-1],
                        )
                    ]
                suffix_match = bool(strongest)

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
        _as_match(
            node,
            by_workspace[node.workspace_id],
            symbol=canonical_symbol,
            suffix=suffix_match,
        )
        for node in strongest[:match_limit]
    )
    if matches:
        return SymbolResolution(matches, (), total)

    # Suggestions are not traversal roots.  They exist only to let the agent
    # correct a partial or misspelled identifier without turning the graph into
    # natural-language retrieval.
    suggestion_term = canonical_symbol.rsplit(".", 1)[-1].casefold()
    escaped = suggestion_term.replace("%", "\\%").replace("_", "\\_")
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
            0 if node.name.casefold().startswith(suggestion_term) else 1,
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
            symbol=canonical_symbol,
            suggestion=True,
        )
        for node in suggestion_rows[:suggestion_limit]
    )
    return SymbolResolution((), suggestions)
