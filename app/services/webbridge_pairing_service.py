"""WebBridge pairing credentials and short-lived relay tickets."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.webbridge import (
    WebBridgeInteraction,
    WebBridgePairing,
    WebBridgeTabBinding,
    WebBridgeTeachDraft,
)
from app.models.chat import ChatSession


DEFAULT_PAIRING_SCOPES = frozenset(
    {
        "relay",
        "interactions:write",
        "bindings:write",
        "sessions:list",
        "sessions:create",
        "session-stream:read",
        "teach:drafts:write",
        "session:messages:write",
        "handoff:reply",
    }
)
_P0_PAIRING_SCOPES = frozenset(
    {
        "relay",
        "interactions:write",
        "bindings:write",
        "sessions:list",
        "session-stream:read",
    }
)
_P1_PAIRING_SCOPES = frozenset(
    {
        "relay",
        "interactions:write",
        "bindings:write",
        "sessions:list",
        "sessions:create",
        "session-stream:read",
    }
)
_P3_PAIRING_SCOPES = _P1_PAIRING_SCOPES | {"teach:drafts:write"}


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def pairing_session_tag(pairing_id: UUID | str) -> str:
    """Session tag granting one paired browser access to a WebBridge session."""
    return f"webbridge_pairing:{pairing_id}"


@dataclass(frozen=True)
class PairingGrant:
    label: str
    scopes: frozenset[str]


class WebBridgePairingCodeStore:
    """Issue human-entered, one-time pairing codes with a short lifetime."""

    _ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._codes: dict[str, tuple[PairingGrant, float]] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        label: str,
        *,
        scopes: frozenset[str] = DEFAULT_PAIRING_SCOPES,
        now: float | None = None,
    ) -> str:
        issued_at = time.monotonic() if now is None else now
        code = "-".join(
            "".join(secrets.choice(self._ALPHABET) for _ in range(4)) for _ in range(3)
        )
        with self._lock:
            self._codes[_token_digest(code)] = (
                PairingGrant(label=label, scopes=scopes),
                issued_at + self._ttl_seconds,
            )
        return code

    def consume(self, code: str, *, now: float | None = None) -> PairingGrant | None:
        consumed_at = time.monotonic() if now is None else now
        normalized = code.strip().upper()
        with self._lock:
            entry = self._codes.pop(_token_digest(normalized), None)
        if entry is None:
            return None
        grant, expires_at = entry
        return grant if consumed_at <= expires_at else None


class WebBridgeRateLimiter:
    """Per-pairing sliding-window limiter for inbound interactions."""

    def __init__(self, *, window_seconds: float = 60.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, pairing_id: str, limit: int, *, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self._window_seconds
        with self._lock:
            events = self._events.setdefault(pairing_id, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(timestamp)
            return True


class WebBridgeTicketStore:
    """Issue and atomically consume short-lived relay WebSocket tickets."""

    def __init__(self, *, ttl_seconds: float = 30.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._tickets: dict[bytes, tuple[str, float]] = {}
        self._revoked_pairings: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _digest(ticket: str) -> bytes:
        return hashlib.sha256(ticket.encode("utf-8")).digest()

    def issue(self, pairing_id: str, *, now: float | None = None) -> str:
        issued_at = time.monotonic() if now is None else now
        ticket = secrets.token_urlsafe(32)
        with self._lock:
            if pairing_id in self._revoked_pairings:
                raise ValueError("pairing is revoked")
            self._tickets[self._digest(ticket)] = (
                pairing_id,
                issued_at + self._ttl_seconds,
            )
        return ticket

    def consume(self, ticket: str, *, now: float | None = None) -> str | None:
        consumed_at = time.monotonic() if now is None else now
        with self._lock:
            entry = self._tickets.pop(self._digest(ticket), None)
            if entry is None:
                return None
            pairing_id, expires_at = entry
            if pairing_id in self._revoked_pairings:
                return None
            return pairing_id if consumed_at <= expires_at else None

    def revoke(self, pairing_id: str) -> int:
        """Invalidate every outstanding ticket issued for one pairing."""
        with self._lock:
            self._revoked_pairings.add(pairing_id)
            digests = [
                digest
                for digest, (ticket_pairing_id, _) in self._tickets.items()
                if ticket_pairing_id == pairing_id
            ]
            for digest in digests:
                self._tickets.pop(digest, None)
        return len(digests)

    def is_revoked(self, pairing_id: str) -> bool:
        with self._lock:
            return pairing_id in self._revoked_pairings


def new_pairing_credential() -> str:
    return secrets.token_urlsafe(32)


async def create_pairing(
    db: AsyncSession,
    *,
    grant: PairingGrant,
    browser: str,
    version: str,
) -> tuple[WebBridgePairing, str]:
    credential = new_pairing_credential()
    pairing = WebBridgePairing(
        label=grant.label,
        browser=browser[:40] or "unknown",
        version=version[:40] or "unknown",
        credential_hash=_token_digest(credential),
        scopes=sorted(grant.scopes),
    )
    db.add(pairing)
    await db.flush()
    return pairing, credential


async def authenticate_pairing(
    db: AsyncSession,
    credential: str,
    *,
    required_scope: str | None = None,
) -> WebBridgePairing | None:
    if not credential:
        return None
    pairing = (
        await db.exec(
            select(WebBridgePairing).where(
                WebBridgePairing.credential_hash == _token_digest(credential),
                col(WebBridgePairing.revoked_at).is_(None),
            )
        )
    ).first()
    if pairing is None:
        return None
    # P0/P1 pairings were issued by this same first-party flow. Upgrade only
    # their exact historical scope sets so existing extensions can use the
    # new draft-only Teach Mode capability without being re-paired. Approval
    # and replay intentionally remain app-authenticated endpoints.
    if frozenset(pairing.scopes) in {
        _P0_PAIRING_SCOPES,
        _P1_PAIRING_SCOPES,
        _P3_PAIRING_SCOPES,
    }:
        pairing.scopes = sorted(DEFAULT_PAIRING_SCOPES)
    if required_scope is not None and required_scope not in pairing.scopes:
        return None
    pairing.last_seen_at = datetime.now(timezone.utc)
    db.add(pairing)
    return pairing


async def list_active_pairings(db: AsyncSession) -> list[WebBridgePairing]:
    rows = await db.exec(
        select(WebBridgePairing)
        .where(col(WebBridgePairing.revoked_at).is_(None))
        .order_by(col(WebBridgePairing.last_seen_at).desc())
    )
    return list(rows.all())


async def revoke_pairing(db: AsyncSession, pairing_id: UUID) -> WebBridgePairing | None:
    pairing = await db.get(WebBridgePairing, pairing_id)
    if pairing is None or pairing.revoked_at is not None:
        return None
    pairing.revoked_at = datetime.now(timezone.utc)
    db.add(pairing)
    await db.flush()
    return pairing


async def delete_pairing_data(db: AsyncSession, pairing_id: UUID) -> None:
    """Remove pairing-owned channel metadata while preserving chat messages."""
    await db.exec(
        delete(WebBridgeTabBinding).where(
            col(WebBridgeTabBinding.pairing_id) == pairing_id
        )
    )
    await db.exec(
        delete(WebBridgeInteraction).where(
            col(WebBridgeInteraction.pairing_id) == pairing_id
        )
    )
    await db.exec(
        delete(WebBridgeTeachDraft).where(
            col(WebBridgeTeachDraft.pairing_id) == pairing_id
        )
    )
    owner_tag = pairing_session_tag(pairing_id)
    sessions = (
        await db.exec(select(ChatSession).where(col(ChatSession.tags).is_not(None)))
    ).all()
    for session in sessions:
        if owner_tag not in (session.tags or ()):
            continue
        session.tags = [tag for tag in (session.tags or []) if tag != owner_tag] or None
        db.add(session)
    await db.flush()


def interaction_request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create_or_get_interaction(
    db: AsyncSession,
    *,
    pairing_id: UUID,
    interaction_id: str,
    request_payload: dict[str, Any],
    kind: str,
    delivery: str,
    status: str,
    target_session_id: UUID | None,
    origin: str,
    tab_id: int | None,
    page_instance_id: str | None,
    payload_metadata: dict[str, Any],
    prompt: str | None = None,
) -> tuple[WebBridgeInteraction, bool]:
    request_hash = interaction_request_hash(request_payload)
    stmt = select(WebBridgeInteraction).where(
        WebBridgeInteraction.pairing_id == pairing_id,
        WebBridgeInteraction.interaction_id == interaction_id,
    )
    existing = (await db.exec(stmt)).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("interaction_id was already used for another request")
        return existing, False

    interaction = WebBridgeInteraction(
        pairing_id=pairing_id,
        interaction_id=interaction_id,
        request_hash=request_hash,
        kind=kind,
        delivery=delivery,
        status=status,
        target_session_id=target_session_id,
        origin=origin,
        tab_id=tab_id,
        page_instance_id=page_instance_id,
        payload_metadata=payload_metadata,
        prompt=prompt,
    )
    try:
        async with db.begin_nested():
            db.add(interaction)
            await db.flush()
    except IntegrityError:
        existing = (await db.exec(stmt)).first()
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise ValueError(
                "interaction_id was already used for another request"
            ) from None
        return existing, False
    return interaction, True


async def create_teach_draft(
    db: AsyncSession,
    *,
    pairing_id: UUID,
    session_id: UUID,
    tab_id: int,
    title: str,
    origin: str,
    start_url: str,
    actions: list[dict[str, Any]],
    parameter_names: list[str],
    capture_warnings: list[str],
) -> WebBridgeTeachDraft:
    """Persist a review-gated semantic browser trace for one pairing."""
    draft = WebBridgeTeachDraft(
        pairing_id=pairing_id,
        session_id=session_id,
        tab_id=tab_id,
        title=title,
        origin=origin,
        start_url=start_url,
        actions=actions,
        parameter_names=parameter_names,
        capture_warnings=capture_warnings,
    )
    db.add(draft)
    await db.flush()
    return draft


async def list_teach_drafts(db: AsyncSession) -> list[WebBridgeTeachDraft]:
    rows = await db.exec(
        select(WebBridgeTeachDraft).order_by(col(WebBridgeTeachDraft.created_at).desc())
    )
    return list(rows.all())


async def claim_interaction_dispatch(
    db: AsyncSession,
    interaction: WebBridgeInteraction,
    *,
    lease_seconds: int = 60,
) -> bool:
    """Claim a pending submit, reclaiming it after an expired crash lease."""
    now = datetime.now(timezone.utc)
    result = await db.exec(
        update(WebBridgeInteraction)
        .where(
            col(WebBridgeInteraction.id) == interaction.id,
            col(WebBridgeInteraction.status) == "pending",
            or_(
                col(WebBridgeInteraction.dispatch_lease_until).is_(None),
                col(WebBridgeInteraction.dispatch_lease_until) <= now,
            ),
        )
        .values(dispatch_lease_until=now + timedelta(seconds=lease_seconds))
        .returning(col(WebBridgeInteraction.id))
    )
    await db.commit()
    claimed = result.first() is not None
    return claimed


async def upsert_tab_binding(
    db: AsyncSession,
    *,
    pairing_id: UUID,
    tab_id: int,
    session_id: UUID,
    origin: str,
    page_instance_id: str | None,
    ttl_seconds: int = 86_400,
) -> WebBridgeTabBinding:
    now = datetime.now(timezone.utc)
    stale_session_bindings = (
        await db.exec(
            select(WebBridgeTabBinding).where(
                WebBridgeTabBinding.pairing_id == pairing_id,
                WebBridgeTabBinding.session_id == session_id,
                WebBridgeTabBinding.tab_id != tab_id,
            )
        )
    ).all()
    for stale in stale_session_bindings:
        await db.delete(stale)
    binding = (
        await db.exec(
            select(WebBridgeTabBinding).where(
                WebBridgeTabBinding.pairing_id == pairing_id,
                WebBridgeTabBinding.tab_id == tab_id,
            )
        )
    ).first()
    if binding is None:
        binding = WebBridgeTabBinding(
            pairing_id=pairing_id,
            tab_id=tab_id,
            session_id=session_id,
            origin=origin,
            page_instance_id=page_instance_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    else:
        binding.session_id = session_id
        binding.origin = origin
        binding.page_instance_id = page_instance_id
        binding.updated_at = now
        binding.expires_at = now + timedelta(seconds=ttl_seconds)
    db.add(binding)
    await db.flush()
    return binding


async def list_tab_bindings(
    db: AsyncSession, pairing_id: UUID
) -> list[WebBridgeTabBinding]:
    now = datetime.now(timezone.utc)
    rows = await db.exec(
        select(WebBridgeTabBinding)
        .where(
            WebBridgeTabBinding.pairing_id == pairing_id,
            WebBridgeTabBinding.expires_at > now,
        )
        .order_by(col(WebBridgeTabBinding.updated_at).desc())
    )
    newest_by_session: dict[UUID, WebBridgeTabBinding] = {}
    for binding in rows.all():
        newest_by_session.setdefault(binding.session_id, binding)
    return list(newest_by_session.values())


async def delete_tab_binding(
    db: AsyncSession, *, pairing_id: UUID, tab_id: int
) -> WebBridgeTabBinding | None:
    binding = (
        await db.exec(
            select(WebBridgeTabBinding).where(
                WebBridgeTabBinding.pairing_id == pairing_id,
                WebBridgeTabBinding.tab_id == tab_id,
            )
        )
    ).first()
    if binding is not None:
        session_bindings = (
            await db.exec(
                select(WebBridgeTabBinding).where(
                    WebBridgeTabBinding.pairing_id == pairing_id,
                    WebBridgeTabBinding.session_id == binding.session_id,
                )
            )
        ).all()
        for session_binding in session_bindings:
            await db.delete(session_binding)
        await db.flush()
    return binding


webbridge_pairing_code_store = WebBridgePairingCodeStore()
webbridge_interaction_rate_limiter = WebBridgeRateLimiter()
webbridge_ticket_store = WebBridgeTicketStore()
