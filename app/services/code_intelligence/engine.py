"""Native symbol-first code-graph engine.

The engine synchronizes the persistent parser index, resolves one exact symbol,
and traverses only the requested structural direction.  It never interprets a
user request, performs natural-language ranking, scans source with grep, calls
an LSP, or routes through MCP.
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_graph import CodeIndexState, CrossRepoEdge
from app.services import code_graph_service
from app.services.code_graph.indexer import content_hash, index_format_tag
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph.watcher import (
    flush_code_graph_index,
    get_dirty_code_paths,
    is_code_graph_watcher_active,
)
from app.services.code_intelligence.context import attach_source
from app.services.code_intelligence.models import (
    CodeGraphResult,
    FreshnessPolicy,
    GraphOperation,
    LanguageCapability,
    WorkspaceScope,
)
from app.services.code_intelligence.resolver import resolve_symbol
from app.services.code_intelligence.traversal import traverse_symbol_graph


@dataclass(frozen=True, slots=True)
class PreparedScope:
    scope: WorkspaceScope
    states: tuple[CodeIndexState, ...]
    dirty_paths: frozenset[str]


# A live watcher makes repeated full ``git status`` + content-hash validation
# redundant after one successful check of a given graph snapshot. Keying by
# the stored state fingerprint naturally invalidates this cache after reindex.
_VALIDATED_SNAPSHOTS: dict[UUID, tuple[int, str, str, int]] = {}


def _state_fingerprint(states: tuple[CodeIndexState, ...]) -> tuple[int, str]:
    if not states:
        return (0, "")
    latest = max(state.indexed_at.isoformat() for state in states)
    return (len(states), latest)


async def _states(db: AsyncSession, workspace_id: UUID) -> tuple[CodeIndexState, ...]:
    return tuple(
        (
            await db.exec(
                select(CodeIndexState).where(
                    CodeIndexState.workspace_id == workspace_id
                )
            )
        ).all()
    )


def _git_changed_paths(root: Path) -> frozenset[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    paths: set[str] = set()
    records = result.stdout.decode("utf-8", "replace").split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record or len(record) < 4:
            continue
        status = record[:2]
        path = record[3:].replace("\\", "/")
        paths.add(path)
        if ("R" in status or "C" in status) and index < len(records):
            source = records[index].replace("\\", "/")
            index += 1
            if source:
                paths.add(source)
    return frozenset(paths)


def _git_source_marker(root: Path) -> tuple[str, int]:
    """Cheap cache marker that changes across commits/branch switches."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=2,
            text=True,
        )
        revision = head.stdout.strip() if head.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        revision = ""
    try:
        index_mtime = (root / ".git" / "index").stat().st_mtime_ns
    except OSError:
        index_mtime = 0
    return revision, index_mtime


def _clean_tree_candidates(
    scope: WorkspaceScope, states: tuple[CodeIndexState, ...]
) -> frozenset[str]:
    """Find source paths that can be stale even when ``git status`` is clean.

    A committed edit disappears from ``git status`` but leaves a newer file
    mtime than the stored per-file index timestamp. Missing indexed files are
    always candidates. ``git ls-files`` adds newly committed source files that
    have no state row yet. Only candidates are hashed by ``_index_dirty_paths``.
    """
    indexed = {state.file_path for state in states}
    candidates: set[str] = set()
    for state in states:
        path = scope.root / state.file_path
        try:
            if path.stat().st_mtime > state.indexed_at.timestamp():
                candidates.add(state.file_path)
        except OSError:
            candidates.add(state.file_path)
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=scope.root,
            capture_output=True,
            check=False,
            timeout=3,
        )
        if tracked.returncode == 0:
            registry = default_registry()
            for raw_path in tracked.stdout.decode("utf-8", "replace").split("\0"):
                relative = raw_path.replace("\\", "/")
                if (
                    relative
                    and relative not in indexed
                    and registry.for_path(relative) is not None
                ):
                    candidates.add(relative)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return frozenset(candidates)


def _looks_like_source_path(symbol: str) -> bool:
    normalized = symbol.replace("\\", "/")
    suffix = Path(normalized).suffix.casefold()
    return suffix in default_registry().supported_extensions()


def _index_dirty_paths(
    scope: WorkspaceScope,
    states: tuple[CodeIndexState, ...],
    changed: frozenset[str],
) -> frozenset[str]:
    indexed = {state.file_path: state.content_hash for state in states}
    parser_registry = default_registry()
    dirty: set[str] = set()
    candidates = set(changed)
    if any(not value.startswith(index_format_tag()) for value in indexed.values()):
        candidates.update(indexed)
    if not (scope.root / ".git").exists():
        candidates.update(indexed)
        try:
            candidates.update(
                path.relative_to(scope.root).as_posix()
                for path in scope.root.rglob("*")
                if path.is_file()
                and parser_registry.for_path(path.relative_to(scope.root).as_posix())
                is not None
            )
        except OSError:
            pass
    for relative in candidates:
        path = scope.root / relative
        is_indexable = parser_registry.for_path(relative) is not None
        if not is_indexable and relative not in indexed:
            continue
        expected = indexed.get(relative)
        if not path.is_file():
            if expected is not None:
                dirty.add(relative)
            continue
        if expected is None:
            dirty.add(relative)
            continue
        try:
            if content_hash(path.read_bytes()) != expected:
                dirty.add(relative)
        except OSError:
            dirty.add(relative)
    return frozenset(dirty)


