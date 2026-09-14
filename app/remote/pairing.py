"""One-tap pairing and principal authorization (AC-7, AC-8, AC-9, AC-10).

``PairingService`` is the transport-neutral home for:

- minting the single-use pairing token behind **Connect phone**'s QR code
  and ``https://t.me/<bot_username>?start=<token>`` deep link (AC-7);
- binding a channel-attested principal/destination to a connection once
  every check passes, and only then (AC-8);
- silencing every failure behind one indistinguishable refusal shape, with
  per-principal and connection-wide rate limiting so a flood of bad
  attempts cannot be used as a response/spam amplifier (AC-9);
- authorizing subsequent inbound actions against the live pairing row, with
  no caching lag after ``unpair`` (AC-10).

Nothing here imports a Telegram payload type — a later task's adapter
translates a raw update into a :class:`~app.remote.contracts.RemotePrincipal`
and booleans (``is_private_chat``, ``is_bot_sender``) before calling
``consume``.

Design choice — one pairing per connection (v1 product limit)
----------------------------------------------------------------
The spec's UI exposes **Connect phone** and a separate **Unpair phone**
action, and states "The UI can mint a replacement [token] without changing
the connection or bot token" for a lost/expired token. Read together, that
implies ``issue_link`` should stay a cheap, always-available, in-memory
operation — it never touches the database and never needs to know whether a
pairing already exists. The one-pairing-per-connection limit is instead
enforced at the single point a :class:`~app.models.remote.RemotePairing` row
would actually be written: :meth:`PairingService.consume`. If a connection
already has an active pairing, ``consume`` refuses — using the exact same
refusal shape as every other failure — rather than silently replacing it.
Re-pairing therefore requires an explicit ``unpair`` first, matching the
UI's two distinct actions.

Token custody
-------------
A pairing token is generated with ``secrets.token_urlsafe(16)`` (128 bits of
entropy, a strict subset of Telegram's ``[A-Za-z0-9_-]`` ``start``-parameter
alphabet, 22 characters — comfortably under the 64-character limit). It
lives only in an in-process dict guarded by a lock, with a ten-minute
monotonic expiry, and is removed the instant it is either successfully
consumed or found expired/invalid. It is never written to the database and
never logged.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import RemotePrincipal

__all__ = [
    "DEFAULT_CONNECTION_RATE_LIMIT",
    "DEFAULT_PER_PRINCIPAL_RATE_LIMIT",
    "DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
    "PAIRING_TOKEN_TTL_SECONDS",
    "PairingLink",
    "PairingService",
]

#: AC-7: the pairing token expires after ten minutes.
PAIRING_TOKEN_TTL_SECONDS = 600.0

#: AC-9 defaults: generous enough for a legitimate retry (e.g. a corrected
#: private-chat attempt) but bounded so pairing attempts cannot be used as a
#: response/spam amplifier. Callers may override per-instance.
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0
DEFAULT_PER_PRINCIPAL_RATE_LIMIT = 5
DEFAULT_CONNECTION_RATE_LIMIT = 20

_MAX_LABEL_LENGTH = 120


@dataclass(frozen=True)
class PairingLink:
    """Returned by :meth:`PairingService.issue_link`.

    ``url`` is the fully-formed deep link
    (``https://t.me/<bot_username>?start=<token>``). ``qr_payload`` is what
    the UI should encode into the QR code; for a Telegram deep link that is
    the identical URL, since scanning it must resolve to the same Start
    action as tapping **Open Telegram**. ``expires_at`` is a wall-clock UTC
    timestamp for display only — the token's actual liveness check uses an
    internal monotonic clock.
    """

    url: str
    qr_payload: str
    expires_at: datetime


class _SlidingWindowRateLimiter:
    """Per-key sliding-window limiter.

    Same algorithm as
    ``app.services.webbridge_pairing_service.WebBridgeRateLimiter``, kept as
    a small private copy here rather than imported: it is a generic,
    self-contained utility with no WebBridge-specific concept in it, and
    keeping it inside ``app/remote`` avoids a cross-feature dependency on an
    unrelated module for a dozen lines of logic.
    """

    def __init__(self, *, window_seconds: float) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, *, now: float | None = None) -> bool:
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self._window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(timestamp)
            return True


@dataclass
class _PendingToken:
    connection_id: UUID
    expires_at: float  # monotonic seconds


class PairingService:
    """Issues one-tap pairing links and authorizes paired principals."""

    def __init__(
        self,
        *,
        token_ttl_seconds: float = PAIRING_TOKEN_TTL_SECONDS,
        per_principal_rate_limit: int = DEFAULT_PER_PRINCIPAL_RATE_LIMIT,
        connection_rate_limit: int = DEFAULT_CONNECTION_RATE_LIMIT,
        rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        if token_ttl_seconds <= 0:
            raise ValueError("token_ttl_seconds must be positive")
        self._token_ttl_seconds = token_ttl_seconds
        self._per_principal_rate_limit = per_principal_rate_limit
        self._connection_rate_limit = connection_rate_limit
        self._tokens: dict[str, _PendingToken] = {}
        self._tokens_lock = threading.Lock()
        #: Serializes consume()'s whole check-then-act sequence (existing-
        #: pairing SELECT through token pop and RemotePairing insert) across
        #: concurrent calls. This app is single-process (see e.g.
        #: app/services/memory_stream_store.py's module docstring and
        #: WebBridgeTicketStore's equivalent per-instance lock in
        #: app/services/webbridge_pairing_service.py), so a plain
        #: asyncio.Lock — safely held across await points — is the
        #: right-sized fix: without it, two concurrent consume() calls can
        #: both pass the "no existing pairing" check before either commits
        #: (breaking the one-pairing-per-connection limit), or both race
        #: past a since-consumed token toward a duplicate insert.
        self._consume_lock = asyncio.Lock()
        self._rate_limiter = _SlidingWindowRateLimiter(
            window_seconds=rate_limit_window_seconds
        )

    # ── issue_link ───────────────────────────────────────────────────────

    def issue_link(
        self, connection: RemoteConnection, *, now: float | None = None
    ) -> PairingLink:
        """Mint a single-use pairing token and return its deep link.

        Pure in-memory operation (no database access): it can always be
        called to produce a fresh link, including as a replacement for a
        lost or expired token, without any connection-state check. See the
        module docstring for why the one-pairing-per-connection limit is
        enforced in :meth:`consume` instead.
        """
        issued_at = time.monotonic() if now is None else now
        token = secrets.token_urlsafe(16)
        with self._tokens_lock:
            self._tokens[token] = _PendingToken(
                connection_id=connection.id,
                expires_at=issued_at + self._token_ttl_seconds,
            )
        url = f"https://t.me/{connection.adapter_username}?start={token}"
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._token_ttl_seconds
        )
        return PairingLink(url=url, qr_payload=url, expires_at=expires_at)

    # ── consume ──────────────────────────────────────────────────────────

    async def consume(
        self,
        session: AsyncSession,
        token: str,
        principal: RemotePrincipal,
        *,
        is_private_chat: bool,
        is_bot_sender: bool,
        now: float | None = None,
    ) -> RemotePairing | None:
        """Attempt to bind *principal* using *token*.

        Returns the persisted :class:`~app.models.remote.RemotePairing` on
        success, or ``None`` on any failure: an invalid, expired, or
        already-used token; a token issued for a different connection; a
        non-private chat; a bot-authored sender; a connection that already
        has an active pairing; or a rate limit. Every failure path returns
        the identical ``None`` and writes nothing — a caller cannot infer
        *why* an attempt failed from the return value alone (AC-8, AC-9).

        A rejected attempt never consumes the token — only a *successful*
        bind does — so a legitimate retry from a corrected context (for
        example a private chat after a group-chat attempt) can still
        succeed before the token's real expiry.

        The existing-pairing check, token pop, and insert run as one atomic
        critical section under ``self._consume_lock`` so two concurrent
        calls cannot both observe "no existing pairing" and both insert, and
        cannot both pop the same token and both proceed toward insert.
        """
        timestamp = time.monotonic() if now is None else now

        if not self._rate_limiter.allow(
            f"pairing:principal:{principal.principal_id}",
            self._per_principal_rate_limit,
            now=timestamp,
        ):
            return None
        if not self._rate_limiter.allow(
            f"pairing:connection:{principal.connection_id}",
            self._connection_rate_limit,
            now=timestamp,
        ):
            return None

        async with self._consume_lock:
            with self._tokens_lock:
                pending = self._tokens.get(token)
            if pending is None or pending.expires_at <= timestamp:
                return None
            if pending.connection_id != principal.connection_id:
                return None
            if not is_private_chat or is_bot_sender:
                return None

            existing = (
                await session.exec(
                    select(RemotePairing).where(
                        RemotePairing.connection_id == principal.connection_id
                    )
                )
            ).first()
            if existing is not None:
                return None

            # Every check passed: burn the token now, then persist the
            # binding. Checking pop()'s return value is correct
            # defense-in-depth even under the lock — it is the only thing
            # standing between a racing/duplicate consume of the very same
            # token and an unhandled IntegrityError from a duplicate insert.
            with self._tokens_lock:
                popped = self._tokens.pop(token, None)
            if popped is None:
                return None

            display = principal.display[:_MAX_LABEL_LENGTH]
            pairing = RemotePairing(
                connection_id=principal.connection_id,
                principal_id=principal.principal_id,
                destination_id=principal.destination_id,
                label=display or "Paired device",
                display=display,
            )
            session.add(pairing)
            await session.commit()
            await session.refresh(pairing)
            return pairing

    # ── authorize ────────────────────────────────────────────────────────

    async def authorize(
        self,
        session: AsyncSession,
        *,
        connection_id: UUID,
        principal_id: str,
        now: float | None = None,
    ) -> RemotePairing | None:
        """Authorize an inbound action for *principal_id* on *connection_id*.

        Reads the pairing row fresh from the database on every call — there
        is no cache to go stale, so a pairing deleted by :meth:`unpair` is
        unauthorized on the very next call (AC-10). Also rate-limited,
        per-principal and connection-wide (AC-9), returning ``None`` (the
        same refusal as "no such pairing") when the limit is exceeded.
        """
        timestamp = time.monotonic() if now is None else now
        if not self._rate_limiter.allow(
            f"authorize:principal:{principal_id}",
            self._per_principal_rate_limit,
            now=timestamp,
        ):
            return None
        if not self._rate_limiter.allow(
            f"authorize:connection:{connection_id}",
            self._connection_rate_limit,
            now=timestamp,
        ):
            return None

        pairing = (
            await session.exec(
                select(RemotePairing).where(
                    RemotePairing.connection_id == connection_id,
                    RemotePairing.principal_id == principal_id,
                )
            )
        ).first()
        if pairing is None:
            return None
        pairing.last_seen_at = datetime.now(timezone.utc)
        session.add(pairing)
        await session.commit()
        await session.refresh(pairing)
        return pairing

    # ── unpair ───────────────────────────────────────────────────────────

    async def unpair(self, session: AsyncSession, connection_id: UUID) -> bool:
        """Delete *connection_id*'s pairing row(s), if any (AC-10).

        The delete is committed before returning, so a subsequent
        :meth:`authorize` call for the former principal fails immediately —
        there is no in-memory cache to invalidate. Returns ``True`` if a row
        was deleted.
        """
        rows = (
            await session.exec(
                select(RemotePairing).where(
                    RemotePairing.connection_id == connection_id
                )
            )
        ).all()
        if not rows:
            return False
        for row in rows:
            await session.delete(row)
        await session.commit()
        return True
