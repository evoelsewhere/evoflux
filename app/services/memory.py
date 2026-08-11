"""Unified search and recall over EvoFlux's durable Memory store.

Dream writes curated knowledge to ``topics/``, ``entities/``, ``sources/``,
and ``comparisons/``.  ``USER.md`` contains the durable user profile, while
``notes/`` and ``imports/`` remain raw evidence.  This module is the single
retrieval path used by both automatic prompt injection and ``memory_search``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, SessionMessage
from app.services.wiki import (
    COMPARISONS_DIR,
    ENTITIES_DIR,
    IMPORTS_DIR,
    NOTES_DIR,
    SOURCES_DIR,
    TOPICS_DIR,
    USER_FILE,
    parse_frontmatter,
    wiki_root,
)

EXTRACTED_FACTS_MARKER = "evoflux-memory-facts:v1"
CURATED_MEMORY_DIRS: tuple[str, ...] = (
    TOPICS_DIR,
    ENTITIES_DIR,
    SOURCES_DIR,
    COMPARISONS_DIR,
)
RAW_MEMORY_DIRS: tuple[str, ...] = (NOTES_DIR, IMPORTS_DIR)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class MemorySearchResult:
    source_ref: str
    path: str | None
    title: str
    excerpt: str
    score: float
    diagnostics: dict[str, object] = field(default_factory=dict)


_SEARCH_STOPWORDS = {
    # English query scaffolding.
    "a",
    "an",
    "and",
    "are",
    "be",
    "did",
    "do",
    "does",
    "for",
    "how",
    "in",
    "is",
    "me",
    "my",
    "of",
    "s",
    "should",
    "the",
    "to",
    "what",
    "which",
    "with",
    "you",
    # Vietnamese query scaffolding.  Keep content-bearing words such as
    # "muốn", "nhớ", and "quyết định" searchable.
    "các",
    "cho",
    "của",
    "đã",
    "được",
    "hãy",
    "không",
    "là",
    "một",
    "nào",
    "những",
    "thế",
    "thì",
    "tôi",
    "trong",
    "và",
    "về",
    "với",
}


def memory_root() -> Path:
    """Return the canonical EvoFlux Memory root."""
    return wiki_root()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def _normalize_token(token: str) -> str:
    """Apply conservative English inflection cleanup without concept mapping."""
    normalized = token.casefold()
    if len(normalized) > 4 and normalized.endswith("ies"):
        return normalized[:-3] + "y"
    if len(normalized) > 4 and normalized.endswith("ing"):
        normalized = normalized[:-3]
    elif len(normalized) > 3 and normalized.endswith("ed"):
        normalized = normalized[:-2]
    elif (
        len(normalized) > 3
        and normalized.endswith("s")
        and not normalized.endswith("ss")
    ):
        normalized = normalized[:-1]
    if len(normalized) > 3 and normalized[-1:] == normalized[-2:-1]:
        normalized = normalized[:-1]
    return normalized


def _meaningful_query_tokens(query: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in _tokens(query)
        if token not in _SEARCH_STOPWORDS
    }


def _normalized_tokens(text: str) -> list[str]:
    return [_normalize_token(token) for token in _tokens(text)]


def _scoring_tokens(query: str) -> set[str]:
    meaningful = _meaningful_query_tokens(query)
    return meaningful or {_normalize_token(token) for token in _tokens(query)}


def _score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    tokens = _normalized_tokens(text)
    if not tokens:
        return 0.0
    counts = {token: tokens.count(token) for token in query_tokens}
    overlap = sum(counts.values())
    if overlap == 0:
        return 0.0
    coverage = sum(1 for token in query_tokens if counts[token] > 0) / len(query_tokens)
    return (overlap * coverage) / math.log(len(tokens) + 10)


def _metadata(text: str) -> dict[str, object]:
    parsed = parse_frontmatter(text)
    return {
        "description": parsed.description,
        "tags": set(parsed.tags),
        "confidence": parsed.confidence,
        "sources": list(parsed.sources),
        "body": parsed.body,
    }


def _diagnose_result(
    query: str,
    query_tokens: set[str],
    rel_path: str,
    text: str,
    base_score: float,
    *,
    memory_scope: str,
) -> dict[str, object]:
    metadata = _metadata(text)
    meaningful = _meaningful_query_tokens(query)
    searchable_text = f"{rel_path}\n{text}"
    meaningful_text = _meaningful_query_tokens(searchable_text)
    matched = sorted(meaningful & meaningful_text)
    query_count = len(meaningful)
    raw_tags = metadata["tags"]
    tags: set[str] = (
        {str(tag) for tag in raw_tags} if isinstance(raw_tags, set) else set()
    )
    normalized_tags = {_normalize_token(tag) for tag in tags}
    path_tokens = set(_normalized_tokens(rel_path))
    description_tokens = set(_normalized_tokens(str(metadata["description"])))
    return {
        "base_score": base_score,
        "memory_scope": memory_scope,
        "matched_tokens": sorted(
            query_tokens & set(_normalized_tokens(searchable_text))
        ),
        "matched_meaningful_tokens": matched,
        "missing_meaningful_tokens": sorted(meaningful - meaningful_text),
        "query_token_count": query_count,
        "evidence_token_count": len(matched),
        "query_coverage": len(matched) / query_count if query_count else 0.0,
        "path_overlap": sorted(meaningful & path_tokens),
        "description_overlap": sorted(meaningful & description_tokens),
        "tag_overlap": sorted(meaningful & normalized_tags),
        "confidence": metadata["confidence"],
        "sources": metadata["sources"],
    }


def _reranked_score(score: float, diagnostics: dict[str, object]) -> float:
    path_overlap = diagnostics.get("path_overlap")
    description_overlap = diagnostics.get("description_overlap")
    tag_overlap = diagnostics.get("tag_overlap")
    coverage = diagnostics.get("query_coverage")
    multiplier = 1.0
    if isinstance(path_overlap, list):
        multiplier += 0.12 * len(path_overlap)
    if isinstance(description_overlap, list):
        multiplier += 0.15 * len(description_overlap)
    if isinstance(tag_overlap, list):
        multiplier += 0.2 * len(tag_overlap)
    if isinstance(coverage, float):
        multiplier += 0.5 * coverage
    diagnostics["rerank_multiplier"] = multiplier
    return score * multiplier


def _has_sufficient_evidence(diagnostics: dict[str, object]) -> bool:
    """Abstain when a page matches the subject but not the requested detail."""
    query_count = diagnostics.get("query_token_count")
    evidence_count = diagnostics.get("evidence_token_count")
    coverage = diagnostics.get("query_coverage")
    if not isinstance(query_count, int) or not isinstance(evidence_count, int):
        return False
    if not isinstance(coverage, float) or query_count <= 0:
        return False
    required_count = 1 if query_count <= 2 else 2
    return evidence_count >= required_count and coverage >= 0.5


def _excerpt(text: str, query_tokens: set[str], limit: int = 500) -> str:
    parsed = parse_frontmatter(text)
    clean = re.sub(r"\s+", " ", parsed.body or text).strip()
    if len(clean) <= limit:
        return clean
    normalized = clean.casefold()
    positions = [
        normalized.find(token) for token in query_tokens if normalized.find(token) >= 0
    ]
    start = max(min(positions) - 120, 0) if positions else 0
    end = min(start + limit, len(clean))
    return f"{'…' if start else ''}{clean[start:end]}{'…' if end < len(clean) else ''}"


def _source_ref_for_file(rel_path: str) -> str:
    if rel_path == USER_FILE:
        return "memory:user"
    path = Path(rel_path)
    namespace = {
        TOPICS_DIR: "topic",
        ENTITIES_DIR: "entity",
        SOURCES_DIR: "source",
        COMPARISONS_DIR: "comparison",
        IMPORTS_DIR: "import",
        NOTES_DIR: "note",
    }.get(path.parts[0], "memory")
    identifier = path.stem if namespace != "note" else path.name
    return f"{namespace}:{identifier}"


def _candidate_files(scope: str) -> list[tuple[str, Path, str]]:
    if scope not in {"all", "curated"}:
        raise ValueError(f"Unknown memory search scope: {scope}")
    root = memory_root()
    candidates: list[tuple[str, Path, str]] = []
    user_path = root / USER_FILE
    if user_path.is_file():
        candidates.append((USER_FILE, user_path, "curated"))
    directories = CURATED_MEMORY_DIRS
    if scope == "all":
        directories = (*directories, *RAW_MEMORY_DIRS)
    for subdir in directories:
        directory = root / subdir
        if not directory.is_dir():
            continue
        item_scope = "raw" if subdir in RAW_MEMORY_DIRS else "curated"
        candidates.extend(
            (f"{subdir}/{entry.name}", entry, item_scope)
            for entry in sorted(directory.iterdir())
            if entry.is_file() and entry.suffix == ".md"
        )
    return candidates


def search_memory_files(
    query: str,
    *,
    limit: int = 8,
    scope: str = "all",
    rerank: bool = True,
    abstain_weak: bool = True,
) -> list[MemorySearchResult]:
    """Search canonical Memory pages and, optionally, raw evidence files."""
    limit = max(1, limit)
    query_tokens = _scoring_tokens(query)
    results: list[MemorySearchResult] = []
    for rel_path, path, item_scope in _candidate_files(scope):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        score = _score(query_tokens, f"{rel_path}\n{text}")
        if score <= 0:
            continue
        diagnostics = _diagnose_result(
            query,
            query_tokens,
            rel_path,
            text,
            score,
            memory_scope=item_scope,
        )
        if abstain_weak and not _has_sufficient_evidence(diagnostics):
            continue
        final_score = _reranked_score(score, diagnostics) if rerank else score
        parsed = parse_frontmatter(text)
        results.append(
            MemorySearchResult(
                source_ref=_source_ref_for_file(rel_path),
                path=rel_path,
                title=parsed.description or rel_path,
                excerpt=_excerpt(text, query_tokens),
                score=final_score,
                diagnostics=diagnostics,
            )
        )
    return sorted(results, key=lambda result: (-result.score, result.source_ref))[
        :limit
    ]


def search_curated_memory(
    query: str,
    *,
    limit: int = 8,
    rerank: bool = True,
    abstain_weak: bool = True,
) -> list[MemorySearchResult]:
    """Search only durable knowledge that is safe for automatic recall."""
    return search_memory_files(
        query,
        limit=limit,
        scope="curated",
        rerank=rerank,
        abstain_weak=abstain_weak,
    )


async def search_memory_messages(
    db: AsyncSession, query: str, *, limit: int = 5
) -> list[MemorySearchResult]:
    """Search visible persisted chat messages as a raw-evidence fallback."""
    limit = max(1, limit)
    query_tokens = _scoring_tokens(query)
    if not query_tokens:
        return []
    stmt = (
        select(SessionMessage, ChatSession)
        .join(ChatSession, col(SessionMessage.session_id) == col(ChatSession.id))
        .where(col(SessionMessage.exclude_from_context).is_(False))
        .where(col(SessionMessage.content).is_not(None))
        .order_by(col(SessionMessage.created_at).desc())
        .limit(500)
    )
    rows = (await db.exec(stmt)).all()
    results: list[MemorySearchResult] = []
    for message, session in rows:
        content = message.content or ""
        title = session.title or session.agent_name or str(session.id)
        score = _score(query_tokens, f"{title}\n{message.role}\n{content}")
        if score <= 0:
            continue
        results.append(
            MemorySearchResult(
                source_ref=f"message:{message.id}",
                path=None,
                title=f"{title} ({message.role})",
                excerpt=_excerpt(content, query_tokens),
                score=score,
                diagnostics={"memory_scope": "raw"},
            )
        )
    return sorted(results, key=lambda result: (-result.score, result.source_ref))[
        :limit
    ]


async def memory_search(
    query: str,
    *,
    db: AsyncSession | None = None,
    limit: int = 8,
    rerank: bool = True,
    abstain_weak: bool = True,
) -> list[MemorySearchResult]:
    """Search durable Memory, raw evidence files, and visible chat history."""
    limit = max(1, limit)
    results = search_memory_files(
        query,
        limit=limit,
        scope="all",
        rerank=rerank,
        abstain_weak=abstain_weak,
    )
    if db is not None:
        results.extend(await search_memory_messages(db, query, limit=limit))
    return sorted(results, key=lambda result: (-result.score, result.source_ref))[
        :limit
    ]


__all__ = [
    "CURATED_MEMORY_DIRS",
    "EXTRACTED_FACTS_MARKER",
    "MemorySearchResult",
    "RAW_MEMORY_DIRS",
    "memory_root",
    "memory_search",
    "search_curated_memory",
    "search_memory_files",
    "search_memory_messages",
]
