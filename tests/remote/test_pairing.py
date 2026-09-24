"""Tests for app/remote/pairing.py.

Exercises AC-7 (token custody), AC-8 (pairing authorization), AC-9 (silence
and rate limits), and AC-10 (immediate revocation) without ever touching a
real Telegram transport. ``is_private_chat``/``is_bot_sender`` stand in for
what a later task's Telegram adapter would classify from a raw update.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel import select

import app.core.db as db_module
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import RemotePrincipal
from app.remote.pairing import PairingLink, PairingService
from app.remote.pairing import (
    ConsumeOutcome,
    ConsumeResult,
    PairingCodeExpired,
    PairingCodeMismatch,
    PairingCodeRateLimited,
    _hash_pairing_code,
    _random_digits,
    _verify_pairing_code,
)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{22,64}")


def _extract_token(link: PairingLink) -> str:
    return parse_qs(urlparse(link.url).query)["start"][0]


def _assert_paired(outcome: ConsumeOutcome) -> RemotePairing:
    """Assert consume succeeded and return the pairing."""
    assert outcome.result == ConsumeResult.PAIRED, f"expected PAIRED, got {outcome.result}"
    assert outcome.pairing is not None
    return outcome.pairing


def _assert_not_paired(outcome: ConsumeOutcome) -> None:
    """Assert consume did not produce a pairing."""
    assert outcome.pairing is None
    assert outcome.result is not ConsumeResult.PAIRED


@pytest_asyncio.fixture
async def session():
    async with db_module.async_session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def connection(session) -> RemoteConnection:
    row = RemoteConnection(
        adapter="telegram",
        label="My phone",
        enabled=True,
        adapter_principal_id="bot-1",
        adapter_username="my_evoflux_bot",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest_asyncio.fixture
async def other_connection(session) -> RemoteConnection:
    row = RemoteConnection(
        adapter="telegram",
        label="Other install",
        enabled=True,
        adapter_principal_id="bot-2",
        adapter_username="other_bot",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.fixture
def service() -> PairingService:
    return PairingService()


def _principal(
    connection_id,
    *,
    principal_id="tg-user-1",
    destination_id="tg-chat-1",
    display="Alice",
) -> RemotePrincipal:
    return RemotePrincipal(
        connection_id=connection_id,
        principal_id=principal_id,
        destination_id=destination_id,
        display=display,
    )


# ── issue_link (AC-7) ────────────────────────────────────────────────────


def test_issue_link_token_is_url_safe_bounded_and_matches_username(
    service, connection
) -> None:
    link = service.issue_link(connection)

    assert link.url == f"https://t.me/my_evoflux_bot?start={_extract_token(link)}"
    assert link.qr_payload == link.url

    token = _extract_token(link)
    assert TOKEN_PATTERN.fullmatch(token)
    assert len(token) <= 64
    # secrets.token_urlsafe(16) => 128 bits of entropy, 22 chars.
    assert len(token) >= 22


@pytest.mark.asyncio
async def test_issue_link_never_touches_the_database(
    service, connection, session
) -> None:
    service.issue_link(connection)

    rows = (await session.exec(select(RemotePairing))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_issued_token_is_single_use(service, connection, session) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id)

    pairing = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    pairing = _assert_paired(pairing)

    second = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    _assert_not_paired(second)


# ── consume: success path (AC-8) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_persists_principal_and_destination_separately(
    service, connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(
        connection.id,
        principal_id="tg-user-42",
        destination_id="tg-chat-99",
        display="Bob",
    )

    pairing = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )

    pairing = _assert_paired(pairing)
    assert pairing.principal_id == "tg-user-42"
    assert pairing.destination_id == "tg-chat-99"
    assert pairing.principal_id != pairing.destination_id
    assert pairing.connection_id == connection.id

    rows = (await session.exec(select(RemotePairing))).all()
    assert [row.id for row in rows] == [pairing.id]


# ── consume: expiry (AC-7) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_rejects_expired_token(service, connection, session) -> None:
    link = service.issue_link(connection, now=1_000.0)
    token = _extract_token(link)
    principal = _principal(connection.id)

    result = await service.consume(
        session,
        token,
        principal,
        is_private_chat=True,
        is_bot_sender=False,
        now=1_000.0 + 600.0 + 1.0,  # just past the ten-minute expiry
    )

    _assert_not_paired(result)


@pytest.mark.asyncio
async def test_consume_accepts_token_right_before_expiry(
    service, connection, session
) -> None:
    link = service.issue_link(connection, now=1_000.0)
    token = _extract_token(link)
    principal = _principal(connection.id)

    result = await service.consume(
        session,
        token,
        principal,
        is_private_chat=True,
        is_bot_sender=False,
        now=1_000.0 + 599.0,
    )

    result = _assert_paired(result)


# ── consume: silence and refusal shape (AC-9) ────────────────────────────


@pytest.mark.asyncio
async def test_consume_unknown_token_is_refused_silently(
    service, connection, session
) -> None:
    principal = _principal(connection.id)
    result = await service.consume(
        session,
        "not-a-real-token",
        principal,
        is_private_chat=True,
        is_bot_sender=False,
    )
    _assert_not_paired(result)


@pytest.mark.asyncio
async def test_consume_rejects_group_chat_without_burning_token(
    service, connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id)

    group_attempt = await service.consume(
        session, token, principal, is_private_chat=False, is_bot_sender=False
    )
    _assert_not_paired(group_attempt)

    # A legitimate retry from a private chat still succeeds with the same
    # token: a rejected attempt must not burn it.
    retry = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    retry = _assert_paired(retry)


@pytest.mark.asyncio
async def test_consume_rejects_bot_sender_without_burning_token(
    service, connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id)

    bot_attempt = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=True
    )
    _assert_not_paired(bot_attempt)

    retry = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    retry = _assert_paired(retry)


@pytest.mark.asyncio
async def test_consume_rejects_token_issued_for_a_different_connection(
    service, connection, other_connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    wrong_principal = _principal(other_connection.id)

    result = await service.consume(
        session, token, wrong_principal, is_private_chat=True, is_bot_sender=False
    )
    _assert_not_paired(result)

    # The token remains valid for the connection it was actually issued for.
    right_principal = _principal(connection.id)
    retry = await service.consume(
        session, token, right_principal, is_private_chat=True, is_bot_sender=False
    )
    retry = _assert_paired(retry)


@pytest.mark.asyncio
async def test_consume_enforces_one_pairing_per_connection(
    service, connection, session
) -> None:
    first_link = service.issue_link(connection)
    first_token = _extract_token(first_link)
    first_principal = _principal(
        connection.id, principal_id="tg-user-1", destination_id="tg-chat-1"
    )

    first = await service.consume(
        session, first_token, first_principal, is_private_chat=True, is_bot_sender=False
    )
    first = _assert_paired(first)

    second_link = service.issue_link(connection)
    second_token = _extract_token(second_link)
    second_principal = _principal(
        connection.id, principal_id="tg-user-2", destination_id="tg-chat-2"
    )

    second = await service.consume(
        session,
        second_token,
        second_principal,
        is_private_chat=True,
        is_bot_sender=False,
    )
    _assert_not_paired(second)

    rows = (await session.exec(select(RemotePairing))).all()
    assert [row.principal_id for row in rows] == ["tg-user-1"]

    # Unpairing frees the connection for a fresh pairing, including with the
    # still-unexpired second token (a rejected attempt did not burn it).
    await service.unpair(session, connection.id)
    retry = await service.consume(
        session,
        second_token,
        second_principal,
        is_private_chat=True,
        is_bot_sender=False,
    )
    retry = _assert_paired(retry)
    assert retry.principal_id == "tg-user-2"


@pytest.mark.asyncio
async def test_refusals_are_uniform_regardless_of_reason(
    service, connection, other_connection, session
) -> None:
    """AC-9: an unpaired sender must not be able to distinguish *why* an
    attempt failed from the response shape. Every failure mode here returns
    the identical ``None``."""
    link = service.issue_link(connection)
    token = _extract_token(link)

    unknown_token_result = await service.consume(
        session,
        "garbage",
        _principal(connection.id),
        is_private_chat=True,
        is_bot_sender=False,
    )
    group_chat_result = await service.consume(
        session,
        token,
        _principal(connection.id),
        is_private_chat=False,
        is_bot_sender=False,
    )
    bot_sender_result = await service.consume(
        session,
        token,
        _principal(connection.id),
        is_private_chat=True,
        is_bot_sender=True,
    )
    wrong_connection_result = await service.consume(
        session,
        token,
        _principal(other_connection.id),
        is_private_chat=True,
        is_bot_sender=False,
    )

    # AC-9: every non-pairing failure returns INVALID — the caller cannot
    # distinguish *why* the attempt failed.  ALREADY_PAIRED is reserved for
    # the concurrent-scan race where the token was valid but the connection
    # already had a pairing.
    for outcome in (
        unknown_token_result,
        group_chat_result,
        bot_sender_result,
        wrong_connection_result,
    ):
        assert outcome.result is ConsumeResult.INVALID
        assert outcome.pairing is None


# ── rate limiting (AC-9) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consume_enforces_per_principal_rate_limit(connection, session) -> None:
    limited_service = PairingService(per_principal_rate_limit=1)
    link = limited_service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id)

    # First attempt consumes the rate-limit budget (even though it also
    # fails on chat type, the limiter must have already counted it).
    await limited_service.consume(
        session, token, principal, is_private_chat=False, is_bot_sender=False, now=1.0
    )
    second = await limited_service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False, now=1.0
    )

    _assert_not_paired(second)


@pytest.mark.asyncio
async def test_consume_enforces_connection_wide_rate_limit(connection, session) -> None:
    limited_service = PairingService(connection_rate_limit=1)
    link = limited_service.issue_link(connection)
    token = _extract_token(link)

    await limited_service.consume(
        session,
        token,
        _principal(connection.id, principal_id="user-a"),
        is_private_chat=False,
        is_bot_sender=False,
        now=1.0,
    )
    second = await limited_service.consume(
        session,
        token,
        _principal(connection.id, principal_id="user-b"),
        is_private_chat=True,
        is_bot_sender=False,
        now=1.0,
    )

    _assert_not_paired(second)


@pytest.mark.asyncio
async def test_consume_rate_limit_window_recovers_over_time(
    connection, session
) -> None:
    limited_service = PairingService(
        per_principal_rate_limit=1, rate_limit_window_seconds=10.0
    )
    link = limited_service.issue_link(connection, now=0.0)
    token = _extract_token(link)
    principal = _principal(connection.id)

    blocked = await limited_service.consume(
        session, token, principal, is_private_chat=False, is_bot_sender=False, now=1.0
    )
    _assert_not_paired(blocked)

    later = await limited_service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False, now=12.0
    )
    later = _assert_paired(later)


# ── authorize (AC-8, AC-9, AC-10) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_returns_pairing_for_the_bound_principal(
    service, connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id, principal_id="tg-user-7")
    await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )

    authorized = await service.authorize(
        session, connection_id=connection.id, principal_id="tg-user-7"
    )
    assert authorized is not None
    assert authorized.principal_id == "tg-user-7"


@pytest.mark.asyncio
async def test_authorize_refuses_unpaired_principal(
    service, connection, session
) -> None:
    result = await service.authorize(
        session, connection_id=connection.id, principal_id="nobody"
    )
    assert result is None


@pytest.mark.asyncio
async def test_authorize_does_not_authorize_destination_id_as_principal(
    service, connection, session
) -> None:
    """principal_id and destination_id must never be collapsed/defaulted
    from one another."""
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(
        connection.id, principal_id="tg-user-1", destination_id="tg-chat-1"
    )
    await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )

    # destination_id must not authorize as if it were the principal_id.
    result = await service.authorize(
        session, connection_id=connection.id, principal_id="tg-chat-1"
    )
    assert result is None


@pytest.mark.asyncio
async def test_authorize_is_rate_limited(connection, session) -> None:
    limited_service = PairingService(per_principal_rate_limit=1)
    link = limited_service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id, principal_id="tg-user-1")
    await limited_service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False, now=1.0
    )

    first = await limited_service.authorize(
        session, connection_id=connection.id, principal_id="tg-user-1", now=2.0
    )
    second = await limited_service.authorize(
        session, connection_id=connection.id, principal_id="tg-user-1", now=2.0
    )

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_unpair_revokes_authorization_immediately(
    service, connection, session
) -> None:
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(connection.id, principal_id="tg-user-1")
    await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    assert (
        await service.authorize(
            session, connection_id=connection.id, principal_id="tg-user-1"
        )
        is not None
    )

    deleted = await service.unpair(session, connection.id)
    assert deleted is True

    # No caching lag: the very next authorize() call must fail.
    result = await service.authorize(
        session, connection_id=connection.id, principal_id="tg-user-1"
    )
    assert result is None

    rows = (await session.exec(select(RemotePairing))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_unpair_on_connection_without_a_pairing_returns_false(
    service, connection, session
) -> None:
    assert await service.unpair(session, connection.id) is False


@pytest.mark.asyncio
async def test_unpair_unknown_connection_returns_false(service, session) -> None:
    assert await service.unpair(session, uuid4()) is False


# ── concurrency: unsynchronized check-then-act race (fix follow-up) ──────


@pytest.mark.asyncio
async def test_concurrent_consume_with_different_tokens_only_binds_one_pairing(
    service, connection, session
) -> None:
    """Two different valid tokens for the same connection, consumed near-
    simultaneously via asyncio.gather, must not both pass the
    one-pairing-per-connection check before either commits — only one may
    succeed, the other must get the uniform refusal."""
    first_link = service.issue_link(connection)
    first_token = _extract_token(first_link)
    second_link = service.issue_link(connection)
    second_token = _extract_token(second_link)

    first_principal = _principal(
        connection.id, principal_id="user-a", destination_id="chat-a"
    )
    second_principal = _principal(
        connection.id, principal_id="user-b", destination_id="chat-b"
    )

    results = await asyncio.gather(
        service.consume(
            session,
            first_token,
            first_principal,
            is_private_chat=True,
            is_bot_sender=False,
        ),
        service.consume(
            session,
            second_token,
            second_principal,
            is_private_chat=True,
            is_bot_sender=False,
        ),
    )

    successes = [r for r in results if r.result == ConsumeResult.PAIRED]
    refusals = [r for r in results if r.result != ConsumeResult.PAIRED]
    assert len(successes) == 1
    assert len(refusals) == 1
    # The losing scanner gets ALREADY_PAIRED (not a silent INVALID).
    assert refusals[0].result == ConsumeResult.ALREADY_PAIRED

    rows = (await session.exec(select(RemotePairing))).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_consume_with_the_same_token_only_succeeds_once(
    service, connection, session
) -> None:
    """The same token consumed twice concurrently (e.g. a duplicate inbound
    delivery) must yield exactly one success and one uniform refusal — never
    an unhandled exception from a duplicate insert."""
    link = service.issue_link(connection)
    token = _extract_token(link)
    principal = _principal(
        connection.id, principal_id="user-a", destination_id="chat-a"
    )

    results = await asyncio.gather(
        service.consume(
            session, token, principal, is_private_chat=True, is_bot_sender=False
        ),
        service.consume(
            session, token, principal, is_private_chat=True, is_bot_sender=False
        ),
    )

    successes = [r for r in results if r.result == ConsumeResult.PAIRED]
    refusals = [r for r in results if r.result != ConsumeResult.PAIRED]
    assert len(successes) == 1
    assert len(refusals) == 1

    rows = (await session.exec(select(RemotePairing))).all()
    assert len(rows) == 1


# ── phone-first pairing code tests ────────────────────────────────────────


def _digits(raw: str) -> str:
    """Strip spaces from a display code to get raw digits."""
    return raw.replace(" ", "")


# -- unit tests for helpers --


@pytest.mark.asyncio
async def test_random_digits_returns_correct_length() -> None:
    for length in (4, 8, 12):
        result = _random_digits(length)
        assert len(result) == length
        assert result.isdigit()


@pytest.mark.asyncio
async def test_hash_and_verify_round_trip() -> None:
    code = "12345678"
    code_hash = _hash_pairing_code(code)
    assert _verify_pairing_code(code, code_hash) is True
    assert _verify_pairing_code("87654321", code_hash) is False


@pytest.mark.asyncio
async def test_verify_pairing_code_with_none_hash_returns_false() -> None:
    assert _verify_pairing_code("12345678", None) is False


# -- issue_pair_code tests --


@pytest.mark.asyncio
async def test_issue_pair_code_creates_pending_row(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id)

    assert len(_digits(result.display_code)) == 8
    assert len(result.raw_code) == 8
    assert result.raw_code.isdigit()
    assert result.expires_at > datetime.now(timezone.utc)

    rows = (await session.exec(select(RemotePairing))).all()
    assert len(rows) == 1
    assert rows[0].pair_code_hash is not None
    assert rows[0].pair_code_expires_at is not None
    assert rows[0].principal_id == ""  # not yet bound


@pytest.mark.asyncio
async def test_issue_pair_code_replaces_stale_pending_code(
    service: PairingService,
    connection,
    session,
) -> None:
    first = await service.issue_pair_code(session, connection.id)
    second = await service.issue_pair_code(session, connection.id)

    rows = (await session.exec(select(RemotePairing))).all()
    assert len(rows) == 1
    assert second.raw_code != first.raw_code


# -- verify_pair_code tests --


@pytest.mark.asyncio
async def test_verify_pair_code_with_correct_code_succeeds(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    pairing = await service.verify_pair_code(
        session,
        connection_id=connection.id,
        principal=principal,
        raw_code=result.raw_code,
        now=1000.0,
    )
    # verify_pair_code returns RemotePairing | None (not ConsumeOutcome).
    assert pairing is not None
    assert pairing.principal_id == "tg-user-1"
    assert pairing.destination_id == "tg-chat-1"
    assert pairing.pair_code_hash is None
    assert pairing.pair_code_expires_at is None


@pytest.mark.asyncio
async def test_verify_pair_code_with_wrong_code_raises_mismatch(
    service: PairingService,
    connection,
    session,
) -> None:
    await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    with pytest.raises(PairingCodeMismatch):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code="00000000",
            now=1000.0,
        )


@pytest.mark.asyncio
async def test_verify_pair_code_expired_code_raises_expired(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    with pytest.raises(PairingCodeExpired):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code=result.raw_code,
            now=1000.0 + 601.0,
        )

    rows = (await session.exec(select(RemotePairing))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_verify_pair_code_rate_limited_after_max_attempts(
    service: PairingService,
    connection,
    session,
) -> None:
    await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    for _ in range(5):
        with pytest.raises(PairingCodeMismatch):
            await service.verify_pair_code(
                session,
                connection_id=connection.id,
                principal=principal,
                raw_code="99999999",
                now=1000.0,
            )

    with pytest.raises(PairingCodeRateLimited):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code="99999999",
            now=1000.0,
        )


@pytest.mark.asyncio
async def test_verify_pair_code_bot_sender_raises_mismatch(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    with pytest.raises(PairingCodeMismatch):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code=result.raw_code,
            now=1000.0,
            is_bot_sender=True,
        )


@pytest.mark.asyncio
async def test_verify_pair_code_non_private_chat_raises_mismatch(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    with pytest.raises(PairingCodeMismatch):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code=result.raw_code,
            now=1000.0,
            is_private_chat=False,
        )


@pytest.mark.asyncio
async def test_verify_pair_code_no_pending_code_raises_mismatch(
    service: PairingService,
    connection,
    session,
) -> None:
    principal = _principal(connection.id)

    with pytest.raises(PairingCodeMismatch):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=principal,
            raw_code="12345678",
            now=1000.0,
        )


@pytest.mark.asyncio
async def test_verify_pair_code_wrong_connection_raises_mismatch(
    service: PairingService,
    connection,
    session,
) -> None:
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    other_principal = _principal(uuid4())

    with pytest.raises(PairingCodeMismatch):
        await service.verify_pair_code(
            session,
            connection_id=connection.id,
            principal=other_principal,
            raw_code=result.raw_code,
            now=1000.0,
        )


@pytest.mark.asyncio
async def test_full_pairing_code_lifecycle(
    service: PairingService,
    connection,
    session,
) -> None:
    """End-to-end: issue code, verify with correct code, authorize succeeds."""
    result = await service.issue_pair_code(session, connection.id, now=1000.0)
    principal = _principal(connection.id)

    pairing = await service.verify_pair_code(
        session,
        connection_id=connection.id,
        principal=principal,
        raw_code=result.raw_code,
        now=1000.0,
    )
    assert pairing.principal_id == "tg-user-1"

    authorized = await service.authorize(
        session, connection_id=connection.id, principal_id="tg-user-1"
    )
    assert authorized is not None
    assert authorized.principal_id == "tg-user-1"
