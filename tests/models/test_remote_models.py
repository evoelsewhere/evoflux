"""Tests for app/models/remote.py — RemotePairing.notify_scope column default.

Follows the ``session``/``connection`` fixture convention already used by
``tests/remote/test_pairing.py`` and ``tests/remote/test_runtime.py`` (there
is no shared ``db_session``/``remote_connection`` fixture in this codebase to
reuse instead).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlmodel import select

import app.core.db as db_module
from app.models.remote import RemoteConnection, RemotePairing


@pytest_asyncio.fixture
async def session():
    async with db_module.async_session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def remote_connection(session) -> RemoteConnection:
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


@pytest.mark.asyncio
async def test_new_pairing_defaults_notify_scope_to_all(session, remote_connection):
    pairing = RemotePairing(
        connection_id=remote_connection.id,
        principal_id="user-1",
        destination_id="chat-1",
        label="My phone",
    )
    session.add(pairing)
    await session.commit()
    await session.refresh(pairing)
    assert pairing.notify_scope == "all"


@pytest.mark.asyncio
async def test_notify_scope_round_trips_a_non_default_value(session, remote_connection):
    pairing = RemotePairing(
        connection_id=remote_connection.id,
        principal_id="user-1",
        destination_id="chat-1",
        label="My phone",
        notify_scope="phone_initiated",
    )
    session.add(pairing)
    await session.commit()
    await session.refresh(pairing)

    reloaded = (
        await session.exec(
            select(RemotePairing).where(RemotePairing.id == pairing.id)
        )
    ).one()
    assert reloaded.notify_scope == "phone_initiated"
