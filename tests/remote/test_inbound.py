"""Remote natural-language ingress and pairing-scoped task selection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

import app.core.db as db_module
from app.models.chat import ChatSession, SessionMessage
from app.models.remote import RemoteConnection, RemotePairing
from app.remote.contracts import (
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemotePrincipal,
)
from app.services.interactive_message_service import InteractiveMessageResult
from sqlmodel import select


async def _paired_text_action(db, text: str = "Plan my next task"):
    connection = RemoteConnection(
        adapter="telegram",
        label="My phone",
        enabled=True,
        adapter_principal_id="bot-1",
        adapter_username="evoflux_bot",
    )
    db.add(connection)
    await db.flush()
    pairing = RemotePairing(
        connection_id=connection.id,
        principal_id="telegram-user-1",
        destination_id="telegram-chat-1",
        label="Alice",
    )
    db.add(pairing)
    await db.commit()
    return (
        pairing,
        RemoteInboundAction(
            connection_id=connection.id,
            kind=RemoteInboundActionKind.TEXT,
            principal=RemotePrincipal(
                connection_id=connection.id,
                principal_id="telegram-user-1",
                destination_id="telegram-chat-1",
            ),
            source_key=f"telegram:{connection.id}:42",
            text=text,
        ),
    )


@pytest.mark.asyncio
async def test_handle_text_result_defaults_to_summary_response_mode(monkeypatch):
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            session = await db.get(ChatSession, UUID(session_id))
            return session, team

        submit = AsyncMock(
            side_effect=lambda db, *, session, **_kwargs: InteractiveMessageResult(
                status="accepted", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        assert result.response_mode == "summary"


@pytest.mark.asyncio
async def test_handle_text_result_carries_a_live_response_mode(monkeypatch):
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        pairing.response_mode = "live"
        db.add(pairing)
        await db.commit()
        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            session = await db.get(ChatSession, UUID(session_id))
            return session, team

        submit = AsyncMock(
            side_effect=lambda db, *, session, **_kwargs: InteractiveMessageResult(
                status="accepted", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        assert result.response_mode == "live"


@pytest.mark.asyncio
async def test_handle_text_creates_and_selects_a_top_level_work_task(monkeypatch):
    """Removing remote provenance or pointer persistence must fail this test."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            session = await db.get(ChatSession, UUID(session_id))
            assert session is not None
            assert require_existing is True
            return session, team

        submit = AsyncMock(
            side_effect=lambda db, *, session, **_kwargs: InteractiveMessageResult(
                status="accepted", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        refreshed_pairing = await db.get(RemotePairing, pairing.id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id == result.session_id
        remote_session = await db.get(ChatSession, result.session_id)
        assert remote_session is not None
        assert remote_session.parent_session_id is None
        assert remote_session.mode == "work"
        assert remote_session.session_type == "main"
        assert remote_session.tags == [
            "remote_origin",
            f"remote_connection:{action.connection_id}",
        ]
        assert result.status == "accepted"
        assert submit.await_args.kwargs["content"] == "Plan my next task"


@pytest.mark.asyncio
async def test_new_task_clears_only_the_pairings_current_pointer():
    """Deleting or interrupting the former task must fail this test."""
    from app.remote.inbound import RemoteInboundService

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        previous = ChatSession(title="Keep this task")
        db.add(previous)
        await db.flush()
        pairing.active_session_id = previous.id
        db.add(pairing)
        await db.commit()

        result = await RemoteInboundService().new_task(db, action)

        refreshed_pairing = await db.get(RemotePairing, pairing.id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id is None
        assert await db.get(ChatSession, previous.id) is not None
        assert result.status == "current_task_cleared"
        assert result.session_id is None


@pytest.mark.asyncio
async def test_continue_task_selects_an_existing_top_level_coding_task():
    """Fail if Continue does not persist its pairing-scoped task selection."""
    from app.remote.inbound import RemoteInboundService

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        coding_task = ChatSession(title="Coding task", mode="coding")
        db.add(coding_task)
        await db.commit()

        result = await RemoteInboundService().continue_task(db, action, coding_task.id)

        refreshed_pairing = await db.get(RemotePairing, pairing.id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id == coding_task.id
        assert result.status == "current_task_selected"
        assert result.session_id == coding_task.id


@pytest.mark.asyncio
async def test_continue_task_refuses_a_side_chat_without_changing_current_task():
    """Fail if a non-addressable session can become remotely selectable."""
    from app.remote.inbound import RemoteInboundService

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        pairing_id = pairing.id
        current = ChatSession(title="Current task")
        side_chat = ChatSession(title="Side chat", session_type="side_chat")
        db.add(current)
        db.add(side_chat)
        await db.flush()
        pairing.active_session_id = current.id
        db.add(pairing)
        await db.commit()

        result = await RemoteInboundService().continue_task(db, action, side_chat.id)

        refreshed_pairing = await db.get(RemotePairing, pairing_id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id == current.id
        assert result.status == "session_not_addressable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate_kwargs",
    [
        {"session_type": "team_member"},
        {"mode": "internal"},
    ],
)
async def test_continue_task_refuses_non_user_visible_sessions(
    candidate_kwargs: dict[str, str],
):
    """Fail if child or internal task records become remotely addressable."""
    from app.remote.inbound import RemoteInboundService

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        current = ChatSession(title="Current task")
        candidate = ChatSession(title="Hidden task", **candidate_kwargs)
        db.add(current)
        db.add(candidate)
        await db.flush()
        current_id = current.id
        pairing.active_session_id = current_id
        db.add(pairing)
        await db.commit()

        result = await RemoteInboundService().continue_task(db, action, candidate.id)

        refreshed_pairing = await db.get(RemotePairing, pairing.id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id == current_id
        assert result.status == "session_not_addressable"


@pytest.mark.asyncio
async def test_stop_current_interrupts_only_the_pairings_live_task(monkeypatch):
    """Fail if Stop does not target the selected live task through its team."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        pairing_id = pairing.id
        current = ChatSession(title="Current task")
        db.add(current)
        await db.flush()
        current_id = current.id
        pairing.active_session_id = current.id
        db.add(pairing)
        await db.commit()

        team = SimpleNamespace(has_active_user_turn=lambda: True)

        async def resolve(db, session_id: str, *, require_existing: bool):
            assert UUID(session_id) == current_id
            assert require_existing is True
            return current, team

        interrupted: list[tuple[object, str | None]] = []

        async def interrupt(target_team, session_id: str | None):
            interrupted.append((target_team, session_id))
            return ["lead"]

        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(
            inbound,
            "agent_service",
            SimpleNamespace(interrupt_team=interrupt),
            raising=False,
        )

        result = await RemoteInboundService().stop_current(db, action)

        assert result.status == "interrupted"
        assert result.session_id == current_id
        assert interrupted == [(team, str(current_id))]
        refreshed_pairing = await db.get(RemotePairing, pairing_id)
        assert refreshed_pairing is not None
        assert refreshed_pairing.active_session_id == current_id


@pytest.mark.asyncio
async def test_stop_current_reports_no_active_turn_when_no_team_is_configured(
    monkeypatch,
):
    """Fail if a missing team makes the adapter retry a stop command forever."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound
    from app.services.agent_service import NoTeamConfigured

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        current = ChatSession(title="Current task")
        db.add(current)
        await db.flush()
        current_id = current.id
        pairing.active_session_id = current.id
        db.add(pairing)
        await db.commit()

        async def resolve(_db, _session_id: str, *, require_existing: bool):
            assert require_existing is True
            raise NoTeamConfigured("No configured team")

        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)

        result = await RemoteInboundService().stop_current(db, action)

        assert result.status == "no_active_turn"
        assert result.session_id == current_id


@pytest.mark.asyncio
async def test_handle_text_replays_a_delivered_update_without_second_dispatch(
    monkeypatch,
):
    """Fail if duplicate provider updates create or deliver another user message."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound
    from app.services import agent_service

    async with db_module.async_session_factory() as db:
        _, action = await _paired_text_action(db, "Deliver this once")
        team = SimpleNamespace(
            user_message_lock=asyncio.Lock(),
            session_tags=frozenset(),
            permission_mode="auto",
            has_active_user_turn=lambda: False,
        )

        async def resolve(db, session_id: str, *, require_existing: bool):
            async with db.begin():
                session = await db.get(ChatSession, UUID(session_id))
            assert session is not None
            assert require_existing is True
            return session, team

        dispatches: list[UUID] = []

        async def dispatch(_team, *, content, session_id, message_extra, **_kwargs):
            session_uuid = UUID(session_id)
            source = dict(message_extra["interactive_source"])
            source["state"] = "delivered"
            db.add(
                SessionMessage(
                    session_id=session_uuid,
                    role="user",
                    content=content,
                    extra={"interactive_source": source},
                )
            )
            await db.commit()
            dispatches.append(session_uuid)
            return session_id, 0

        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(agent_service, "dispatch_user_message", dispatch)

        service = RemoteInboundService()
        first = await service.handle_text(db, action)
        replay = await service.handle_text(db, action)

        assert first.status == "accepted"
        assert replay.status == "accepted"
        assert replay.session_id == first.session_id
        assert dispatches == [first.session_id]


@pytest.mark.asyncio
async def test_handle_text_ignores_an_unpaired_principal_without_creating_a_task():
    """Fail if an unpaired phone can allocate a session or trigger team work."""
    from app.remote.inbound import RemoteInboundService

    connection_id = uuid4()
    action = RemoteInboundAction(
        connection_id=connection_id,
        kind=RemoteInboundActionKind.TEXT,
        principal=RemotePrincipal(
            connection_id=connection_id,
            principal_id="unpaired-user",
            destination_id="unpaired-chat",
        ),
        source_key=f"telegram:{connection_id}:99",
        text="Start something",
    )

    async with db_module.async_session_factory() as db:
        result = await RemoteInboundService().handle_text(db, action)
        sessions = list((await db.exec(select(ChatSession))).all())

    assert result.status == "unauthorized"
    assert sessions == []


@pytest.mark.asyncio
async def test_handle_text_replaces_a_deleted_current_task(monkeypatch):
    """Fail if a stale pairing pointer prevents the next phone message."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db, "Start replacement")
        previous = ChatSession(title="Deleted task")
        db.add(previous)
        await db.flush()
        previous_id = previous.id
        pairing.active_session_id = previous_id
        db.add(pairing)
        await db.commit()
        await db.delete(previous)
        await db.commit()

        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            async with db.begin():
                session = await db.get(ChatSession, UUID(session_id))
            assert session is not None
            assert require_existing is True
            return session, team

        submit = AsyncMock(
            side_effect=lambda _db, *, session, **_kwargs: InteractiveMessageResult(
                status="queued", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        assert result.status == "queued"
        assert result.session_id != previous_id
        replacement = await db.get(ChatSession, result.session_id)
        assert replacement is not None
        assert replacement.mode == "work"


@pytest.mark.asyncio
async def test_stop_current_does_not_claim_success_for_an_idle_task(monkeypatch):
    """Fail if Stop reports interruption when the selected task is already idle."""
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        current = ChatSession(title="Idle task")
        db.add(current)
        await db.flush()
        current_id = current.id
        pairing.active_session_id = current_id
        db.add(pairing)
        await db.commit()

        async def resolve(_db, session_id: str, *, require_existing: bool):
            assert UUID(session_id) == current_id
            assert require_existing is True
            return current, SimpleNamespace(has_active_user_turn=lambda: False)

        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)

        result = await RemoteInboundService().stop_current(db, action)

        assert result.status == "no_active_turn"
        assert result.session_id == current_id
