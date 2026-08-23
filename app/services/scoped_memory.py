"""Canonical scoped memory storage, retrieval, and extraction state.

Memory is deliberately split into:

* working memory: the current session transcript (owned by chat_service),
* episodic evidence: links from facts back to source sessions/messages,
* semantic memory: deduplicated facts visible only inside compatible scopes.

The Markdown wiki remains inspectable legacy/consolidated knowledge, but new
automatic recall reads this store so project facts cannot bleed globally.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from loguru import logger
from sqlalchemy import and_, delete, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.models.memory import MemoryExtractionState, MemoryFact, MemoryFactEvidence
from app.services.memory import (
    MemorySearchResult,
    _meaningful_query_tokens,
    _normalized_tokens,
    _score,
)

_VALID_KINDS = {"preference", "profile", "decision", "convention", "constraint", "fact"}
_VALID_CONFIDENCE = {"low", "medium", "high"}
_SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token)\s*[:=]", re.IGNORECASE
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
)
_SCOPE_WEIGHT = {
    "session": 1.35,
    "project": 1.30,
    "workspace": 1.20,
    "folder": 1.15,
    "user": 1.00,
}
_CONFIDENCE_WEIGHT = {"high": 1.10, "medium": 1.00, "low": 0.70}
_EXTRACTION_MARKER_RE = re.compile(
    r"evoflux-memory-facts:v1\s+source=session:([0-9a-fA-F-]{32,36})"
)
_ANNOTATED_BULLET_RE = re.compile(
    r"^-\s+\[(user|project|workspace|folder|session)/"
    r"(preference|profile|decision|convention|constraint|fact)/"
    r"(low|medium|high)\]\s+(.+)$"
)


@dataclass(frozen=True, slots=True)
class MemoryScope:
    type: str
    id: str


@dataclass(frozen=True, slots=True)
class ProposedMemoryFact:
    content: str
    kind: str = "fact"
    scope: str = "session"
    confidence: str = "medium"
    origin: str = "extraction"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _workspace_scope_id(workspace: str) -> str:
    return str(Path(workspace).expanduser().resolve(strict=False))


async def resolve_memory_scopes(
    db: AsyncSession, session_id: UUID
) -> tuple[ChatSession | None, tuple[MemoryScope, ...]]:
    """Return the session and every semantic scope it is allowed to recall."""

    session = await db.get(ChatSession, session_id)
    if session is None:
        return None, ()
    owner = session
    if session.parent_session_id is not None:
        parent = await db.get(ChatSession, session.parent_session_id)
        if parent is not None:
            owner = parent

    scopes = [MemoryScope("user", ""), MemoryScope("session", str(session.id))]
    if owner.id != session.id:
        scopes.append(MemoryScope("session", str(owner.id)))
    if owner.project_id is not None:
        scopes.append(MemoryScope("project", str(owner.project_id)))
    if owner.workspace:
        scopes.append(MemoryScope("workspace", _workspace_scope_id(owner.workspace)))
    if owner.folder_id is not None:
        scopes.append(MemoryScope("folder", str(owner.folder_id)))
    return session, tuple(dict.fromkeys(scopes))


def _normalise_content(content: str) -> str:
    return " ".join(content.split()).strip()


def _content_hash(content: str) -> str:
    normalized = _normalise_content(content).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _looks_sensitive(content: str) -> bool:
    return any(pattern.search(content) for pattern in _SENSITIVE_PATTERNS)


def _coerce_scope(
    proposed: ProposedMemoryFact, available: tuple[MemoryScope, ...]
) -> MemoryScope:
    by_type = {scope.type: scope for scope in available}
    kind = proposed.kind if proposed.kind in _VALID_KINDS else "fact"
    # Only durable profile/preferences may become user-global. Project facts,
    # implementation details, and decisions always remain locally scoped.
    if proposed.scope == "user" and kind in {"preference", "profile"}:
        return by_type["user"]
    if proposed.scope in by_type and proposed.scope != "user":
        return by_type[proposed.scope]
    for scope_type in ("project", "workspace", "folder", "session"):
        if scope_type in by_type:
            return by_type[scope_type]
    return by_type["user"]


async def _get_or_create_fact(
    db: AsyncSession,
    *,
    scope: MemoryScope,
    proposed: ProposedMemoryFact,
    now: datetime,
) -> tuple[MemoryFact, bool]:
    content = _normalise_content(proposed.content)[:500]
    digest = _content_hash(content)
    stmt = select(MemoryFact).where(
        col(MemoryFact.scope_type) == scope.type,
        col(MemoryFact.scope_id) == scope.id,
        col(MemoryFact.content_hash) == digest,
    )
    fact = (await db.exec(stmt)).first()
    created = fact is None
    if fact is None:
        fact = MemoryFact(
            scope_type=scope.type,
            scope_id=scope.id,
            kind=proposed.kind if proposed.kind in _VALID_KINDS else "fact",
            content=content,
            content_hash=digest,
            confidence=(
                proposed.confidence
                if proposed.confidence in _VALID_CONFIDENCE
                else "medium"
            ),
            origin=proposed.origin,
            last_seen_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(fact)
                await db.flush()
        except IntegrityError:
            # Another process inserted the same scoped fact after our SELECT.
            fact = (await db.exec(stmt)).one()
            created = False
    else:
        if fact.status != "active":
            fact.status = "active"
            fact.updated_at = now
        if proposed.confidence == "high":
            fact.confidence = "high"
            fact.updated_at = now
        db.add(fact)
    return fact, created


async def _upsert_evidence(
    db: AsyncSession,
    *,
    fact: MemoryFact,
    session_id: UUID,
    source_message_id: UUID | None,
    now: datetime,
) -> bool:
    stmt = select(MemoryFactEvidence).where(
        col(MemoryFactEvidence.fact_id) == fact.id,
        col(MemoryFactEvidence.session_id) == session_id,
    )
    evidence = (await db.exec(stmt)).first()
    created = evidence is None
    if evidence is None:
        evidence = MemoryFactEvidence(
            fact_id=fact.id,
            session_id=session_id,
            source_message_id=source_message_id,
            last_seen_at=now,
        )
        try:
            async with db.begin_nested():
                db.add(evidence)
                await db.flush()
        except IntegrityError:
            evidence = (await db.exec(stmt)).one()
            created = False
            evidence.last_seen_at = now
            if source_message_id is not None:
                evidence.source_message_id = source_message_id
            db.add(evidence)
    else:
        evidence.last_seen_at = now
        if source_message_id is not None:
            evidence.source_message_id = source_message_id
        db.add(evidence)
    return created


async def store_extracted_facts(
    db: AsyncSession,
    session_id: UUID,
    facts: list[ProposedMemoryFact],
    *,
    source_message_id: UUID | None = None,
) -> list[MemoryFact]:
    """Validate, scope, deduplicate, and attach provenance to extracted facts."""

    _session, scopes = await resolve_memory_scopes(db, session_id)
    if not scopes:
        return []
    now = _utcnow()
    stored: list[MemoryFact] = []
    seen: set[tuple[str, str, str]] = set()
    for proposed in facts[:8]:
        content = _normalise_content(proposed.content)
        if not content or _looks_sensitive(content):
            continue
        scope = _coerce_scope(proposed, scopes)
        key = (scope.type, scope.id, _content_hash(content))
        if key in seen:
            continue
        seen.add(key)
        fact, fact_created = await _get_or_create_fact(
            db, scope=scope, proposed=proposed, now=now
        )
        evidence_created = await _upsert_evidence(
            db,
            fact=fact,
            session_id=session_id,
            source_message_id=source_message_id,
            now=now,
        )
        if evidence_created and not fact_created:
            fact.occurrences += 1
            fact.last_seen_at = now
            fact.updated_at = now
            db.add(fact)
        stored.append(fact)
    await db.flush()
    return stored


def _rank_facts(
    facts: list[MemoryFact], query: str, *, limit: int, automatic: bool
) -> list[MemorySearchResult]:
    meaningful = _meaningful_query_tokens(query)
    if automatic and len(meaningful) < 2:
        return []
    query_tokens = meaningful or set(_normalized_tokens(query))
    ranked: list[MemorySearchResult] = []
    for fact in facts:
        base = _score(query_tokens, fact.content)
        if base <= 0:
            continue
        fact_tokens = set(_normalized_tokens(fact.content))
        matched = query_tokens & fact_tokens
        coverage = len(matched) / len(query_tokens) if query_tokens else 0.0
        if automatic and coverage < 0.5:
            continue
        score = (
            base
            * _SCOPE_WEIGHT.get(fact.scope_type, 1.0)
            * _CONFIDENCE_WEIGHT.get(fact.confidence, 1.0)
            * min(1.20, 1.0 + math.log1p(max(1, fact.occurrences)) * 0.03)
        )
        ranked.append(
            MemorySearchResult(
                source_ref=f"fact:{fact.id}",
                path=None,
                title=f"{fact.kind} ({fact.scope_type})",
                excerpt=fact.content,
                score=score,
                diagnostics={
                    "memory_scope": "semantic",
                    "scope_type": fact.scope_type,
                    "scope_id": fact.scope_id,
                    "kind": fact.kind,
                    "confidence": fact.confidence,
                    "query_coverage": coverage,
                    "matched_tokens": sorted(matched),
                },
            )
        )
    return sorted(ranked, key=lambda item: (-item.score, item.source_ref))[:limit]


async def search_scoped_memory(
    db: AsyncSession,
    session_id: UUID,
    query: str,
    *,
    limit: int = 8,
    automatic: bool = False,
) -> list[MemorySearchResult]:
    """Search only facts visible to the active session's scope set."""

    _session, scopes = await resolve_memory_scopes(db, session_id)
    if not scopes:
        return []
    scope_filter = or_(
        *(
            and_(
                col(MemoryFact.scope_type) == scope.type,
                col(MemoryFact.scope_id) == scope.id,
            )
            for scope in scopes
        )
    )
    facts = list(
        (
            await db.exec(
                select(MemoryFact)
                .where(col(MemoryFact.status) == "active", scope_filter)
                .order_by(col(MemoryFact.updated_at).desc())
                .limit(500)
            )
        ).all()
    )
    # CPU-heavy tokenization/ranking must not block other chat streams.
    import asyncio

    return await asyncio.to_thread(
        _rank_facts, facts, query, limit=max(1, limit), automatic=automatic
    )


