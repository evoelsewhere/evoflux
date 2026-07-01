"""Tier B cross-repo resolution: FTS5-narrowed candidates + LLM fallback.

Runs only on rows Tier A (``cross_repo.py``) left unresolved. Always tries
lexical (FTS5) matching first — free, reuses each sibling repo's existing
full-text index from its normal reindex — and only reaches for an LLM call
when a reference is still ambiguous after that, and only when a model is
actually configured (there's no "current session" to inherit a model from
here — this runs as a project-level background job, not inside an agent
turn).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from uuid import UUID

from loguru import logger
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.providers.factory import build_provider
from app.agent.schemas.chat import ChatMessage, HumanMessage, SystemMessage
from app.core.db import current_sqlite_path
from app.core.runtime_settings import load_runtime_settings
from app.models.code_graph import CodeNode, CrossRepoEdge
from app.services.code_graph import cross_repo, fts_store
from app.services.coding_project_service import get_project_workspaces

_LLM_TIMEOUT = 30  # seconds per batch call

_SYSTEM_PROMPT = """\
You are resolving cross-repository code references. For each numbered \
reference, decide which (if any) of its lettered candidate symbols is the \
one actually being referenced.

Output ONE line per reference, in order, in exactly this format:
  <n>: MATCH <letter> <confidence 0-100>
or, if none of the candidates are a plausible match:
  <n>: NONE

Rules:
- Only output MATCH when reasonably confident — a wrong guess is worse than NONE.
- Output only the result lines. No explanations, no other text.
"""

_RESULT_LINE_RE = re.compile(
    r"^\s*(\d+)\s*:\s*(?:MATCH\s+([A-Za-z])\s+(\d{1,3})|NONE)\s*$", re.IGNORECASE
)

_CandidateBatchItem = tuple[CrossRepoEdge, list[tuple[CodeNode, UUID]]]


@dataclass(frozen=True, slots=True)
class TierBStats:
    lexical_resolved: int = 0
    llm_resolved: int = 0


async def resolve_project_tier_b(
    db: AsyncSession,
    *,
    project_id: UUID,
    llm_model: str | None = None,
) -> TierBStats:
    """Lexically narrow (FTS5), then LLM-resolve, whatever Tier A left unresolved.

    ``llm_model`` overrides ``CrossRepoSettings.llm_model`` for this call —
    the API route accepts it per-request since there's no session context to
    default to here. If neither is set, the LLM step is skipped (lexical
    resolution still runs).
    """
    cfg = load_runtime_settings().cross_repo
    if not cfg.enabled:
        return TierBStats()

    pairs = await get_project_workspaces(db, project_id)
    workspace_ids = {ws.id for _, ws in pairs}
    if len(workspace_ids) < 2:
        return TierBStats()

    rows = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.project_id) == project_id,
                col(CrossRepoEdge.status) == "unresolved",
            )
        )
    ).all()
    if not rows:
        return TierBStats()

    db_path = current_sqlite_path()
    lexical_resolved = 0
    still_ambiguous: list[_CandidateBatchItem] = []

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

        if not candidates:
            continue  # nothing for the LLM to choose among — leave unresolved

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
        elif cfg.llm_enabled:
            still_ambiguous.append((row, candidates[: cfg.candidate_k]))

    llm_resolved = 0
    if still_ambiguous:
        model = llm_model or cfg.llm_model
        if model:
            llm_resolved = await _resolve_with_llm(
                still_ambiguous, model=model, batch_size=cfg.llm_batch_size
            )
            for row, _candidates in still_ambiguous:
                db.add(row)
        else:
            logger.info(
                "cross_repo tier_b llm skipped project={} reason=no_model_configured",
                project_id,
            )

    await db.commit()
    return TierBStats(lexical_resolved=lexical_resolved, llm_resolved=llm_resolved)


def _build_batch_prompt(batch: list[_CandidateBatchItem]) -> str:
    lines: list[str] = []
    for i, (row, candidates) in enumerate(batch, start=1):
        lines.append(f"{i}. Reference: `{row.raw_reference}` (kind={row.kind})")
        if row.src_file_path:
            lines.append(f"   Found in: {row.src_file_path}")
        for j, (node, _ws_id) in enumerate(candidates):
            letter = chr(ord("a") + j)
            sig = f" — {node.signature}" if node.signature else ""
            lines.append(f"   {letter}) [{node.kind}] {node.qualified_name}{sig}")
        lines.append("")
    return "\n".join(lines)


async def _resolve_with_llm(
    batch_items: list[_CandidateBatchItem],
    *,
    model: str,
    batch_size: int,
) -> int:
    try:
        provider = build_provider(model)
    except ValueError as exc:
        logger.warning(
            "cross_repo tier_b llm provider unavailable model={} err={}", model, exc
        )
        return 0

    resolved = 0
    for start in range(0, len(batch_items), max(1, batch_size)):
        batch = batch_items[start : start + max(1, batch_size)]
        messages: list[ChatMessage] = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_batch_prompt(batch)),
        ]
        try:
            async with asyncio.timeout(_LLM_TIMEOUT):
                result = await provider.chat(
                    messages, max_tokens=400, temperature=0, thinking_level="none"
                )
        except Exception as exc:  # noqa: BLE001 — one bad batch shouldn't kill the pass
            logger.warning("cross_repo tier_b llm batch failed err={}", exc)
            continue

        for line in (result.content or "").splitlines():
            match = _RESULT_LINE_RE.match(line)
            if not match:
                continue
            idx = int(match.group(1)) - 1
            if idx < 0 or idx >= len(batch):
                continue
            letter = match.group(2)
            if letter is None:
                continue  # NONE
            row, candidates = batch[idx]
            letter_idx = ord(letter.lower()) - ord("a")
            if letter_idx < 0 or letter_idx >= len(candidates):
                continue
            node, ws_id = candidates[letter_idx]
            row.status = "resolved"
            row.method = "llm"
            row.confidence = int(match.group(3)) / 100.0
            row.dst_workspace_id = ws_id
            row.dst_node_id = node.id
            row.dst_qualified_name = node.qualified_name
            row.rationale = f"AI-inferred match (model={model})"
            resolved += 1
    return resolved
