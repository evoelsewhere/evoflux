"""Tests for the stream observer registry in memory_stream_store."""

from __future__ import annotations

import pytest

from app.services.memory_stream_store import (
    _observers,
    _notify_observers,
    close,
    init_turn,
    push_event,
    register_observer,
)
from app.services.stream_envelope import StreamEnvelope


@pytest.fixture(autouse=True)
def _clean_observers():
    """Ensure no observers leak between tests."""
    _observers.clear()
    yield
    _observers.clear()


def _make_envelope(event: str = "message", **data: object) -> StreamEnvelope:
    return StreamEnvelope.from_parts(event=event, data={"type": event, **data})


# ── register / unregister ────────────────────────────────────────────────


def test_register_returns_unregister_callable() -> None:
    calls: list[tuple[str, StreamEnvelope]] = []

    def observer(session_id: str, envelope: StreamEnvelope) -> None:
        calls.append((session_id, envelope))

    unregister = register_observer(observer)
    assert callable(unregister)
    assert observer in _observers

    unregister()
    assert observer not in _observers


def test_unregister_is_idempotent() -> None:
    def observer(session_id: str, envelope: StreamEnvelope) -> None:
        pass

    unregister = register_observer(observer)
    unregister()
    unregister()  # must not raise
    assert observer not in _observers


# ── invocation ───────────────────────────────────────────────────────────


def test_observer_receives_events() -> None:
    calls: list[tuple[str, str]] = []

    def observer(session_id: str, envelope: StreamEnvelope) -> None:
        calls.append((session_id, envelope.event))

    register_observer(observer)
    env = _make_envelope("message", text="hello")
    _notify_observers("sess-1", env)

    assert calls == [("sess-1", "message")]


def test_multiple_observers_all_invoked() -> None:
    calls_a: list[str] = []
    calls_b: list[str] = []

    register_observer(lambda sid, env: calls_a.append(sid))
    register_observer(lambda sid, env: calls_b.append(sid))

    _notify_observers("sess-1", _make_envelope())

    assert calls_a == ["sess-1"]
    assert calls_b == ["sess-1"]


def test_observer_exception_isolation() -> None:
    good_calls: list[str] = []

    def bad_observer(session_id: str, envelope: StreamEnvelope) -> None:
        raise RuntimeError("boom")

    def good_observer(session_id: str, envelope: StreamEnvelope) -> None:
        good_calls.append(session_id)

    register_observer(bad_observer)
    register_observer(good_observer)

    _notify_observers("sess-1", _make_envelope())

    assert good_calls == ["sess-1"]


def test_observers_cleared_on_close() -> None:
    register_observer(lambda sid, env: None)
    register_observer(lambda sid, env: None)
    assert len(_observers) == 2

    import asyncio

    asyncio.get_event_loop().run_until_complete(close())
    assert len(_observers) == 0


# ── integration with push_event ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_event_invokes_observers() -> None:
    calls: list[tuple[str, str]] = []

    def observer(session_id: str, envelope: StreamEnvelope) -> None:
        calls.append((session_id, envelope.event))

    register_observer(observer)
    await init_turn("sess-1")
    await push_event("sess-1", _make_envelope("message", text="hi"))

    assert len(calls) == 1
    assert calls[0] == ("sess-1", "message")


@pytest.mark.asyncio
async def test_push_event_no_observer_on_unknown_session() -> None:
    calls: list[str] = []

    register_observer(lambda sid, env: calls.append(sid))
    await push_event("nonexistent", _make_envelope())

    assert calls == []
