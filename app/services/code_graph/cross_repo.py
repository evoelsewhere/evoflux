"""Cross-repo reference resolver.

Turns ``CrossRepoEdge`` rows recorded by the indexer (see
``code_graph_service._persist_unresolved_references``) from raw, unresolved
import specifiers/type references into links to an actual sibling-repo
symbol, in three tiers of increasing cost:

  Tier 0 — reattach: a previously ``resolved`` row whose ``dst_node_id`` was
    SET NULL by the target repo's own reindex gets re-attached by name,
    cheaper than re-matching from scratch.
  Tier A — static (this module, free), tried in order:
    1. explicit path dependency — the SOURCE repo's own manifest points at a
       sibling by relative path (npm file:/link:/workspace:, uv/poetry
       path=, Go replace, Cargo path=). Unambiguous by construction: no
       cross-sibling search needed, so this is tried before anything else.
    2. Java fully-qualified-name matching.
    3. manifest-identity matching (package.json/pyproject.toml/go.mod/
       Cargo.toml) for the languages that already extract imports.
  Tier B — FTS5 lexical matching (``cross_repo_llm.py``) for whatever Tier A
    leaves unresolved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import sqlite_write_guard
from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services.code_graph.manifest import (
    PackageManifest,
    PathDependency,
    compute_importable_id,
    match_path_dependency,
    match_reference_to_package,
    read_manifests,
    read_path_dependencies,
)
from app.services.code_graph.path_resolve import RepoContext, build_repo_context
from app.services.coding_project_service import get_project_workspaces

# Symbol kinds a resolved import may point at.
_ANY_SYMBOL_KINDS = frozenset(
    {"file", "module", "class", "function", "method", "interface", "variable"}
)

METHOD_STATIC_PATH_DEPENDENCY = "static_path_dependency"
METHOD_STATIC_FQN = "static_fqn"
METHOD_STATIC_MANIFEST_EXACT = "static_manifest_exact"
METHOD_STATIC_MANIFEST_PACKAGE = "static_manifest_package"
# Set when a user/agent manually rejects a row via the API — distinct from
# every resolver-produced method so a rejected row's provenance stays
# visible. Also doubles as a non-NULL sentinel: _persist_unresolved_references'
# reindex-time delete only ever targets ``method IS NULL`` rows, so setting
# this is what makes a rejection survive the source file being reindexed
# again (otherwise it would be wiped and recreated as "unresolved").
METHOD_MANUAL_REJECT = "manual_reject"
# No longer produced (the embedding layer was removed in favor of FTS5
# lexical search — see cross_repo_llm.py) — kept only so historical
# CrossRepoEdge rows with this value still deserialize/display correctly.
METHOD_EMBEDDING = "embedding"
# No longer produced (the LLM fallback layer was removed in favor of pure
# FTS5 lexical search — see cross_repo_llm.py) — kept only so historical
# CrossRepoEdge rows with this value still deserialize/display correctly.
METHOD_LLM = "llm"
METHOD_LEXICAL = "lexical"


@dataclass(frozen=True, slots=True)
class CrossRepoResolveStats:
    reattached: int = 0
    static_resolved: int = 0
    lexical_resolved: int = 0
    still_unresolved: int = 0
    capped: int = 0


@dataclass(frozen=True, slots=True)
class _SiblingRepo:
    workspace_id: UUID
    path: str
    manifests: list[PackageManifest]
    path_dependencies: list[PathDependency]
    layout_hints: RepoContext


async def resolve_project(
    db: AsyncSession,
    *,
    project_id: UUID,
) -> CrossRepoResolveStats:
    """Run Tier 0 (reattach) + Tier A (static) resolution for a project.

    Tier B (FTS5 lexical matching) is a separate pass — see
    ``resolve_project_tier_b``. The caller controls whether it runs through
    the job registry in ``app/services/code_graph/cross_repo_jobs.py``.
    """
    async with sqlite_write_guard():
        reattached = await _reattach_stale(db, project_id=project_id)
        static_resolved = await _resolve_static(db, project_id=project_id)
        remaining = await _count_unresolved(db, project_id=project_id)
        await db.commit()
    return CrossRepoResolveStats(
        reattached=reattached,
        static_resolved=static_resolved,
        still_unresolved=remaining,
    )


async def _count_unresolved(db: AsyncSession, *, project_id: UUID) -> int:
    result = (
        await db.exec(
            select(sa_func.count()).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "unresolved",
            )
        )
    ).one()
    return int(result)


async def _reattach_stale(db: AsyncSession, *, project_id: UUID) -> int:
    """Re-attach ``resolved`` rows whose ``dst_node_id`` went NULL because the
    target repo reindexed — cheap name lookup, no re-matching."""
    rows = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "resolved",
                col(CrossRepoEdge.dst_node_id).is_(None),
                col(CrossRepoEdge.dst_workspace_id).is_not(None),
                col(CrossRepoEdge.dst_qualified_name).is_not(None),
            )
        )
    ).all()
    count = 0
    for row in rows:
        node = (
            await db.exec(
                select(CodeNode).where(
                    col(CodeNode.workspace_id) == row.dst_workspace_id,
                    col(CodeNode.qualified_name) == row.dst_qualified_name,
                )
            )
        ).first()
        if node is not None:
            row.dst_node_id = node.id
            db.add(row)
            count += 1
    return count


async def _load_sibling_repos(
    db: AsyncSession, *, project_id: UUID
) -> dict[UUID, _SiblingRepo]:
    pairs = await get_project_workspaces(db, project_id)
    return {
        ws.id: _SiblingRepo(
            workspace_id=ws.id,
            path=ws.path,
            manifests=read_manifests(ws.path),
            path_dependencies=read_path_dependencies(ws.path),
            layout_hints=build_repo_context(Path(ws.path)),
        )
        for _, ws in pairs
    }


async def _find_node_by_qualified_name(
    db: AsyncSession, *, workspace_id: UUID, qualified_name: str
) -> CodeNode | None:
    candidates = (
        await db.exec(
            select(CodeNode).where(
                col(CodeNode.workspace_id) == workspace_id,
                col(CodeNode.qualified_name) == qualified_name,
                col(CodeNode.kind).in_(_ANY_SYMBOL_KINDS),
            )
        )
    ).all()
    return candidates[0] if len(candidates) == 1 else None


async def _find_node_by_name(
    db: AsyncSession, *, workspace_id: UUID, name: str
) -> CodeNode | None:
    candidates = (
        await db.exec(
            select(CodeNode).where(
                col(CodeNode.workspace_id) == workspace_id,
                col(CodeNode.name) == name,
                col(CodeNode.kind).in_(_ANY_SYMBOL_KINDS),
            )
        )
    ).all()
    return candidates[0] if len(candidates) == 1 else None


async def _resolve_static(db: AsyncSession, *, project_id: UUID) -> int:
    siblings = await _load_sibling_repos(db, project_id=project_id)
    if len(siblings) < 2:
        return 0  # nothing to link against

    rows = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "unresolved",
            )
        )
    ).all()
    if not rows:
        return 0

    # Built once per sibling and reused for every row below. The previous
    # version rebuilt this (a full node fetch + compute_importable_id over
    # every node) inside the per-row fallback, turning an O(siblings * nodes)
    # cost into O(rows * siblings * nodes) — fine on test fixtures with a
    # handful of nodes, but minutes-to-hours on a real project with thousands
    # of unresolved rows against repos with tens of thousands of nodes each.
    importable_indexes = {
        ws_id: await _build_importable_index(db, sibling)
        for ws_id, sibling in siblings.items()
    }

    resolved = 0
    for row in rows:
        others = [
            s for s in siblings.values() if s.workspace_id != row.src_workspace_id
        ]
        if not others:
            continue
        src_repo = siblings.get(row.src_workspace_id)

        if src_repo is not None and await _try_resolve_path_dependency(
            db, row, src_repo, others
        ):
            resolved += 1
            continue
        if src_repo is not None and await _try_resolve_relative_cross_repo(
            db, row, src_repo, others
        ):
            resolved += 1
            continue
        if await _try_resolve_fqn(db, row, others, importable_indexes):
            resolved += 1
            continue
        if await _try_resolve_manifest(db, row, others):
            resolved += 1
            continue
        # Left unresolved for Tier B.

    return resolved


async def _try_resolve_path_dependency(
    db: AsyncSession,
    row: CrossRepoEdge,
    src_repo: _SiblingRepo,
    others: list[_SiblingRepo],
) -> bool:
    """Resolve via an explicit local-path dependency in the SOURCE repo's own
    manifest — the referencing repo's author pointed at this exact sibling
    directory, so there's no cross-sibling ambiguity to resolve, unlike
    ``_try_resolve_manifest``'s identity search.
    """
    dep = match_path_dependency(row.raw_reference, src_repo.path_dependencies)
    if dep is None:
        return False

    target_path = str((Path(src_repo.path) / dep.relative_path).resolve())
    sibling = next(
        (s for s in others if str(Path(s.path).resolve()) == target_path), None
    )
    if sibling is None:
        return False  # sibling not (yet) a member of this project

    node = None
    if row.dst_name_hint:
        node = await _find_node_by_name(
            db, workspace_id=sibling.workspace_id, name=row.dst_name_hint
        )
    if node is not None:
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=node.id,
            dst_qualified_name=node.qualified_name,
            method=METHOD_STATIC_PATH_DEPENDENCY,
            confidence=1.0,
        )
    else:
        # Repo-level link only — still real signal, just not symbol-precise
        # (e.g. a bare package import with no specific member referenced).
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=None,
            dst_qualified_name=dep.alias,
            method=METHOD_STATIC_PATH_DEPENDENCY,
            confidence=0.8,
        )
    db.add(row)
    return True


async def _try_resolve_relative_cross_repo(
    db: AsyncSession,
    row: CrossRepoEdge,
    src_repo: _SiblingRepo,
    others: list[_SiblingRepo],
) -> bool:
    """Resolve a relative import that points at a sibling repo.

    A relative import like ``"../sibling-repo/src/utils"`` that Phase 1
    already tried and failed to resolve *intra*-repo (not in ``known_files``)
    — that failure is itself the "points at a sibling" signal. Resolve the
    relative path from the source file's directory, check whether it falls
    inside any sibling's root, and if so resolve the specific symbol.
    """
    raw = row.raw_reference
    if not raw.startswith("."):
        return False

    src_dir = str(Path(row.src_file_path).parent)
    try:
        target = (Path(src_repo.path) / src_dir / raw).resolve()
    except (OSError, ValueError):
        return False

    sibling = next(
        (
            s
            for s in others
            if str(Path(s.path).resolve()) == target
            or str(Path(s.path).resolve()) in str(target)
        ),
        None,
    )
    if sibling is None:
        # Check if target falls inside any sibling's root.
        for s in others:
            sroot = str(Path(s.path).resolve())
            if str(target).startswith(sroot + os.sep) or str(target).startswith(
                sroot + "/"
            ):
                sibling = s
                break
    if sibling is None:
        return False

    node = None
    if row.dst_name_hint:
        node = await _find_node_by_name(
            db, workspace_id=sibling.workspace_id, name=row.dst_name_hint
        )
    if node is not None:
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=node.id,
            dst_qualified_name=node.qualified_name,
            method=METHOD_STATIC_PATH_DEPENDENCY,
            confidence=1.0,
        )
    else:
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=None,
            dst_qualified_name=None,
            method=METHOD_STATIC_PATH_DEPENDENCY,
            confidence=0.6,
        )
    db.add(row)
    return True


def _fqn_candidates(raw_reference: str) -> list[str]:
    """Reference strings worth trying as an exact qualified_name match.

    A wildcard import ("com.example.qux.*") has no specific symbol to match.
    A Java static-member import ("com.example.Helper.doThing") is
    syntactically identical to a class import, one segment longer — retry
    with the last segment stripped if the full string doesn't match.
    """
    if raw_reference.endswith(".*"):
        return []
    candidates = [raw_reference]
    if "." in raw_reference:
        candidates.append(raw_reference.rsplit(".", 1)[0])
    return candidates


async def _try_resolve_fqn(
    db: AsyncSession,
    row: CrossRepoEdge,
    others: list[_SiblingRepo],
    importable_indexes: dict[UUID, dict[str, CodeNode]] | None = None,
) -> bool:
    for candidate in _fqn_candidates(row.raw_reference):
        matches: list[tuple[_SiblingRepo, CodeNode]] = []
        for sibling in others:
            node = await _find_node_by_qualified_name(
                db, workspace_id=sibling.workspace_id, qualified_name=candidate
            )
            if node is not None:
                matches.append((sibling, node))
        if len(matches) == 1:
            sibling, node = matches[0]
            _stamp_resolved(
                row,
                dst_workspace_id=sibling.workspace_id,
                dst_node_id=node.id,
                dst_qualified_name=node.qualified_name,
                method=METHOD_STATIC_FQN,
                confidence=1.0,
            )
            db.add(row)
            return True

    # Fallback: try generalized importable_id for ecosystems without native
    # FQN support (Python, JS/TS, Go, etc.) — matched against indexes built
    # once per resolve pass (see _resolve_static), not recomputed per row.
    if importable_indexes is not None:
        matches = _find_by_importable_id(row, others, importable_indexes)
        if len(matches) == 1:
            sibling, node = matches[0]
            _stamp_resolved(
                row,
                dst_workspace_id=sibling.workspace_id,
                dst_node_id=node.id,
                dst_qualified_name=node.qualified_name,
                method=METHOD_STATIC_FQN,
                confidence=0.9,
            )
            db.add(row)
            return True

    return False


async def _build_importable_index(
    db: AsyncSession, sibling: _SiblingRepo
) -> dict[str, CodeNode]:
    """Map every node of ``sibling`` to its importable_id, once per resolve pass.

    Recomputing this per unresolved row (the previous shape of this code) is
    what made ``_resolve_static`` scale with ``rows * siblings * nodes``
    instead of ``siblings * nodes`` — see the comment in ``_resolve_static``.
    """
    root_prefix = _get_root_prefix(sibling)
    if not root_prefix:
        return {}
    nodes = (
        await db.exec(
            select(CodeNode).where(
                col(CodeNode.workspace_id) == sibling.workspace_id,
                col(CodeNode.kind).in_(_ANY_SYMBOL_KINDS),
            )
        )
    ).all()
    index: dict[str, CodeNode] = {}
    for node in nodes:
        importable = compute_importable_id(
            node.file_path,
            node.qualified_name,
            language=node.language,
            root_prefix=root_prefix,
        )
        if importable:
            # First node wins on a collision — same tie-break the old
            # per-row DB scan applied (first match in fetch order).
            index.setdefault(importable, node)
    return index


def _importable_id_candidates(raw_reference: str) -> list[str]:
    """``raw_reference`` itself, then progressively shorter dotted prefixes.

    A reference can point at a member of an importable symbol (e.g.
    ``pkg.mod.Class.method`` when the indexed importable_id is
    ``pkg.mod.Class``), so every prefix boundary is a candidate — most
    specific (longest) first.
    """
    parts = raw_reference.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def _find_by_importable_id(
    row: CrossRepoEdge,
    others: list[_SiblingRepo],
    importable_indexes: dict[UUID, dict[str, CodeNode]],
) -> list[tuple[_SiblingRepo, CodeNode]]:
    """Match via each sibling's precomputed importable_id index (Phase 3)."""
    matches: list[tuple[_SiblingRepo, CodeNode]] = []
    candidates = _importable_id_candidates(row.raw_reference)
    for sibling in others:
        index = importable_indexes.get(sibling.workspace_id)
        if not index:
            continue
        for candidate in candidates:
            node = index.get(candidate)
            if node is not None:
                matches.append((sibling, node))
                break
    return matches


