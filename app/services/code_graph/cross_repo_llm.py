"""Tier B cross-repo resolution: FTS5-narrowed candidates + LLM fallback.

Runs only on rows Tier A (``cross_repo.py``) left unresolved. Always tries
lexical (FTS5) matching first — free, reuses each sibling repo's existing
full-text index from its normal reindex — and only reaches for an LLM call
when a reference is still ambiguous after that, and only when a model is
actually configured (there's no "current session" to inherit a model from
here — this runs as a project-level background job, not inside an agent
turn).

The LLM sees more than a bare candidate-symbol list: each batch is prefixed
with every project repo's own manifest identity (npm/pyproject/go.mod/Cargo/
Maven), so it can reason about *which repo* a reference plausibly belongs to
even when lexical search finds nothing (an unindexed symbol, or a reference
that's actually a third-party dependency ``is_likely_external``'s static
pre-filter didn't catch). The response format has a dedicated ``EXTERNAL``
outcome for exactly that last case — the LLM is a second-opinion filter for
noise the static pre-filter missed, not just a symbol matcher.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
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
from app.services.code_graph.manifest import read_manifests
from app.services.coding_project_service import get_project_workspaces

_LLM_TIMEOUT = 30  # seconds per batch call

_SYSTEM_PROMPT = """\
You are resolving cross-repository code references for a multi-repo project. \
For each numbered reference, decide one of three outcomes using the listed \
project repos and, if any, lettered candidate symbols found in them.

Output ONE line per reference, in order, in exactly this format:
  <n>: MATCH <letter> <confidence 0-100>   — one of the candidates IS the referenced symbol
  <n>: EXTERNAL <confidence 0-100>         — this is a third-party/standard-library \
dependency, not part of any repo in this project (e.g. a well-known framework \
or library class that doesn't belong to any listed repo's own identity)
  <n>: NONE                                — neither of the above; not confident enough to say

Rules:
- Only output MATCH when a candidate is reasonably confident to be correct — a wrong guess is worse than NONE.
- Only output EXTERNAL when you recognize the reference as a common third-party dependency, not merely because no candidates were found (an unindexed sibling symbol also has no candidates — prefer NONE when unsure).
- Output only the result lines. No explanations, no other text.
"""

_RESULT_LINE_RE = re.compile(
    r"^\s*(\d+)\s*:\s*(?:MATCH\s+([A-Za-z])\s+(\d{1,3})"
    r"|EXTERNAL\s+(\d{1,3})"
    r"|NONE)\s*$",
    re.IGNORECASE,
)

_CandidateBatchItem = tuple[CrossRepoEdge, list[tuple[CodeNode, UUID]]]


@dataclass(frozen=True, slots=True)
class TierBStats:
    lexical_resolved: int = 0
    llm_resolved: int = 0
    llm_external: int = 0
    capped: int = 0


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

    Bounded by ``CrossRepoSettings.max_rows_per_run`` — even after the
    ``is_likely_external`` pre-filter, a very large or freshly-linked project
    could still have more unresolved rows than are sane to run through FTS +
    an LLM in one pass; the remainder is simply picked up on the next run.
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

    repo_context = _build_repo_context(pairs)

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
            # Queued even with zero candidates (unlike the old "continue and
            # leave unresolved" behavior) — the LLM still has repo-identity
            # context to potentially classify this as EXTERNAL, which the
            # static pre-filter and lexical search alone cannot do.
            still_ambiguous.append((row, candidates[: cfg.candidate_k]))

    llm_resolved = 0
    llm_external = 0
    if still_ambiguous:
        model = llm_model or cfg.llm_model
        if model:
            llm_resolved, llm_external = await _resolve_with_llm(
                still_ambiguous,
                model=model,
                batch_size=cfg.llm_batch_size,
                repo_context=repo_context,
            )
            for row, _candidates in still_ambiguous:
                db.add(row)
        else:
            logger.info(
                "cross_repo tier_b llm skipped project={} reason=no_model_configured",
                project_id,
            )

    await db.commit()
    return TierBStats(
        lexical_resolved=lexical_resolved,
        llm_resolved=llm_resolved,
        llm_external=llm_external,
        capped=capped,
    )


def _build_repo_context(pairs) -> str:
    """One line per project repo: its label and self-declared manifest
    identity — gives the LLM config-level context beyond bare symbol
    candidates, so it can reason about which repo a reference plausibly
    belongs to (or that it belongs to none of them)."""
    lines = ["Project repos:"]
    for link, ws in pairs:
        label = link.display_name or Path(ws.path).name
        identities = [f"{m.ecosystem}:{m.package_name}" for m in read_manifests(ws.path)]
        identity_text = ", ".join(identities) if identities else "no manifest identity found"
        lines.append(f"- {label} — {identity_text}")
    return "\n".join(lines)


def _build_batch_prompt(batch: list[_CandidateBatchItem], *, repo_context: str) -> str:
    lines: list[str] = [repo_context, ""]
    for i, (row, candidates) in enumerate(batch, start=1):
        lines.append(f"{i}. Reference: `{row.raw_reference}` (kind={row.kind})")
        if row.src_file_path:
            lines.append(f"   Found in: {row.src_file_path}")
        if not candidates:
            lines.append("   Candidates: (none found via lexical search)")
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
    repo_context: str,
) -> tuple[int, int]:
    """Returns ``(resolved_count, external_count)``."""
    try:
        provider = build_provider(model)
    except ValueError as exc:
        logger.warning(
            "cross_repo tier_b llm provider unavailable model={} err={}", model, exc
        )
        return 0, 0

    resolved = 0
    external = 0
    for start in range(0, len(batch_items), max(1, batch_size)):
        batch = batch_items[start : start + max(1, batch_size)]
        messages: list[ChatMessage] = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_batch_prompt(batch, repo_context=repo_context)),
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
            row, candidates = batch[idx]
            letter, match_confidence, external_confidence = (
                match.group(2),
                match.group(3),
                match.group(4),
            )

            if letter is not None:
                letter_idx = ord(letter.lower()) - ord("a")
                if letter_idx < 0 or letter_idx >= len(candidates):
                    continue
                node, ws_id = candidates[letter_idx]
                row.status = "resolved"
                row.method = cross_repo.METHOD_LLM
                row.confidence = int(match_confidence) / 100.0
                row.dst_workspace_id = ws_id
                row.dst_node_id = node.id
                row.dst_qualified_name = node.qualified_name
                row.rationale = f"AI-inferred match (model={model})"
                resolved += 1
            elif external_confidence is not None:
                # A second-opinion filter for third-party-library noise the
                # static is_likely_external pre-filter missed — never
                # re-suggested afterward, same as any other resolved status.
                row.status = "external"
                row.method = cross_repo.METHOD_LLM
                row.confidence = int(external_confidence) / 100.0
                row.rationale = f"AI-classified as external dependency (model={model})"
                external += 1
            # else: NONE — leave unresolved for a future pass.
    return resolved, external
