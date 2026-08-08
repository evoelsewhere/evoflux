"""High-level tool/API boundary for cross-repository code context."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.code_index.models import (
    CodeContextAction,
    CodeContextResult,
    IndexStats,
    RepositoryScope,
)
from app.services.code_index.project import RepositoryIndex, repository_indexes
from app.services.code_index.query import (
    navigate_graph,
    search_index,
    structural_grep,
)
from app.services.code_index.settings import load_project_settings

_GRAPH_ACTIONS: frozenset[str] = frozenset(
    {"definition", "callers", "callees", "references", "impact", "neighborhood"}
)


def _unique_scopes(scopes: tuple[RepositoryScope, ...]) -> tuple[RepositoryScope, ...]:
    output: list[RepositoryScope] = []
    roots: set[Path] = set()
    used_labels: set[str] = set()
    for scope in scopes:
        root = scope.root.expanduser().resolve()
        if root in roots or not root.is_dir():
            continue
        roots.add(root)
        base_label = scope.label.strip() or root.name or str(root)
        label = base_label
        ordinal = 2
        while label.casefold() in used_labels:
            label = f"{base_label}-{ordinal}"
            ordinal += 1
        used_labels.add(label.casefold())
        output.append(RepositoryScope(root=root, label=label))
    return tuple(output)


def _select_scopes(
    scopes: tuple[RepositoryScope, ...], repository: str | None
) -> tuple[RepositoryScope, ...]:
    """Resolve a model-facing selector without expanding authorized scope."""
    if not repository:
        return scopes
    selector = repository.strip()
    if selector in {".", "./", ".\\"}:
        return scopes[:1]
    folded = selector.casefold().rstrip("/\\")
    path: Path | None = None
    candidate = Path(selector).expanduser()
    if candidate.is_absolute():
        try:
            path = candidate.resolve()
        except OSError:
            path = None
    return tuple(
        scope
        for scope in scopes
        if scope.label.casefold() == folded
        or scope.root.name.casefold() == folded
        or (path is not None and scope.root == path)
    )


async def _prepare_indexes(
    scopes: tuple[RepositoryScope, ...],
    *,
    repository: str | None,
    refresh: bool,
) -> tuple[list[tuple[str, RepositoryIndex]], dict[str, IndexStats], list[str]]:
    selected = _unique_scopes(scopes)
    selected = _select_scopes(selected, repository)
    if not selected:
        return [], {}, ["No authorized repository matched the requested scope."]
    indexes = await asyncio.gather(
        *(repository_indexes.get(scope.root) for scope in selected)
    )
    prepared: list[tuple[str, RepositoryIndex]] = []
    stats: dict[str, IndexStats] = {}
    limitations: list[str] = []

    async def prepare(scope: RepositoryScope, index: RepositoryIndex) -> None:
        try:
            value = await index.ensure_ready(refresh=refresh)
        except Exception as exc:
            limitations.append(f"{scope.label}: indexing failed ({exc})")
            return
        prepared.append((scope.label, index))
        stats[scope.label] = value
        limitations.extend(
            f"{scope.label}: {warning}"
            for warning in load_project_settings(scope.root).warnings
        )
        if value.errors:
            preview = "; ".join(f"{path}: {error}" for path, error in value.errors[:5])
            remaining = len(value.errors) - 5
            suffix = f"; and {remaining} more" if remaining > 0 else ""
            limitations.append(
                f"{scope.label}: {len(value.errors)} file(s) kept their last-good "
                f"index after errors ({preview}{suffix})."
            )

    await asyncio.gather(
        *(prepare(scope, index) for scope, index in zip(selected, indexes, strict=True))
    )
    prepared.sort(key=lambda item: item[0].casefold())
    return prepared, stats, limitations


async def query_code_context(
    *,
    scopes: tuple[RepositoryScope, ...],
    action: CodeContextAction,
    query: str,
    repository: str | None = None,
    paths: list[str] | None = None,
    languages: list[str] | None = None,
    depth: int = 1,
    limit: int = 10,
    refresh: bool = True,
) -> CodeContextResult:
    """Refresh authorized indexes, then execute one retrieval or graph action."""
    normalized = query.strip()
    if not normalized:
        raise ValueError("Code-context query cannot be empty.")
    if action in _GRAPH_ACTIONS and any(char.isspace() for char in normalized):
        raise ValueError(
            "Structural graph actions require one exact symbol; use action='search' "
            "to discover it first."
        )
    indexes, stats, limitations = await _prepare_indexes(
        scopes,
        repository=None if action in _GRAPH_ACTIONS else repository,
        refresh=refresh,
    )
    if not indexes:
        return CodeContextResult(
            action=action,
            query=normalized,
            strategy="code-index-unavailable",
            index_version=None,
            repositories=(),
            stats=stats,
            limitations=limitations,
        )
    if action == "search":
        result = await search_index(
            indexes,
            query=normalized,
            languages=languages,
            paths=paths,
            limit=limit,
            stats=stats,
        )
    elif action == "grep":
        result = await structural_grep(
            indexes,
            pattern=normalized,
            languages=languages,
            paths=paths,
            limit=limit,
            stats=stats,
        )
    else:
        graph_repository = repository
        if repository:
            matched = _select_scopes(_unique_scopes(scopes), repository)
            if len(matched) == 1:
                graph_repository = matched[0].label
        result = await navigate_graph(
            indexes,
            symbol=normalized,
            operation=action,
            repository=graph_repository,
            paths=paths,
            depth=depth,
            limit=limit,
            stats=stats,
        )
    result.limitations[:0] = limitations
    return result


__all__ = ["query_code_context"]
