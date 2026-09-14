"""Tests for app/remote/pairing.py.

Exercises AC-7 (token custody), AC-8 (pairing authorization), AC-9 (silence
and rate limits), and AC-10 (immediate revocation) without ever touching a
real Telegram transport. ``is_private_chat``/``is_bot_sender`` stand in for
what a later task's Telegram adapter would classify from a raw update.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlmodel import select

import app.core.db as db_module
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import RemotePrincipal
from app.remote.pairing import PairingLink, PairingService

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{22,64}")


def _extract_token(link: PairingLink) -> str:
    return parse_qs(urlparse(link.url).query)["start"][0]


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


def _principal(connection_id, *, principal_id="tg-user-1", destination_id="tg-chat-1", display="Alice") -> RemotePrincipal:
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
async def test_issue_link_never_touches_the_database(service, connection, session) -> None:
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
    assert pairing is not None

    second = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    assert second is None


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

    assert pairing is not None
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

    assert result is None


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

    assert result is not None


# ── consume: silence and refusal shape (AC-9) ────────────────────────────


@pytest.mark.asyncio
async def test_consume_unknown_token_is_refused_silently(
    service, connection, session
) -> None:
    principal = _principal(connection.id)
    result = await service.consume(
        session, "not-a-real-token", principal, is_private_chat=True, is_bot_sender=False
    )
    assert result is None


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
    assert group_attempt is None

    # A legitimate retry from a private chat still succeeds with the same
    # token: a rejected attempt must not burn it.
    retry = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    assert retry is not None


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
    assert bot_attempt is None

    retry = await service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False
    )
    assert retry is not None


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
    assert result is None

    # The token remains valid for the connection it was actually issued for.
    right_principal = _principal(connection.id)
    retry = await service.consume(
        session, token, right_principal, is_private_chat=True, is_bot_sender=False
    )
    assert retry is not None


@pytest.mark.asyncio
async def test_consume_enforces_one_pairing_per_connection(
    service, connection, session
) -> None:
    first_link = service.issue_link(connection)
    first_token = _extract_token(first_link)
    first_principal = _principal(connection.id, principal_id="tg-user-1", destination_id="tg-chat-1")

    first = await service.consume(
        session, first_token, first_principal, is_private_chat=True, is_bot_sender=False
    )
    assert first is not None

    second_link = service.issue_link(connection)
    second_token = _extract_token(second_link)
    second_principal = _principal(connection.id, principal_id="tg-user-2", destination_id="tg-chat-2")

    second = await service.consume(
        session, second_token, second_principal, is_private_chat=True, is_bot_sender=False
    )
    assert second is None

    rows = (await session.exec(select(RemotePairing))).all()
    assert [row.principal_id for row in rows] == ["tg-user-1"]

    # Unpairing frees the connection for a fresh pairing, including with the
    # still-unexpired second token (a rejected attempt did not burn it).
    await service.unpair(session, connection.id)
    retry = await service.consume(
        session, second_token, second_principal, is_private_chat=True, is_bot_sender=False
    )
    assert retry is not None
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
        session, "garbage", _principal(connection.id), is_private_chat=True, is_bot_sender=False
    )
    group_chat_result = await service.consume(
        session, token, _principal(connection.id), is_private_chat=False, is_bot_sender=False
    )
    bot_sender_result = await service.consume(
        session, token, _principal(connection.id), is_private_chat=True, is_bot_sender=True
    )
    wrong_connection_result = await service.consume(
        session, token, _principal(other_connection.id), is_private_chat=True, is_bot_sender=False
    )

    assert (
        unknown_token_result
        is group_chat_result
        is bot_sender_result
        is wrong_connection_result
        is None
    )


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

    assert second is None


@pytest.mark.asyncio
async def test_consume_enforces_connection_wide_rate_limit(
    connection, session
) -> None:
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

    assert second is None


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
    assert blocked is None

    later = await limited_service.consume(
        session, token, principal, is_private_chat=True, is_bot_sender=False, now=12.0
    )
    assert later is not None


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
