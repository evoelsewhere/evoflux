from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.models.chat import ChatSession, SessionMessage
from app.services import interactive_message_service


@pytest.mark.asyncio
async def test_find_interactive_message_by_source_reads_channel_neutral_metadata(
    setup_db,
):
    """Remote retry lookup must find the persisted interactive-source row."""
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        chat_session = ChatSession(title="Remote task")
        db.add(chat_session)
        await db.flush()
        message = SessionMessage(
            session_id=chat_session.id,
            role="user",
            content="Continue the task",
            extra={
                "interactive_source": {
                    "key": "telegram:connection-1:42",
                    "state": "persisted",
                }
            },
        )
        db.add(message)
        await db.commit()

        found = await interactive_message_service.find_interactive_message_by_source(
            db,
            session_id=chat_session.id,
            source_key="telegram:connection-1:42",
        )

    assert found is not None
    assert found.id == message.id


@pytest.mark.asyncio
async def test_submit_interactive_message_rejects_reused_remote_source_key(
    setup_db,
):
    """A changed phone payload may not reuse an already persisted update key."""
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        chat_session = ChatSession(title="Remote task")
        db.add(chat_session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=chat_session.id,
                role="user",
                content="Original phone message",
                extra={
                    "interactive_source": {
                        "key": "telegram:connection-1:43",
                        "request_hash": "a" * 64,
                        "state": "persisted",
                    }
                },
            )
        )
        await db.commit()

        team = SimpleNamespace(
            user_message_lock=asyncio.Lock(),
            session_tags=frozenset(),
            permission_mode="auto",
            has_active_user_turn=lambda: False,
        )
        with pytest.raises(
            interactive_message_service.InteractiveMessageConflict,
            match="Idempotency-Key",
        ):
            await interactive_message_service.submit_persisted_interactive_message(
                db,
                session=chat_session,
                team=team,
                content="Changed phone message",
                source_key="telegram:connection-1:43",
                source_request_hash="b" * 64,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("reset_to_default", [False, True])
async def test_work_interactive_restore_syncs_persisted_workspace(
    setup_db, monkeypatch, tmp_path, reset_to_default
):
    from app.core import db as db_module

    session_id = uuid.uuid7()
    selected = tmp_path / "work-interactive-workspace"
    selected.mkdir()
    persisted_workspace = None if reset_to_default else str(selected)

    async with db_module.async_session_factory() as db:
        db.add(
            ChatSession(
                id=session_id,
                agent_name="lead",
                mode="work",
                workspace=persisted_workspace,
            )
        )
        await db.commit()

    team = SimpleNamespace(
        workspace=str(selected) if reset_to_default else None,
        session_tags=frozenset(),
        permission_mode="auto",
    )

    async def get_team(_session_id: str):
        return team

    monkeypatch.setattr(
        "app.services.team_manager.get_or_start_team_for_session",
        get_team,
    )

    async with db_module.async_session_factory() as db:
        (
            session,
            restored_team,
        ) = await interactive_message_service.resolve_team_for_session(
            db,
            str(session_id),
            require_existing=True,
        )

    assert session is not None
    assert restored_team is team
    assert team.workspace == persisted_workspace
