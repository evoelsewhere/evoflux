"""Tests for app/remote/outbound.py — remote stream projection and delivery."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio

import app.core.db as db_module
from app.models.chat import ChatSession, SessionMessage
from app.remote.contracts import (
    RemoteAdapterStatus,
    RemoteConnectionState,
    RemoteOutboundMessage,
    RemoteOutboundPriority,
)
from app.remote.outbound import RemoteProjection, _split_text
from app.services.stream_envelope import StreamEnvelope


def _envelope(event: str, **data: object) -> StreamEnvelope:
    return StreamEnvelope.from_parts(event=event, data={"type": event, **data})


class FakeAdapter:
    """Records send/edit calls for assertion.

    ``calls`` tracks only ``send``/``edit`` — in delivery order — so tests
    can assert "sent first, then edited" without the typing indicator's
    repeating ``indicate_typing`` calls interleaving into that sequence.
    """

    def __init__(self) -> None:
        self.sent: list[RemoteOutboundMessage] = []
        self.edited: list[RemoteOutboundMessage] = []
        self.calls: list[str] = []
        #: Correlation ids whose ``send`` should raise instead of
        #: succeeding, to simulate a status card that never made it.
        self.fail_send_correlations: set[str] = set()
        #: When >0, ``indicate_typing`` raises this many times before
        #: succeeding, to simulate a transient transport error.
        self.typing_failures_remaining = 0
        self.typing_calls = 0

    async def send(self, message: RemoteOutboundMessage) -> None:
        if message.correlation_id in self.fail_send_correlations:
            raise RuntimeError("simulated send failure")
        self.calls.append("send")
        self.sent.append(message)

    async def edit(self, message: RemoteOutboundMessage) -> None:
        self.calls.append("edit")
        self.edited.append(message)

    async def answer_callback(self, callback_token: str) -> None:
        pass

    async def indicate_typing(self, destination_id: str) -> None:
        self.typing_calls += 1
        if self.typing_failures_remaining > 0:
            self.typing_failures_remaining -= 1
            raise RuntimeError("simulated typing failure")

    def status(self) -> RemoteAdapterStatus:
        return RemoteAdapterStatus(
            connection_id=uuid4(), state=RemoteConnectionState.POLLING
        )


class FakeCapabilityRegistrar:
    """Records completion-card capabilities without depending on actions.py."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def register_capability(self, **kwargs: str) -> str:
        self.calls.append(kwargs)
        return f"{kwargs['action_kind']}-token"


@pytest_asyncio.fixture
async def addressable_session() -> ChatSession:
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Desktop task", mode="work", session_type="main")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


@pytest_asyncio.fixture
async def side_chat_session() -> ChatSession:
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Private side chat", session_type="side_chat")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session


# ── session registration ─────────────────────────────────────────────────


def test_register_and_unregister_session() -> None:
    proj = RemoteProjection()
    proj.register_session(
        "sess-1",
        connection_id=str(uuid4()),
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    assert "sess-1" in proj._session_tags

    proj.unregister_session("sess-1")
    assert "sess-1" not in proj._session_tags


# ── observe filtering ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ignores_unregistered_sessions() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    proj.observe("unknown-session", _envelope("done"))
    await proj.drain_pending()
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_ignores_non_remote_sessions() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    proj.register_session(
        "sess-1",
        connection_id=str(uuid4()),
        destination_id="12345",
        tags=frozenset({"other_tag"}),
    )
    proj.observe("sess-1", _envelope("done"))
    await proj.drain_pending()
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_ignores_non_observed_event_types() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("message", text="streaming text"))
    proj.observe("sess-1", _envelope("thinking", text="reasoning"))
    proj.observe("sess-1", _envelope("tool_call", name="search"))
    await proj.drain_pending()

    assert adapter.sent == []


# ── done event ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_done_sends_completion_message() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("done", text="Here is the result."))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert adapter.sent[0].destination_id == "12345"
    assert adapter.sent[0].priority == RemoteOutboundPriority.HIGH