def _parse_note_projection(path: Path) -> list[tuple[UUID, ProposedMemoryFact]]:
    """Parse old and new extraction-note projections conservatively."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    current_session: UUID | None = None
    parsed: list[tuple[UUID, ProposedMemoryFact]] = []
    for line in lines:
        marker = _EXTRACTION_MARKER_RE.search(line)
        if marker:
            try:
                current_session = UUID(marker.group(1))
            except ValueError:
                current_session = None
            continue
        if line.startswith("## "):
            current_session = None
            continue
        if current_session is None or not line.startswith("- "):
            continue
        annotated = _ANNOTATED_BULLET_RE.match(line)
        if annotated:
            scope, kind, confidence, content = annotated.groups()
        else:
            content = line[2:].strip()
            # Legacy bullets did not carry a durable scope. Never infer a
            # user-global preference from wording such as "user wants"; that
            # frequently describes a one-off request. The store coerces this
            # local project proposal to workspace/folder/session as needed.
            scope, kind, confidence = "project", "fact", "medium"
        if content:
            parsed.append(
                (
                    current_session,
                    ProposedMemoryFact(
                        content=content,
                        scope=scope,
                        kind=kind,
                        confidence=confidence,
                        origin="legacy_note",
                    ),
                )
            )
    return parsed


async def backfill_extracted_note_projections(
    db: AsyncSession, *, force: bool = False
) -> dict[str, int]:
    """Idempotently import historical extraction notes into scoped memory."""

    from app.services.wiki import NOTES_DIR, wiki_root

    root = wiki_root()
    sentinel = root / ".scoped-memory-v1-backfilled"
    if sentinel.is_file() and not force:
        return {"files": 0, "sessions": 0, "facts": 0, "skipped": 1}
    notes_dir = root / NOTES_DIR
    if not notes_dir.is_dir():
        return {"files": 0, "sessions": 0, "facts": 0, "skipped": 0}
    paths = sorted(notes_dir.glob("*.md"))
    batches = await asyncio.gather(
        *(asyncio.to_thread(_parse_note_projection, path) for path in paths)
    )
    grouped: dict[UUID, list[ProposedMemoryFact]] = {}
    for batch in batches:
        for session_id, fact in batch:
            grouped.setdefault(session_id, []).append(fact)
    facts_stored = 0
    sessions_imported = 0
    for session_id, facts in grouped.items():
        if await db.get(ChatSession, session_id) is None:
            continue
        for offset in range(0, len(facts), 8):
            stored = await store_extracted_facts(
                db, session_id, facts[offset : offset + 8]
            )
            facts_stored += len(stored)
        sessions_imported += 1
        # Release SQLite's single writer between sessions so startup backfill
        # cannot freeze live chat persistence behind one long transaction.
        await db.commit()
        await asyncio.sleep(0)
    result = {
        "files": len(paths),
        "sessions": sessions_imported,
        "facts": facts_stored,
        "skipped": 0,
    }
    from app.agent.tools.builtin.filesystem._atomic import atomic_write_bytes

    await asyncio.to_thread(
        atomic_write_bytes,
        sentinel,
        b"Scoped memory legacy-note backfill completed.\n",
    )
    logger.info("memory_note_backfill_complete result={}", result)
    return result


async def claim_extraction(
    db: AsyncSession,
    session_id: UUID,
    *,
    assistant_count: int,
    content_hash: str,
    min_assistant_messages: int,
    every_n_messages: int,
) -> bool:
    """Durably claim an extraction window, recovering stale/crashed claims."""

    now = _utcnow()
    state = await db.get(MemoryExtractionState, session_id)
    if state is None:
        if assistant_count < min_assistant_messages:
            return False
        state = MemoryExtractionState(session_id=session_id)
    else:
        stale = state.started_at is None or state.started_at < now - timedelta(
            minutes=15
        )
        if state.status == "processing" and not stale:
            return False
        if state.last_assistant_count > 0:
            if assistant_count - state.last_assistant_count < every_n_messages:
                return False
        elif assistant_count < min_assistant_messages:
            return False
        if (
            state.status == "done"
            and state.content_hash == content_hash
            and state.last_assistant_count >= assistant_count
        ):
            return False

    state.status = "processing"
    state.pending_assistant_count = assistant_count
    state.content_hash = content_hash
    state.attempts += 1
    state.error = None
    state.started_at = now
    state.updated_at = now
    db.add(state)
    await db.flush()
    return True


async def complete_extraction(
    db: AsyncSession, session_id: UUID, *, assistant_count: int
) -> None:
    state = await db.get(MemoryExtractionState, session_id)
    if state is None:
        return
    state.last_assistant_count = max(state.last_assistant_count, assistant_count)
    state.pending_assistant_count = None
    state.status = "done"
    state.error = None
    state.completed_at = _utcnow()
    state.updated_at = state.completed_at
    db.add(state)
    await db.flush()


async def fail_extraction(
    db: AsyncSession, session_id: UUID, *, assistant_count: int, error: str
) -> None:
    state = await db.get(MemoryExtractionState, session_id)
    if state is None or state.pending_assistant_count != assistant_count:
        return
    state.pending_assistant_count = None
    state.status = "failed"
    state.error = error[:1000]
    state.updated_at = _utcnow()
    db.add(state)
    await db.flush()


async def forget_session_memory(db: AsyncSession, session_id: UUID) -> int:
    """Remove a session's evidence and every extracted fact left unsupported."""

    fact_ids = list(
        (
            await db.exec(
                select(MemoryFactEvidence.fact_id).where(
                    col(MemoryFactEvidence.session_id) == session_id
                )
            )
        ).all()
    )
    if not fact_ids:
        return 0
    await db.exec(
        delete(MemoryFactEvidence).where(
            col(MemoryFactEvidence.session_id) == session_id
        )
    )
    removed = 0
    for fact_id in set(fact_ids):
        remaining = (
            await db.exec(
                select(func.count())
                .select_from(MemoryFactEvidence)
                .where(col(MemoryFactEvidence.fact_id) == fact_id)
            )
        ).one()
        if int(remaining or 0) == 0:
            await db.exec(delete(MemoryFact).where(col(MemoryFact.id) == fact_id))
            removed += 1
    logger.info(
        "session_memory_forgotten session_id={} facts_removed={}", session_id, removed
    )
    return removed


__all__ = [
    "MemoryScope",
    "ProposedMemoryFact",
    "backfill_extracted_note_projections",
    "claim_extraction",
    "complete_extraction",
    "fail_extraction",
    "forget_session_memory",
    "resolve_memory_scopes",
    "search_scoped_memory",
    "store_extracted_facts",
]
