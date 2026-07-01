"""Cross-repo reference resolver.

Turns ``CrossRepoEdge`` rows recorded by the indexer (see
``code_graph_service._persist_unresolved_imports``) from raw, unresolved
import specifiers into links to an actual sibling-repo symbol, in three
tiers of increasing cost:

  Tier 0 — reattach: a previously ``resolved`` row whose ``dst_node_id`` was
    SET NULL by the target repo's own reindex gets re-attached by name,
    cheaper than re-matching from scratch.
  Tier A — static (this module, free): Java fully-qualified-name matching
    plus manifest-identity matching (package.json/pyproject.toml/go.mod/
    Cargo.toml) for the languages that already extract imports.
  Tier B — embedding-narrowed + LLM fallback (a later module) for whatever
    Tier A leaves unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services.code_graph.manifest import (
    PackageManifest,
    match_reference_to_package,
    read_manifests,
)
from app.services.coding_project_service import get_project_workspaces

# Symbol kinds a resolved import may point at.
_ANY_SYMBOL_KINDS = frozenset(
    {"file", "module", "class", "function", "method", "interface", "variable"}
)

METHOD_STATIC_FQN = "static_fqn"
METHOD_STATIC_MANIFEST_EXACT = "static_manifest_exact"
METHOD_STATIC_MANIFEST_PACKAGE = "static_manifest_package"
# No longer produced (the embedding layer was removed in favor of FTS5
# lexical search — see cross_repo_llm.py) — kept only so historical
# CrossRepoEdge rows with this value still deserialize/display correctly.
METHOD_EMBEDDING = "embedding"
METHOD_LEXICAL = "lexical"
METHOD_LLM = "llm"


@dataclass(frozen=True, slots=True)
class CrossRepoResolveStats:
    reattached: int = 0
    static_resolved: int = 0
    lexical_resolved: int = 0
    llm_resolved: int = 0
    still_unresolved: int = 0


@dataclass(frozen=True, slots=True)
class _SiblingRepo:
    workspace_id: UUID
    path: str
    manifests: list[PackageManifest]


async def resolve_project(
    db: AsyncSession,
    *,
    project_id: UUID,
) -> CrossRepoResolveStats:
    """Run Tier 0 (reattach) + Tier A (static) resolution for a project.

    Tier B (embedding + LLM) is a separate, optional pass — see
    ``resolve_project_tier_b`` — so a caller that only wants the free tiers
    (``use_llm=False`` in the API) never pays for it.
    """
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
            workspace_id=ws.id, path=ws.path, manifests=read_manifests(ws.path)
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

    resolved = 0
    for row in rows:
        others = [s for s in siblings.values() if s.workspace_id != row.src_workspace_id]
        if not others:
            continue

        if await _try_resolve_fqn(db, row, others):
            resolved += 1
            continue
        if await _try_resolve_manifest(db, row, others):
            resolved += 1
            continue
        # Left unresolved for Tier B.

    return resolved


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
    db: AsyncSession, row: CrossRepoEdge, others: list[_SiblingRepo]
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
    return False


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
