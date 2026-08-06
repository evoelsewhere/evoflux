"""Application facade for native, symbol-first code-graph navigation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_graph import CodeIndexState
from app.services.code_graph.watcher import (
    flush_code_graph_index,
    get_dirty_code_paths,
)
from app.services.code_intelligence.engine import (
    _git_changed_paths,
    _index_dirty_paths,
    navigate_code_graph as _navigate,
)
from app.services.code_intelligence.models import (
    CodeGraphResult,
    FreshnessPolicy,
    GraphOperation,
    LanguageCapability,
    RetrievalFreshness,
    WorkspaceScope,
)


async def navigate_code_graph(
    db: AsyncSession,
    *,
    root_path: str,
    workspace_id: UUID | None,
    symbol: str,
    operation: GraphOperation = "definition",
    path: str | None = None,
    repository: str | None = None,
    depth: int = 1,
    limit: int = 40,
    freshness_policy: FreshnessPolicy = "balanced",
) -> CodeGraphResult:
    workspaces = [(root_path, workspace_id, Path(root_path).name or root_path)]
    return await navigate_code_graph_across_workspaces(
        db,
        workspaces=workspaces,
        symbol=symbol,
        operation=operation,
        path=path,
        repository=repository,
        depth=depth,
        limit=limit,
        freshness_policy=freshness_policy,
    )


async def navigate_code_graph_across_workspaces(
    db: AsyncSession,
    *,
    workspaces: Sequence[tuple[str, UUID | None, str]],
    symbol: str,
    operation: GraphOperation = "definition",
    path: str | None = None,
    repository: str | None = None,
    depth: int = 1,
    limit: int = 40,
    freshness_policy: FreshnessPolicy = "balanced",
) -> CodeGraphResult:
    scopes: list[WorkspaceScope] = []
    seen: set[tuple[Path, UUID]] = set()
    for root_path, workspace_id, label in workspaces:
        if workspace_id is None:
            continue
        root = Path(root_path).expanduser().resolve()
        identity = (root, workspace_id)
        if identity in seen or not root.is_dir():
            continue
        seen.add(identity)
        scopes.append(
            WorkspaceScope(
                root=root,
                workspace_id=workspace_id,
                label=label or root.name or str(root),
            )
        )
    return await _navigate(
        db,
        scopes=tuple(scopes),
        symbol=symbol,
        operation=operation,
        path=path,
        repository=repository,
        depth=depth,
        limit=limit,
        freshness_policy=freshness_policy,
    )


async def _states(
    db: AsyncSession, workspace_id: UUID | None
) -> tuple[CodeIndexState, ...]:
    if workspace_id is None:
        return ()
    return tuple(
        (
            await db.exec(
                select(CodeIndexState).where(
                    CodeIndexState.workspace_id == workspace_id
                )
            )
        ).all()
    )


async def get_capabilities(
    db: AsyncSession, *, root_path: str, workspace_id: UUID | None
) -> list[LanguageCapability]:
    del root_path
    states = await _states(db, workspace_id)
    by_language: dict[str, Counter[str]] = defaultdict(Counter)
    for state in states:
        by_language[state.language or "unknown"][
            Path(state.file_path).suffix.casefold()
        ] += 1
    return [
        LanguageCapability(
            language=language,
            extensions=tuple(sorted(ext for ext in counts if ext)),
            graph=True,
            lsp=False,
            indexed_files=sum(counts.values()),
            workspace_files=sum(counts.values()),
        )
        for language, counts in sorted(by_language.items())
    ]


async def get_freshness(
    db: AsyncSession, *, root_path: str, workspace_id: UUID | None
) -> RetrievalFreshness:
    root = Path(root_path).expanduser().resolve()
    if workspace_id is None:
        return RetrievalFreshness(
            graph_version=None,
            working_tree_revision="unavailable",
            freshness="unavailable",
            indexed_files=0,
            dirty_files=0,
            change_source="native-index",
        )
    if get_dirty_code_paths(str(root)):
        await flush_code_graph_index(str(root))
    states = await _states(db, workspace_id)
    scope = WorkspaceScope(root=root, workspace_id=workspace_id, label=root.name)
    changed = _git_changed_paths(root)
    dirty = _index_dirty_paths(scope, states, changed)
    digest = hashlib.sha256()
    for state in sorted(states, key=lambda item: item.file_path):
        digest.update(state.file_path.encode("utf-8", "replace"))
        digest.update(state.content_hash.encode())
    graph_version = digest.hexdigest()[:12] if states else None
    revision = hashlib.sha256(
        f"{graph_version}:{':'.join(sorted(dirty))}".encode()
    ).hexdigest()[:16]
    return RetrievalFreshness(
        graph_version=graph_version,
        working_tree_revision=revision,
        freshness=("partial" if dirty else "fresh") if states else "unavailable",
        indexed_files=len(states),
        dirty_files=len(dirty),
        change_source="native-index",
    )
