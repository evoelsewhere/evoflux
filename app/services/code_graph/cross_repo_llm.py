"""Tier B cross-repo resolution: FTS5 lexical matching only.

Runs only on rows Tier A (``cross_repo.py``) left unresolved. Each reference is
narrowed with an FTS5 query against every sibling repo's existing full-text
index (built during normal reindexing) and resolved when exactly one candidate
matches the target name or qualified reference. The remainder stays unresolved
for a future pass.

This module intentionally does not call an LLM: the embedding/vector layer was
removed in favor of free lexical search, and the LLM fallback was dropped to
keep cross-repo resolution deterministic, local, and free of provider latency.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import current_sqlite_path
from app.core.runtime_settings import load_runtime_settings
from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services.code_graph import cross_repo, fts_store
from app.services.coding_project_service import get_project_workspaces


@dataclass(frozen=True, slots=True)
class TierBStats:
    lexical_resolved: int = 0
    capped: int = 0


async def resolve_project_tier_b(
    db: AsyncSession,
    *,
    project_id: UUID,
) -> TierBStats:
    """Lexically narrow (FTS5) whatever Tier A left unresolved.

    Bounded by ``CrossRepoSettings.max_rows_per_run`` — even after the
    ``is_likely_external`` pre-filter, a very large or freshly-linked project
    could still have more unresolved rows than are sane to run through FTS5 in
    one pass; the remainder is simply picked up on the next run.
    """
    cfg = load_runtime_settings().cross_repo
    if not cfg.enabled:
        return TierBStats()

    pairs = await get_project_workspaces(db, project_id)
    workspace_ids = {ws.id for _, ws in pairs}
    if len(workspace_ids) < 2:
        return TierBStats()

    all_rows = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "unresolved",
            )
        )
    ).all()
    if not all_rows:
        return TierBStats()
    rows = all_rows[: cfg.max_rows_per_run]
    capped = len(all_rows) - len(rows)
    if capped > 0:
        logger.info(
            "cross_repo tier_b row cap project={} processed={} deferred={}",
            project_id,
            len(rows),
            capped,
        )

    db_path = current_sqlite_path()
    lexical_resolved = 0

    for row in rows:
        others = [wid for wid in workspace_ids if wid != row.src_workspace_id]
        if not others or db_path is None:
            continue

        # Deliberately omit row.kind here (unlike the old embedding query) —
        # FTS5 ANDs every token together, so an extra word like "import"
        # could zero out real matches that don't literally contain it.
        query_text = f"{row.raw_reference} {row.dst_name_hint or ''}".strip()
        if not query_text:
            continue

        candidates: list[tuple[CodeNode, UUID]] = []
        for ws_id in others:
            node_ids = await asyncio.to_thread(
                fts_store.search_fts, db_path, str(ws_id), query_text, cfg.candidate_k
            )
            if not node_ids:
                continue
            nodes = (
                await db.exec(
                    select(CodeNode).where(
                        col(CodeNode.id).in_([UUID(nid) for nid in node_ids])
                    )
                )
            ).all()
            candidates.extend((node, ws_id) for node in nodes)

        target_name = row.dst_name_hint or row.raw_reference.rsplit(".", 1)[-1]
        exact = [
            (node, ws_id)
            for node, ws_id in candidates
            if node.name == target_name or node.qualified_name == row.raw_reference
        ]

        if len(exact) == 1:
            node, ws_id = exact[0]
            row.status = "resolved"
            row.method = cross_repo.METHOD_LEXICAL
            row.confidence = 0.8
            row.dst_workspace_id = ws_id
            row.dst_node_id = node.id
            row.dst_qualified_name = node.qualified_name
            db.add(row)
            lexical_resolved += 1

    await db.commit()
    return TierBStats(
        lexical_resolved=lexical_resolved,
        capped=capped,
    )