async def prepare_scope(
    db: AsyncSession,
    scope: WorkspaceScope,
    freshness_policy: FreshnessPolicy,
) -> PreparedScope:
    watcher_dirty = get_dirty_code_paths(str(scope.root))
    if watcher_dirty and freshness_policy != "fast":
        await flush_code_graph_index(str(scope.root))
    states = await _states(db, scope.workspace_id)
    if not states:
        await code_graph_service.reindex_workspace(
            db,
            workspace_id=scope.workspace_id,
            root_path=str(scope.root),
            incremental=False,
        )
        states = await _states(db, scope.workspace_id)
    # Processor/schema fingerprints are lifecycle state, not working-tree
    # freshness. Never reuse an incompatible generation, even under the
    # latency-first policy; this is a one-time rebuild after an index upgrade.
    current_format_tag = index_format_tag()
    if any(not state.content_hash.startswith(current_format_tag) for state in states):
        await code_graph_service.reindex_workspace(
            db,
            workspace_id=scope.workspace_id,
            root_path=str(scope.root),
            incremental=True,
        )
        states = await _states(db, scope.workspace_id)
    if freshness_policy == "fast":
        return PreparedScope(scope, states, watcher_dirty)

    state_count, state_latest = _state_fingerprint(states)
    source_revision, source_index_mtime = await asyncio.to_thread(
        _git_source_marker, scope.root
    )
    if (
        freshness_policy == "balanced"
        and is_code_graph_watcher_active()
        and not get_dirty_code_paths(str(scope.root))
        and _VALIDATED_SNAPSHOTS.get(scope.workspace_id)
        == (state_count, state_latest, source_revision, source_index_mtime)
    ):
        return PreparedScope(scope, states, frozenset())
    changed = await asyncio.to_thread(_git_changed_paths, scope.root)
    if (scope.root / ".git").exists():
        changed |= await asyncio.to_thread(_clean_tree_candidates, scope, states)
    dirty = await asyncio.to_thread(_index_dirty_paths, scope, states, changed)
    if dirty and freshness_policy != "fast":
        await code_graph_service.reindex_workspace(
            db,
            workspace_id=scope.workspace_id,
            root_path=str(scope.root),
            incremental=True,
            changed_paths=sorted(dirty),
        )
        states = await _states(db, scope.workspace_id)
        dirty = await asyncio.to_thread(_index_dirty_paths, scope, states, changed)
    if not dirty and is_code_graph_watcher_active():
        state_count, state_latest = _state_fingerprint(states)
        source_revision, source_index_mtime = await asyncio.to_thread(
            _git_source_marker, scope.root
        )
        _VALIDATED_SNAPSHOTS[scope.workspace_id] = (
            state_count,
            state_latest,
            source_revision,
            source_index_mtime,
        )
    return PreparedScope(scope, states, dirty)


async def prepare_scopes(
    db: AsyncSession,
    scopes: Sequence[WorkspaceScope],
    freshness_policy: FreshnessPolicy,
) -> tuple[PreparedScope, ...]:
    """Synchronize authorized repositories for graph and source-index queries."""
    return tuple(
        [await prepare_scope(db, scope, freshness_policy) for scope in scopes]
    )


def _graph_version(prepared: Sequence[PreparedScope]) -> str | None:
    states = [state for item in prepared for state in item.states]
    if not states:
        return None
    digest = hashlib.sha256()
    for state in sorted(states, key=lambda row: (str(row.workspace_id), row.file_path)):
        digest.update(str(state.workspace_id).encode())
        digest.update(state.file_path.encode("utf-8", "replace"))
        digest.update(state.content_hash.encode())
    return digest.hexdigest()[:12]


def _capabilities(prepared: Sequence[PreparedScope]) -> list[LanguageCapability]:
    by_language: dict[str, Counter[str]] = defaultdict(Counter)
    for item in prepared:
        for state in item.states:
            language = state.language or "unknown"
            by_language[language][Path(state.file_path).suffix.casefold()] += 1
    return [
        LanguageCapability(
            language=language,
            extensions=tuple(sorted(extension for extension in counts if extension)),
            graph=True,
            lsp=False,
            indexed_files=sum(counts.values()),
            workspace_files=sum(counts.values()),
        )
        for language, counts in sorted(by_language.items())
    ]


async def _pending_edges(db: AsyncSession, workspace_ids: Sequence[UUID]) -> int:
    if len(workspace_ids) < 2:
        return 0
    values = (
        await db.exec(
            select(CrossRepoEdge.id).where(
                CrossRepoEdge.status == "unresolved",
                or_(
                    col(CrossRepoEdge.src_workspace_id).in_(workspace_ids),
                    col(CrossRepoEdge.dst_workspace_id).in_(workspace_ids),
                ),
            )
        )
    ).all()
    return len(values)


