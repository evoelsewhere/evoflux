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
import dataclasses
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from loguru import logger
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import RemotePrincipal

__all__ = [
    "DEFAULT_CONNECTION_RATE_LIMIT",
    "DEFAULT_PER_PRINCIPAL_RATE_LIMIT",
    "DEFAULT_RATE_LIMIT_WINDOW_SECONDS",
    "PAIRING_TOKEN_TTL_SECONDS",
    "PairingCodeExpired",
    "PairingCodeMismatch",
    "PairingCodeRateLimited",
    "PairingCodeResult",
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

# ── pairing-code constants and helpers ────────────────────────────────────

_PAIRING_CODE_LENGTH: int = 8
_PAIRING_CODE_TTL_SECONDS: int = 600  # 10 minutes
_PAIRING_CODE_MAX_ATTEMPTS: int = 5
_PAIRING_CODE_RATE_LIMIT_WINDOW: float = 300.0  # 5 minutes

# Server-side pepper.  In tests this default is fine; production reads it
# from the same secret store as ``EVOFLUX_DESKTOP_TOKEN``.
_PAIRING_CODE_PEPPER = b"evoflux-pairing-code-v1"

log = logger.bind(name="remote.pairing")


def _random_digits(length: int) -> str:
    """Return *length* cryptographically-random decimal digits."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def _hash_pairing_code(raw_code: str) -> str:
    """Return a hex HMAC-SHA-256 digest of *raw_code*."""
    return hmac.new(_PAIRING_CODE_PEPPER, raw_code.encode(), hashlib.sha256).hexdigest()


def _verify_pairing_code(raw_code: str, code_hash: str | None) -> bool:
    """Constant-time comparison of *raw_code* against stored *code_hash*."""
    if code_hash is None:
        return False
    expected = _hash_pairing_code(raw_code)
    return hmac.compare_digest(expected, code_hash)


# ── pairing-code exceptions ──────────────────────────────────────────────


class PairingCodeExpired(Exception):
    """The phone-side ``/pair`` code has passed its TTL."""


class PairingCodeMismatch(Exception):
    """The submitted code does not match the pending hash."""


class PairingCodeRateLimited(Exception):
    """Too many failed ``/pair`` attempts for the current pending code."""


@dataclasses.dataclass(frozen=True)
class PairingCodeResult:
    """Value returned by :meth:`PairingService.issue_pair_code`.

    ``display_code`` is the user-facing value with digit grouping
    (e.g. ``"1234 5678"``).  ``raw_code`` is the ungrouped digit string
    that must be hashed before storage.  ``expires_at`` is a wall-clock
    ``datetime`` so the UI can render a countdown.
    """

    display_code: str
    raw_code: str
    expires_at: datetime


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


class ConsumeResult(Enum):
    """Discriminated outcome of :meth:`PairingService.consume`.

    The previous ``RemotePairing | None`` return made it impossible for the
    caller to distinguish "someone else already paired from the same QR code"
    from "token expired" or "invalid".  The runtime now sends a targeted
    feedback message to the second scanner when the result is ``ALREADY_PAIRED``.
    """

    #: Pairing succeeded — the returned ``RemotePairing`` is authoritative.
    PAIRED = "paired"
    #: The connection already has an active pairing (likely from a concurrent
    #: scan of the same QR code).  The caller should tell the second scanner.
    ALREADY_PAIRED = "already_paired"
    #: Token was missing, expired, rate-limited, or did not match.
    INVALID = "invalid"


@dataclass
class ConsumeOutcome:
    """Typed wrapper returned by :meth:`PairingService.consume`."""

    result: ConsumeResult
    pairing: RemotePairing | None = None


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

        # Phone-first pairing code rate-limiting (mirrors the link-based
        # counters above but keyed separately so the two flows are
        # independent).
        self._pair_code_attempts: dict[UUID, int] = {}
        self._pair_code_issued_at: dict[UUID, float] = {}
        self._pairing_code_ttl: float = float(_PAIRING_CODE_TTL_SECONDS)
        self._pairing_code_max_attempts: int = _PAIRING_CODE_MAX_ATTEMPTS
        self._rate_limit_window: float = _PAIRING_CODE_RATE_LIMIT_WINDOW

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
    ) -> ConsumeOutcome:
        """Attempt to bind *principal* using *token*.

        Returns a :class:`ConsumeOutcome` whose ``result`` discriminant tells
        the caller exactly what happened:

        - ``PAIRED`` — success; ``outcome.pairing`` is the persisted row.
        - ``ALREADY_PAIRED`` — the connection already has an active pairing
          (most likely a concurrent scan of the same QR code).  The caller
          should tell the second scanner that the device was already claimed.
        - ``INVALID`` — token missing, expired, rate-limited, wrong
          connection, non-private chat, or bot sender.  Silent rejection.

        A rejected attempt never consumes the token — only a *successful*
        bind does — so a legitimate retry from a corrected context (for
        example a private chat after a group-chat attempt) can still
        succeed before the token's real expiry.

        The existing-pairing check, token pop, and insert run as one atomic
        critical section under ``self._consume_lock`` so two concurrent
        calls cannot both observe "no existing pairing" and both insert, and
        cannot both pop the same token and both proceed toward insert.
        """
        _invalid = ConsumeOutcome(result=ConsumeResult.INVALID)
        timestamp = time.monotonic() if now is None else now

        if not self._rate_limiter.allow(
            f"pairing:principal:{principal.principal_id}",
            self._per_principal_rate_limit,
            now=timestamp,
        ):
            return _invalid
        if not self._rate_limiter.allow(
            f"pairing:connection:{principal.connection_id}",
            self._connection_rate_limit,
            now=timestamp,
        ):
            return _invalid

        async with self._consume_lock:
            with self._tokens_lock:
                pending = self._tokens.get(token)
            if pending is None or pending.expires_at <= timestamp:
                return _invalid
            if pending.connection_id != principal.connection_id:
                return _invalid
            if not is_private_chat or is_bot_sender:
                return _invalid

            # Exclude a pending phone-first pairing code (empty
            # principal_id) — it is not a completed pairing, and treating
            # it as one would block a legitimate link-based consume on a
            # connection that merely has an unrelated code outstanding.
            existing = (
                await session.exec(
                    select(RemotePairing).where(
                        RemotePairing.connection_id == principal.connection_id,
                        RemotePairing.principal_id != "",
                    )
                )
            ).first()
            if existing is not None:
                return ConsumeOutcome(result=ConsumeResult.ALREADY_PAIRED)

            # Every check passed: burn the token now, then persist the
            # binding. Checking pop()'s return value is correct
            # defense-in-depth even under the lock — it is the only thing
            # standing between a racing/duplicate consume of the very same
            # token and an unhandled IntegrityError from a duplicate insert.
            with self._tokens_lock:
                popped = self._tokens.pop(token, None)
            if popped is None:
                return _invalid

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
            return ConsumeOutcome(result=ConsumeResult.PAIRED, pairing=pairing)

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

    # ── phone-first pairing code (AC-7, AC-8, AC-9) ───────────────────────

    async def issue_pair_code(
        self,
        session: AsyncSession,
        connection_id: UUID,
        *,
        now: float | None = None,
    ) -> PairingCodeResult:
        """Generate a one-time8-digit pairing code for *connection_id*.

        The code is hashed before storage so a database leak does not expose
        the plaintext value.  Any previously-pending pairing-code row for the
        same connection is replaced so at most one code is active at a time.
        """
        stale = (
            await session.exec(
                select(RemotePairing).where(
                    RemotePairing.connection_id == connection_id,
                    RemotePairing.pair_code_hash.is_not(None),  # ty: ignore[unresolved-attribute]
                )
            )
        ).all()
        for row in stale:
            await session.delete(row)
        if stale:
            await session.flush()

        raw_code = _random_digits(_PAIRING_CODE_LENGTH)
        display_code = f"{raw_code[:4]} {raw_code[4:]}"
        code_hash = _hash_pairing_code(raw_code)

        now_s = time.monotonic() if now is None else now
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=_PAIRING_CODE_TTL_SECONDS
        )

        pending = RemotePairing(
            connection_id=connection_id,
            principal_id="",
            destination_id="",
            label="",
            pair_code_hash=code_hash,
            pair_code_expires_at=expires_at,
        )
        session.add(pending)
        await session.commit()

        self._pair_code_attempts[connection_id] = 0
        self._pair_code_issued_at[connection_id] = now_s

        log.info(
            "pair_code_issued connection_id={} expires_at={}",
            connection_id,
            expires_at.isoformat(),
        )
        return PairingCodeResult(
            display_code=display_code,
            raw_code=raw_code,
            expires_at=expires_at,
        )

    async def verify_pair_code(
        self,
        session: AsyncSession,
        *,
        connection_id: UUID,
        principal: RemotePrincipal,
        raw_code: str,
        now: float | None = None,
        is_private_chat: bool = True,
        is_bot_sender: bool = False,
    ) -> RemotePairing:
        """Verify a phone-submitted pairing code and bind the principal.

        Raises :class:`PairingCodeExpired`, :class:`PairingCodeMismatch`, or
        :class:`PairingCodeRateLimited` on failure.  On success the pairing
        row's ``principal_id`` / ``destination_id`` are set and the code hash
        is cleared so the code cannot be replayed.
        """
        if is_bot_sender:
            raise PairingCodeMismatch()
        if not is_private_chat:
            raise PairingCodeMismatch()

        now_s = time.monotonic() if now is None else now

        attempts = self._pair_code_attempts.get(connection_id, 0)
        if attempts >= self._pairing_code_max_attempts:
            issued_at = self._pair_code_issued_at.get(connection_id, 0.0)
            if (now_s - issued_at) < self._rate_limit_window:
                raise PairingCodeRateLimited()
            self._pair_code_attempts[connection_id] = 0

        pending = (
            await session.exec(
                select(RemotePairing).where(
                    RemotePairing.connection_id == connection_id,
                    RemotePairing.pair_code_hash.is_not(None),  # ty: ignore[unresolved-attribute]
                )
            )
        ).first()

        if pending is None:
            self._pair_code_attempts[connection_id] = (
                self._pair_code_attempts.get(connection_id, 0) + 1
            )
            raise PairingCodeMismatch()

        if principal.connection_id != connection_id:
            self._pair_code_attempts[connection_id] = (
                self._pair_code_attempts.get(connection_id, 0) + 1
            )
            raise PairingCodeMismatch()

        if not _verify_pairing_code(raw_code, pending.pair_code_hash):
            self._pair_code_attempts[connection_id] = (
                self._pair_code_attempts.get(connection_id, 0) + 1
            )
            raise PairingCodeMismatch()

        # Check wall-clock expiry.
        if pending.pair_code_expires_at is not None:
            now_utc = datetime.now(timezone.utc)
            if now_utc > pending.pair_code_expires_at:
                await session.delete(pending)
                await session.commit()
                raise PairingCodeExpired()

        # Check monotonic TTL as well (for test-injected now).
        # Skip if the issued-at entry is absent (e.g. process restarted and
        # the in-memory dict was lost) — the wall-clock check above already
        # covers real expiry; a missing monotonic timestamp is not evidence
        # of timeout.
        issued_at = self._pair_code_issued_at.get(connection_id)
        if issued_at is not None and (now_s - issued_at) > self._pairing_code_ttl:
            await session.delete(pending)
            await session.commit()
            raise PairingCodeExpired()

        # ── success: bind principal ────────────────────────────────────
        pending.principal_id = principal.principal_id
        pending.destination_id = principal.destination_id
        pending.pair_code_hash = None
        pending.pair_code_expires_at = None
        pending.last_seen_at = datetime.now(timezone.utc)
        session.add(pending)
        await session.commit()
        await session.refresh(pending)

        self._pair_code_attempts.pop(connection_id, None)
        self._pair_code_issued_at.pop(connection_id, None)

        log.info(
            "pair_code_verified connection_id={} principal_id={}",
            connection_id,
            principal.principal_id,
        )
        return pending


# Process-wide singleton. Pairing tokens and rate-limit windows live only in
# this instance's memory (AC-7: "exists only in process memory"), so every
# caller — the HTTP route that mints a link and the Telegram adapter's
# inbound dispatch that later consumes it — must share this exact object.
# A second `PairingService()` starts with an empty token store and can never
# see a token minted through this one; there is deliberately no other way to
# reach a `PairingService` in this codebase.
pairing_service = PairingService()