@pytest.mark.asyncio
async def test_done_includes_the_agents_actual_reply_text(
    addressable_session: ChatSession,
) -> None:
    """A "done" ``StreamEnvelope`` never carries reply text (``DoneEvent``
    has no such field) — the done card's answer must come from the turn's
    own persisted assistant message instead, or a tool-call-free
    conversational turn would render as an empty "0 tool calls" card with
    no answer in it at all (the actual regression this guards against)."""
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    connection_id = str(uuid4())
    proj.register_session(
        str(addressable_session.id),
        connection_id=connection_id,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    # Establishes the turn's ``turn_started_wall_clock`` — the message
    # below must be persisted after this so load_turn_activity's ``since``
    # filter doesn't exclude it (matches how a real turn actually starts
    # via begin_phone_turn before any reply gets persisted).
    proj.begin_phone_turn(
        str(addressable_session.id),
        connection_id=connection_id,
        destination_id="12345",
        principal_id="user-1",
        title="Task",
        status="accepted",
    )
    async with db_module.async_session_factory() as db:
        db.add(
            SessionMessage(
                session_id=addressable_session.id,
                role="assistant",
                content="Here is the result.",
            )
        )
        await db.commit()

    proj.observe(str(addressable_session.id), _envelope("done"))
    await proj.drain_pending()

    # begin_phone_turn already sent the status card; the done event edits
    # that same message in place rather than sending a new one.
    assert len(adapter.edited) == 1
    assert "Here is the result." in adapter.edited[0].text
    # No tool calls happened — a "Tool log" button would only ever open an
    # empty "No tool calls." page, so it must not be offered at all.
    assert adapter.edited[0].buttons == ()


@pytest.mark.asyncio
async def test_done_registers_current_turn_detail_capabilities(
    addressable_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    capabilities = FakeCapabilityRegistrar()
    projection.set_adapter(adapter)
    projection.set_actions(capabilities)
    connection_id = str(uuid4())
    destination_id = "12345"
    projection.register_session(
        str(addressable_session.id),
        connection_id=connection_id,
        destination_id=destination_id,
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        str(addressable_session.id),
        connection_id=connection_id,
        destination_id=destination_id,
        principal_id="user-1",
        title="Task",
        status="Working",
    )
    async with db_module.async_session_factory() as db:
        db.add(
            SessionMessage(
                session_id=addressable_session.id,
                role="assistant",
                tool_calls=[
                    {"name": "write", "arguments": {"path": "new.py"}},
                    {"name": "shell", "arguments": {"command": "pytest"}},
                ],
            )
        )
        await db.commit()

    projection.observe(str(addressable_session.id), _envelope("done"))
    await projection.drain_pending()

    assert [call["action_kind"] for call in capabilities.calls] == [
        "diff",
        "toollog",
    ]
    assert all(
        call["session_id"] == str(addressable_session.id) for call in capabilities.calls
    )
    assert all(call["principal_id"] == "user-1" for call in capabilities.calls)
    assert all(call["destination_id"] == destination_id for call in capabilities.calls)
    assert [button.token for button in adapter.edited[0].buttons[-2:]] == [
        "diff-token",
        "toollog-token",
    ]


@pytest.mark.asyncio
async def test_done_collapses_duplicates() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("done", text="First"))
    proj.observe("sess-1", _envelope("done", text="Second"))
    await proj.drain_pending()

    assert len(adapter.sent) == 1


# ── error event ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_sends_error_message() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("error", message="Something went wrong"))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert "Something went wrong" in adapter.sent[0].text


# ── cross-origin completion delivery ─────────────────────────────────────


@pytest.mark.asyncio
async def test_unregistered_addressable_session_notifies_when_scope_is_all(
    addressable_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    connection_id = str(uuid4())
    projection.set_active_pairing(
        connection_id=connection_id,
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )

    projection.observe(str(addressable_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls == ["send"]
    assert adapter.sent[0].destination_id == "chat-1"
    assert str(adapter.sent[0].connection_id) == connection_id
    assert projection.typing_task_for(str(addressable_session.id)) is None


@pytest.mark.asyncio
async def test_unregistered_session_is_silent_when_scope_is_remote_only(
    addressable_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    projection.set_active_pairing(
        connection_id=str(uuid4()),
        destination_id="chat-1",
        notify_scope="remote_only",
        principal_id="user-1",
    )

    projection.observe(str(addressable_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls == []
    assert projection.typing_task_for(str(addressable_session.id)) is None


@pytest.mark.asyncio
async def test_non_addressable_session_never_notifies_even_with_scope_all(
    side_chat_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    projection.set_active_pairing(
        connection_id=str(uuid4()),
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )

    projection.observe(str(side_chat_session.id), _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls == []
    assert projection.typing_task_for(str(side_chat_session.id)) is None


@pytest.mark.asyncio
async def test_unregistered_addressable_error_sends_one_error_card(
    addressable_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    projection.set_active_pairing(
        connection_id=str(uuid4()),
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )

    projection.observe(
        str(addressable_session.id), _envelope("error", message="Workflow failed")
    )
    await projection.drain_pending()

    assert adapter.calls == ["send"]
    assert "Workflow failed" in adapter.sent[0].text


@pytest.mark.asyncio
async def test_duplicate_unregistered_completions_send_one_card(
    addressable_session: ChatSession,
) -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)
    projection.set_active_pairing(
        connection_id=str(uuid4()),
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )

    projection.observe(str(addressable_session.id), _envelope("done", text="First"))
    projection.observe(str(addressable_session.id), _envelope("done", text="Second"))
    await projection.drain_pending()

    assert adapter.calls == ["send"]


# ── phone-admitted status lifecycle ─────────────────────────────────────


@pytest.mark.asyncio
async def test_begin_phone_turn_sends_status_card_then_done_edits_it() -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    await asyncio.sleep(0.05)
    assert adapter.calls[0] == "send"
    first_correlation = adapter.sent[0].correlation_id

    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls[1] == "edit"
    assert adapter.edited[0].correlation_id == first_correlation
    assert "Fix tests" in adapter.edited[0].text
    assert projection.typing_task_for("sess-1") is None


@pytest.mark.asyncio
async def test_immediate_done_edits_queued_phone_status_card() -> None:
    """A completion that races the initial delivery must not create a
    second card: the queued status card is delivered first, then edited."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    projection.observe("sess-1", _envelope("done", text="Done."))

    await projection.drain_pending()

    assert adapter.calls == ["send", "edit"]
    assert len(adapter.sent) == 1
    assert len(adapter.edited) == 1
    assert adapter.edited[0].correlation_id == adapter.sent[0].correlation_id


@pytest.mark.asyncio
async def test_begin_phone_turn_error_edits_status_with_error_card() -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    await asyncio.sleep(0.05)
    first_correlation = adapter.sent[0].correlation_id

    projection.observe("sess-1", _envelope("error", message="Boom"))
    await projection.drain_pending()

    assert adapter.calls[1] == "edit"
    assert adapter.edited[0].correlation_id == first_correlation
    assert "Boom" in adapter.edited[0].text
    assert projection.typing_task_for("sess-1") is None


@pytest.mark.asyncio
async def test_begin_phone_turn_without_adapter_does_not_raise() -> None:
    projection = RemoteProjection()
    projection.set_adapter(None)

    projection.register_session(
        "sess-1",
        connection_id="conn-1",
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id="conn-1",
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    assert projection.typing_task_for("sess-1") is None

    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()


@pytest.mark.asyncio
async def test_begin_phone_turn_again_before_resolution_reuses_status_card() -> None:
    """A follow-up message while the first turn is still running (the
    inbound service returns status="queued" and runtime.py calls
    begin_phone_turn again) must not orphan the first turn's typing task or
    abandon its status card — it should edit the same message."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    await asyncio.sleep(0.05)
    assert adapter.calls == ["send"]
    first_correlation = adapter.sent[0].correlation_id
    first_typing_task = projection.typing_task_for("sess-1")
    assert first_typing_task is not None

    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="queued",
    )
    await asyncio.sleep(0.05)

    # The original typing task is stopped and replaced by a new one — not
    # left running alongside it.
    assert first_typing_task.cancelled() or first_typing_task.done()
    second_typing_task = projection.typing_task_for("sess-1")
    assert second_typing_task is not None
    assert second_typing_task is not first_typing_task

    # No second status message was sent — the existing one was edited.
    assert adapter.calls == ["send", "edit"]
    assert adapter.edited[0].correlation_id == first_correlation
    assert "queued" in adapter.edited[0].text

    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()

    # The final done card also edits that same single message.
    assert adapter.calls == ["send", "edit", "edit"]
    assert adapter.edited[1].correlation_id == first_correlation
    assert projection.typing_task_for("sess-1") is None


@pytest.mark.asyncio
async def test_queued_follow_up_replaces_unsent_status_card() -> None:
    """A follow-up admitted before delivery updates the pending status card
    instead of emitting an orphaned first status message."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="queued",
    )

    await projection.drain_pending()

    assert adapter.calls == ["send"]
    assert "queued" in adapter.sent[0].text


@pytest.mark.asyncio
async def test_begin_phone_turn_reuse_falls_back_to_send_if_original_never_sent() -> (
    None
):
    """If the first status card's send never actually succeeded (e.g. a
    transient transport failure), there is nothing for a follow-up edit to
    land on — must send a fresh message instead of silently no-op'ing."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    # Make the very first send fail so it never lands in _sent_correlations.
    adapter.fail_send_correlations.add(
        projection._turns["sess-1"].lifecycle_correlation_id
    )
    await asyncio.sleep(0.05)
    assert adapter.calls == []
    assert adapter.sent == []

    adapter.fail_send_correlations.clear()
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="queued",
    )
    await asyncio.sleep(0.05)

    # A fresh send, not an edit — nothing existed yet to edit.
    assert adapter.calls == ["send"]

    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()
    assert projection.typing_task_for("sess-1") is None


@pytest.mark.asyncio
async def test_finalize_falls_back_to_send_when_status_card_was_never_sent() -> None:
    """Same fallback, exercised at the done/error edge instead of a
    follow-up admission: if the status card's send never succeeded, the
    final card must still reach the user as a new message."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    adapter.fail_send_correlations.add(
        projection._turns["sess-1"].lifecycle_correlation_id
    )
    await asyncio.sleep(0.05)
    assert adapter.sent == []

    adapter.fail_send_correlations.clear()
    projection.observe("sess-1", _envelope("done", text="Done."))
    await projection.drain_pending()

    assert adapter.calls == ["send"]
    assert len(adapter.sent) == 1
    assert "Fix tests" in adapter.sent[0].text


@pytest.mark.asyncio
async def test_set_adapter_none_stops_all_live_typing_tasks() -> None:
    """Unbinding the adapter (runtime shutdown) must stop every in-flight
    typing loop rather than leaving it calling a stale adapter reference
    forever, since the done/error event that would normally stop it will
    now never arrive."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    await asyncio.sleep(0.05)
    typing_task = projection.typing_task_for("sess-1")
    assert typing_task is not None

    projection.set_adapter(None)
    await asyncio.sleep(0)

    assert projection.typing_task_for("sess-1") is None
    assert typing_task.cancelled() or typing_task.done()


@pytest.mark.asyncio
async def test_typing_loop_survives_indicate_typing_error() -> None:
    """A transient transport error from indicate_typing must not kill the
    typing loop for the rest of the turn — it should log and keep going on
    the next tick."""
    projection = RemoteProjection()
    adapter = FakeAdapter()
    adapter.typing_failures_remaining = 1
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    await asyncio.sleep(0.05)

    # The loop's first indicate_typing call raised and was swallowed; the
    # task must still be alive (not crashed) to try again on its next tick.
    assert adapter.typing_calls == 1
    typing_task = projection.typing_task_for("sess-1")
    assert typing_task is not None
    assert not typing_task.done()

    projection.set_adapter(None)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_unregister_session_stops_typing_task() -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    typing_task = projection.typing_task_for("sess-1")
    assert typing_task is not None

    projection.unregister_session("sess-1")

    assert typing_task.cancelled() or typing_task.cancelling() > 0


@pytest.mark.asyncio
async def test_clear_turn_stops_typing_task() -> None:
    projection = RemoteProjection()
    adapter = FakeAdapter()
    projection.set_adapter(adapter)

    cid = str(uuid4())
    projection.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        tags=frozenset({"remote_origin"}),
    )
    projection.begin_phone_turn(
        "sess-1",
        connection_id=cid,
        destination_id="chat-1",
        principal_id="user-1",
        title="Fix tests",
        status="accepted",
    )
    typing_task = projection.typing_task_for("sess-1")
    assert typing_task is not None

    projection.clear_turn("sess-1")

    assert typing_task.cancelled() or typing_task.cancelling() > 0


@pytest.mark.asyncio
async def test_done_for_registered_but_never_begun_turn_uses_task_fallback_title() -> (
    None
):
    """A session that's register_session-ed but never begin_phone_turn-ed
    (e.g. desktop-started work the phone is only observing) has no real
    title to draw on — the card must fall back to "Task" instead of
    rendering blank."""
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("done", text="Here is the result."))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert "Task" in adapter.sent[0].text


# ── gate events ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permission_asked_sends_buttons() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("permission_asked", tool="shell"))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert len(adapter.sent[0].buttons) == 2
    assert adapter.sent[0].buttons[0].text == "Allow"
    assert adapter.sent[0].buttons[1].text == "Reject"


@pytest.mark.asyncio
async def test_question_asked_sends_text() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("question_asked", question="Which file?"))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert "Which file?" in adapter.sent[0].text


@pytest.mark.asyncio
async def test_plan_approval_sends_buttons() -> None:
    proj = RemoteProjection()
    adapter = FakeAdapter()
    proj.set_adapter(adapter)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("plan_approval_requested"))
    await proj.drain_pending()

    assert len(adapter.sent) == 1
    assert len(adapter.sent[0].buttons) == 2
    assert adapter.sent[0].buttons[0].text == "Approve"


# ── no adapter ───────────────────────────────────────────────────────────


def test_set_active_pairing_then_clear() -> None:
    proj = RemoteProjection()
    assert proj.active_pairing() is None

    proj.set_active_pairing(
        connection_id="conn-1",
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )
    assert proj.active_pairing() == ("conn-1", "chat-1", "all", "user-1")

    proj.clear_active_pairing()
    assert proj.active_pairing() is None


def test_set_active_pairing_overwrites_previous_value() -> None:
    proj = RemoteProjection()
    proj.set_active_pairing(
        connection_id="conn-1",
        destination_id="chat-1",
        notify_scope="all",
        principal_id="user-1",
    )

    proj.set_active_pairing(
        connection_id="conn-2",
        destination_id="chat-2",
        notify_scope="phone_initiated",
        principal_id="user-2",
    )

    assert proj.active_pairing() == ("conn-2", "chat-2", "phone_initiated", "user-2")


def test_no_adapter_does_not_raise() -> None:
    proj = RemoteProjection()
    proj.set_adapter(None)

    cid = str(uuid4())
    proj.register_session(
        "sess-1",
        connection_id=cid,
        destination_id="12345",
        tags=frozenset({"remote_origin"}),
    )
    proj.observe("sess-1", _envelope("done", text="done"))


# ── text splitting ───────────────────────────────────────────────────────


def test_split_text_short_text_unchanged() -> None:
    assert _split_text("hello") == ["hello"]


def test_split_text_splits_at_paragraph_boundary() -> None:
    text = "A" * 3000 + "\n\n" + "B" * 3000
    chunks = _split_text(text)
    assert len(chunks) == 2
    assert chunks[0].rstrip("A") == "" or "\n\n" in chunks[0]
    assert chunks[1].startswith("B")


def test_split_text_hard_split_when_no_breaks() -> None:
    text = "x" * 5000
    chunks = _split_text(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4096
    assert len(chunks[1]) == 904


def test_split_text_preserves_unicode() -> None:
    text = "\U0001f600" * 5000
    chunks = _split_text(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == 4096
    assert len(chunks[1]) == 904
    for chunk in chunks:
        chunk.encode("utf-8")
