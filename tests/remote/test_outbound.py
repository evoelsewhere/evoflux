"""Tests for app/remote/outbound.py — remote stream projection and delivery."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

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

    async def send(self, message: RemoteOutboundMessage) -> None:
        self.calls.append("send")
        self.sent.append(message)

    async def edit(self, message: RemoteOutboundMessage) -> None:
        self.calls.append("edit")
        self.edited.append(message)

    async def answer_callback(self, callback_token: str) -> None:
        pass

    async def indicate_typing(self, destination_id: str) -> None:
        pass

    def status(self) -> RemoteAdapterStatus:
        return RemoteAdapterStatus(
            connection_id=uuid4(), state=RemoteConnectionState.POLLING
        )


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