def _get_root_prefix(sibling: _SiblingRepo) -> str | None:
    """Get the root prefix for importable_id computation."""
    for m in sibling.manifests:
        if m.ecosystem in ("npm", "python", "go", "cargo"):
            return m.package_name
    # Go module path from layout hints
    if sibling.layout_hints.go_module_path:
        return sibling.layout_hints.go_module_path
    # Python top-level packages
    if sibling.layout_hints.py_top_level_packages:
        return next(iter(sibling.layout_hints.py_top_level_packages))
    return None


async def _try_resolve_manifest(
    db: AsyncSession, row: CrossRepoEdge, others: list[_SiblingRepo]
) -> bool:
    package_matches: list[tuple[_SiblingRepo, PackageManifest]] = []
    for sibling in others:
        match = match_reference_to_package(row.raw_reference, sibling.manifests)
        if match is not None:
            package_matches.append((sibling, match))
    if len(package_matches) != 1:
        return False  # no match, or ambiguous across repos — leave for Tier B

    sibling, package = package_matches[0]
    node = None
    if row.dst_name_hint:
        node = await _find_node_by_name(
            db, workspace_id=sibling.workspace_id, name=row.dst_name_hint
        )
    if node is not None:
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=node.id,
            dst_qualified_name=node.qualified_name,
            method=METHOD_STATIC_MANIFEST_EXACT,
            confidence=0.9,
        )
    else:
        # Repo-level link only — still real signal, just not symbol-precise.
        _stamp_resolved(
            row,
            dst_workspace_id=sibling.workspace_id,
            dst_node_id=None,
            dst_qualified_name=package.package_name,
            method=METHOD_STATIC_MANIFEST_PACKAGE,
            confidence=0.6,
        )
    db.add(row)
    return True


def _stamp_resolved(
    row: CrossRepoEdge,
    *,
    dst_workspace_id: UUID,
    dst_node_id: UUID | None,
    dst_qualified_name: str | None,
    method: str,
    confidence: float,
) -> None:
    row.status = "resolved"
    row.method = method
    row.confidence = confidence
    row.dst_workspace_id = dst_workspace_id
    row.dst_node_id = dst_node_id
    row.dst_qualified_name = dst_qualified_name
