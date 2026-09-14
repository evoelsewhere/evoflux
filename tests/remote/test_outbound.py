"""Tests for app/remote/outbound.py — remote stream projection and delivery."""

from __future__ import annotations

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
    """Records send calls for assertion."""

    def __init__(self) -> None:
        self.sent: list[RemoteOutboundMessage] = []

    async def send(self, message: RemoteOutboundMessage) -> None:
        self.sent.append(message)

    async def edit(self, message: RemoteOutboundMessage) -> None:
        pass

    async def answer_callback(self, callback_token: str) -> None:
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
