"""Ranked parser-aligned source retrieval across authorized repositories."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import current_sqlite_path
from app.models.code_graph import CodeIndexChunk
from app.services.code_graph.query import identifier_search_text
from app.services.code_intelligence.engine import prepare_scopes
from app.services.code_intelligence.models import FreshnessPolicy, WorkspaceScope
from app.services.codeindex import fts_store


@dataclass(frozen=True, slots=True)
class CodeIndexMatch:
    chunk: CodeIndexChunk
    scope: WorkspaceScope
    score: float
    match_reasons: tuple[str, ...]


@dataclass(slots=True)
class CodeIndexResult:
    query: str
    strategy: str
    graph_version: str | None
    freshness: Literal["fresh", "partial", "unavailable"]
    matches: list[CodeIndexMatch]
    dirty_files: int = 0
    limitations: list[str] = field(default_factory=list)
    truncated: bool = False


async def search_code_index(
    db: AsyncSession,
    *,
    scopes: tuple[WorkspaceScope, ...],
    query: str,
    repository: str | None = None,
    path: str | None = None,
    language: str | None = None,
    limit: int = 20,
    freshness_policy: FreshnessPolicy = "fast",
) -> CodeIndexResult:
    """Search source chunks and deterministically merge repository-local ranks."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Code-index query cannot be empty.")
    selected_scopes = _select_scopes(scopes, repository)
    if not selected_scopes:
        return CodeIndexResult(
            query=normalized_query,
            strategy="codeindex-unavailable",
            graph_version=None,
            freshness="unavailable",
            matches=[],
            limitations=["No authorized repository matched the requested scope."],
        )

    prepared = await prepare_scopes(db, selected_scopes, freshness_policy)
    active = tuple(item for item in prepared if item.states)
    version = _version(active)
    dirty_files = sum(len(item.dirty_paths) for item in prepared)
    freshness: Literal["fresh", "partial", "unavailable"] = (
        "partial" if dirty_files else "fresh"
    )
    if not active:
        freshness = "unavailable"
        return CodeIndexResult(
            query=normalized_query,
            strategy="codeindex-unavailable",
            graph_version=version,
            freshness=freshness,
            matches=[],
            dirty_files=dirty_files,
            limitations=["The source index contains no supported files."],
        )

    db_path = current_sqlite_path()
    if db_path is None:
        return CodeIndexResult(
            query=normalized_query,
            strategy="codeindex-unavailable",
            graph_version=version,
            freshness=freshness,
            matches=[],
            dirty_files=dirty_files,
            limitations=["Indexed source search requires the local SQLite store."],
        )

    capped_limit = max(1, min(50, limit))
    candidate_limit = max(100, capped_limit * 10)
    lookups = [
        (str(item.scope.workspace_id), normalized_query) for item in active
    ]
    hit_groups = await asyncio.to_thread(
        fts_store.search_many,
        db_path,
        lookups,
        path=path,
        language=language,
        limit=candidate_limit,
    )
    rank_by_id: dict[UUID, float] = {}
    scope_by_workspace = {item.scope.workspace_id: item.scope for item in active}
    for hits in hit_groups:
        for hit in hits:
            try:
                chunk_id = UUID(hit.chunk_id)
            except ValueError:
                continue
            rank_by_id[chunk_id] = max(rank_by_id.get(chunk_id, 0.0), hit.rank)

    if not rank_by_id:
        return CodeIndexResult(
            query=normalized_query,
            strategy="codeindex-fts5-structural",
            graph_version=version,
            freshness=freshness,
            matches=[],
            dirty_files=dirty_files,
        )

    chunks = list(
        (
            await db.exec(
                select(CodeIndexChunk).where(
                    col(CodeIndexChunk.id).in_(list(rank_by_id))
                )
            )
        ).all()
    )
    ranked: list[CodeIndexMatch] = []
    for chunk in chunks:
        scope = scope_by_workspace.get(chunk.workspace_id)
        if scope is None:
            continue
        score, reasons = _rank_chunk(
            chunk,
            normalized_query,
            fts_rank=rank_by_id.get(chunk.id, 0.0),
        )
        ranked.append(
            CodeIndexMatch(
                chunk=chunk,
                scope=scope,
                score=score,
                match_reasons=reasons,
            )
        )
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.scope.label.casefold(),
            item.chunk.file_path.casefold(),
            item.chunk.line_start,
            str(item.chunk.id),
        )
    )
    truncated = len(ranked) > capped_limit
    return CodeIndexResult(
        query=normalized_query,
        strategy="codeindex-fts5-structural",
        graph_version=version,
        freshness=freshness,
        matches=ranked[:capped_limit],
        dirty_files=dirty_files,
        truncated=truncated,
    )


def _select_scopes(
    scopes: tuple[WorkspaceScope, ...], repository: str | None
) -> tuple[WorkspaceScope, ...]:
    if not repository:
        return scopes
    folded = repository.strip().casefold()
    exact = tuple(scope for scope in scopes if scope.label.casefold() == folded)
    if exact:
        return exact
    return tuple(scope for scope in scopes if folded in scope.label.casefold())


def _version(prepared) -> str | None:  # noqa: ANN001
    states = [state for item in prepared for state in item.states]
    if not states:
        return None
    digest = hashlib.sha256()
    for state in sorted(states, key=lambda row: (str(row.workspace_id), row.file_path)):
        digest.update(str(state.workspace_id).encode())
        digest.update(state.file_path.encode("utf-8", "replace"))
        digest.update(state.content_hash.encode())
    return digest.hexdigest()[:12]


def _rank_chunk(
    chunk: CodeIndexChunk,
    query: str,
    *,
    fts_rank: float,
) -> tuple[float, tuple[str, ...]]:
    folded = query.casefold()
    tokens = tuple(identifier_search_text(query).split())
    name = chunk.name.casefold()
    qualified = chunk.qualified_name.casefold()
    path = chunk.file_path.casefold()
    identifiers = identifier_search_text(
        chunk.name,
        chunk.qualified_name,
        chunk.file_path,
        chunk.signature,
        chunk.docstring,
    )
    content = chunk.content.casefold()
    haystack = f"{identifiers} {content}"
    reasons: list[str] = []
    score = min(20.0, max(0.0, fts_rank))
    if qualified == folded:
        score += 100.0
        reasons.append("exact-qualified-name")
    elif name == folded:
        score += 90.0
        reasons.append("exact-symbol")
    elif qualified.endswith(f".{folded}"):
        score += 75.0
        reasons.append("qualified-suffix")
    if folded in path:
        score += 20.0
        reasons.append("path")
    if folded in content:
        score += 15.0
        reasons.append("source-phrase")
    if tokens:
        matched = sum(token in haystack for token in tokens)
        coverage = matched / len(tokens)
        score += coverage * 40.0
        if coverage == 1.0:
            reasons.append("all-query-tokens")
        elif matched:
            reasons.append(f"query-token-coverage:{matched}/{len(tokens)}")
        name_tokens = set(identifier_search_text(chunk.name, chunk.qualified_name).split())
        symbol_matches = sum(token in name_tokens for token in tokens)
        score += symbol_matches * 8.0
        if symbol_matches:
            reasons.append("symbol-token")
    return round(score, 6), tuple(reasons)


__all__ = ["CodeIndexMatch", "CodeIndexResult", "search_code_index"]
