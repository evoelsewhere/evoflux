from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.chat import ChatSession
from app.remote import control


@pytest_asyncio.fixture
async def chat_session() -> ChatSession:
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Control test", mode="work", session_type="main")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


@pytest.mark.asyncio
async def test_set_permission_mode_persists_a_valid_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "ask")

    assert result.status == "ok"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode == "ask"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_bypass(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "bypass")

    assert result.status == "invalid"
    async with db_module.async_session_factory() as db:
        refreshed = await db.get(ChatSession, chat_session.id)
        assert refreshed is not None
        assert refreshed.permission_mode != "bypass"


@pytest.mark.asyncio
async def test_set_permission_mode_rejects_unknown_mode(chat_session: ChatSession) -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(chat_session.id), "nonsense")

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_set_permission_mode_not_found_for_unknown_session() -> None:
    async with db_module.async_session_factory() as db:
        result = await control.set_permission_mode(db, str(UUID(int=0)), "ask")

    assert result.status == "not_found"