async def navigate_code_graph(
    db: AsyncSession,
    *,
    scopes: tuple[WorkspaceScope, ...],
    symbol: str,
    operation: GraphOperation = "definition",
    path: str | None = None,
    repository: str | None = None,
    depth: int = 1,
    limit: int = 40,
    freshness_policy: FreshnessPolicy = "balanced",
) -> CodeGraphResult:
    """Resolve an exact symbol and navigate its structural relationships."""
    symbol = symbol.strip()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    if any(char.isspace() for char in symbol):
        raise ValueError(
            "code_graph accepts one raw symbol identifier, not a natural-language query."
        )
    if _looks_like_source_path(symbol):
        raise ValueError(
            "code_graph expects a symbol, not a source filename/path. Pass the "
            "raw symbol in `symbol` and use the optional `path` filter to "
            "disambiguate it."
        )
    if not scopes:
        return CodeGraphResult(
            symbol=symbol,
            operation=operation,
            strategy="native-index-unavailable",
            graph_version=None,
            working_tree_revision="unavailable",
            freshness="unavailable",
            matches=[],
            relations=[],
            suggestions=[],
            capabilities=[],
            limitations=["No indexed workspace is available."],
        )

    prepared = await prepare_scopes(db, scopes, freshness_policy)
    active_scopes = tuple(item.scope for item in prepared if item.states)
    version = _graph_version(prepared)
    dirty = frozenset(
        f"{item.scope.label}/{path}" for item in prepared for path in item.dirty_paths
    )
    revision = hashlib.sha256(
        f"{version or 'none'}:{':'.join(sorted(dirty))}".encode()
    ).hexdigest()[:16]
    if not active_scopes:
        return CodeGraphResult(
            symbol=symbol,
            operation=operation,
            strategy="native-index-unavailable",
            graph_version=version,
            working_tree_revision=revision,
            freshness="unavailable",
            matches=[],
            relations=[],
            suggestions=[],
            capabilities=_capabilities(prepared),
            dirty_files=len(dirty),
            limitations=["The native graph index contains no source files."],
        )

    capped_depth = max(1, min(3, depth))
    capped_limit = max(1, min(100, limit))
    resolution = await resolve_symbol(
        db,
        scopes=active_scopes,
        symbol=symbol,
        path=path,
        repository=repository,
    )
    ambiguous = resolution.total_matches > 1
    if ambiguous and operation != "definition":
        # Traversing several same-named roots produces a plausible-looking but
        # semantically mixed answer. Return the definitions as disambiguation
        # evidence and require the caller to choose one exact root first.
        relations = []
        graph_truncated = False
    else:
        relations, graph_truncated = await traverse_symbol_graph(
            db,
            roots=resolution.matches,
            scopes=active_scopes,
            operation=operation,
            depth=capped_depth,
            limit=capped_limit,
        )
    matches, relations, missing, source_truncated = attach_source(
        resolution.matches, relations
    )
    pending = await _pending_edges(db, [scope.workspace_id for scope in active_scopes])
    limitations: list[str] = []
    if dirty:
        limitations.append(
            f"{len(dirty)} changed source file(s) remain outside the graph snapshot."
        )
    if pending:
        limitations.append(
            f"{pending} cross-repository relationship(s) are unresolved."
        )
    if ambiguous and operation != "definition":
        limitations.append(
            f"Symbol resolves to {resolution.total_matches} exact definitions. "
            "Traversal was not executed because combining roots would mix "
            "unrelated relationships; pass a qualified symbol, path, or repository."
        )
    elif resolution.total_matches > len(matches):
        limitations.append(
            f"{resolution.total_matches - len(matches)} additional exact definition(s) "
            "were omitted; pass path or repository to disambiguate."
        )
    elif len(matches) > 1 and path is None and repository is None:
        limitations.append(
            f"Symbol resolves to {len(matches)} exact definitions; pass path or "
            "repository when only one is intended."
        )
    if not matches:
        if resolution.suggestions:
            limitations.append(
                "No exact symbol matched. Prefix suggestions are listed, but were "
                "not traversed."
            )
        else:
            limitations.append("No exact symbol matched the native graph index.")
    elif operation != "definition" and not relations and not ambiguous:
        limitations.append(
            f"No resolved {operation} relationships were indexed for this symbol."
        )
    if missing:
        limitations.append(
            "Complete definitions that exceeded the inline source budget are listed "
            "as ranges."
        )
    cross_repo = len(active_scopes) > 1
    strategy = "native-"
    if cross_repo:
        strategy += "cross-repo-"
    strategy += "exact-symbol-graph"
    return CodeGraphResult(
        symbol=symbol,
        operation=operation,
        strategy=strategy,
        graph_version=version,
        working_tree_revision=revision,
        freshness="partial" if dirty else "fresh",
        matches=matches,
        relations=relations,
        suggestions=list(resolution.suggestions),
        capabilities=_capabilities(prepared),
        dirty_files=len(dirty),
        pending_edges=pending,
        limitations=limitations
        + (["Source ranges: " + ", ".join(missing)] if missing else []),
        truncated=graph_truncated or source_truncated,
    )
