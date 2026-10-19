from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.agent.tools.builtin.suggest_next_message as tools
from app.agent.schemas.events import NextMessageSuggestionEvent
from app.services import memory_stream_store as stream_store
from app.services.stream_envelope import StreamEnvelope


def _state(session_id: str | None = "session-1") -> SimpleNamespace:
    metadata = {} if session_id is None else {"stream_session_id": session_id}
    return SimpleNamespace(metadata=metadata)


class _PushCapture:
    """Stand-in for ``memory_stream_store.push_event``."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, StreamEnvelope]] = []

    async def __call__(self, session_id: str, envelope: StreamEnvelope) -> None:
        self.pushed.append((session_id, envelope))


@pytest.fixture()
def capture(monkeypatch: pytest.MonkeyPatch) -> _PushCapture:
    cap = _PushCapture()
    monkeypatch.setattr(stream_store, "push_event", cap)
    return cap


@pytest.mark.asyncio
async def test_publishes_event_with_exact_fields(capture: _PushCapture):
    result = await tools.suggest_next_message.arun(
        _injected={"_state": _state()},
        message="Write tests for the change",
        reason="The change has no coverage yet",
    )

    assert "[Error]" not in result
    assert "published" in result
    assert len(capture.pushed) == 1
    session_id, envelope = capture.pushed[0]
    assert session_id == "session-1"
    assert envelope.event == "next_message_suggestion"
    assert envelope.data["type"] == "next_message_suggestion"
    assert envelope.data["session_id"] == "session-1"
    assert envelope.data["message"] == "Write tests for the change"
    assert envelope.data["reason"] == "The change has no coverage yet"
    assert envelope.data["metadata"] == {}
    assert set(envelope.data) == {
        "type",
        "session_id",
        "message",
        "reason",
        "metadata",
    }


def test_event_wire_contract_is_fixed():
    payload = NextMessageSuggestionEvent(
        session_id="session-1", message="Write tests for the change"
    ).model_dump(mode="json")
    assert payload == {
        "type": "next_message_suggestion",
        "session_id": "session-1",
        "message": "Write tests for the change",
        "reason": "",
        "metadata": {},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["", "   ", "\t\n"])
async def test_empty_message_rejected(capture: _PushCapture, message: str):
    result = await tools.suggest_next_message.arun(
        _injected={"_state": _state()}, message=message
    )

    assert "[Error]" in result
    assert not capture.pushed


@pytest.mark.asyncio
async def test_session_id_injected_from_state(capture: _PushCapture):
    result = await tools.suggest_next_message.arun(
        _injected={"_state": _state("abc-123")}, message="Run the linter"
    )

    assert "[Error]" not in result
    assert len(capture.pushed) == 1
    session_id, envelope = capture.pushed[0]
    assert session_id == "abc-123"
    assert envelope.data["session_id"] == "abc-123"


@pytest.mark.asyncio
async def test_missing_session_is_rejected(capture: _PushCapture):
    result = await tools.suggest_next_message.arun(
        _injected={"_state": _state(None)}, message="Run the linter"
    )

    assert "[Error]" in result
    assert not capture.pushed


def test_tool_metadata():
    tool = tools.suggest_next_message
    assert tool.name == "suggest_next_message"
    assert tool.tiers is not None
    assert set(tool.tiers) == {"coding"}
    assert tool.lead_only is True
    assert tool.description


def test_registered_in_default_tool_registry():
    from app.agent.loader import _default_tool_registry

    registry = _default_tool_registry()
    assert registry["suggest_next_message"] is tools.suggest_next_message


def test_event_is_non_replayable():
    assert "next_message_suggestion" in stream_store._NON_REPLAYABLE_EVENT_TYPES


def test_suggest_next_message_is_allowed_without_prompting() -> None:
    from app.agent.permission import _DEFAULT_BASE_RULESET, evaluate

    rule = evaluate("suggest_next_message", "*", _DEFAULT_BASE_RULESET)
    assert rule.action == "allow"
