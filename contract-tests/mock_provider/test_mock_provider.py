"""Mock provider contract: the agent loop against a replayed model."""

from __future__ import annotations

import httpx

from conftest import configure_backend_provider
from sse import Event, collect_events


def send_and_collect(client: httpx.Client, message: str) -> tuple[str, list[Event]]:
    """POST a chat message, then read the session stream until the turn ends."""
    sent = client.post("/api/team/chat", data={"message": message})
    assert sent.status_code == 202, sent.text
    session_id = sent.json()["session_id"]
    events = collect_events(
        client,
        f"/api/team/{session_id}/stream",
        until=lambda e: e.event in ("done", "error"),
        timeout_s=60,
    )
    return session_id, events


def assistant_text(events: list[Event]) -> str:
    return "".join(e.data["text"] for e in events if e.event == "message")


def test_text_turn_replays(client: httpx.Client, mock_provider) -> None:
    mock_provider.load("openai_text_hello")
    configure_backend_provider(client, mock_provider)
    _, events = send_and_collect(client, "say hello")
    assert assistant_text(events) == "Hello from mock."
    assert len(mock_provider.requests) == 1


def test_tool_call_round_trip(client: httpx.Client, mock_provider) -> None:
    mock_provider.load("openai_tool_call_then_text")
    configure_backend_provider(client, mock_provider)
    _, events = send_and_collect(client, "what day is it")
    assert [e.data["name"] for e in events if e.event == "tool_end"] == ["date"]
    assert len(mock_provider.requests) == 2
    second = mock_provider.requests[1]["messages"]
    tool_messages = [m for m in second if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call_mock_1"]
    assert tool_messages[0]["content"]
    assert assistant_text(events) == "The date tool ran."


def test_anthropic_text_turn_replays(client: httpx.Client, mock_provider) -> None:
    mock_provider.load("anthropic_text_hello")
    configure_backend_provider(client, mock_provider, wire="anthropic")
    _, events = send_and_collect(client, "say hello")
    assert assistant_text(events) == "Hello from mock."
    assert len(mock_provider.requests) == 1
    assert mock_provider.requests[0]["stream"] is True


def test_anthropic_reasoning_and_cache_usage(
    client: httpx.Client, mock_provider
) -> None:
    mock_provider.load("anthropic_reasoning_and_cache_usage")
    configure_backend_provider(client, mock_provider, wire="anthropic")
    _, events = send_and_collect(client, "think about it")
    assert [e.data["text"] for e in events if e.event == "thinking"] == [
        "Considering the question."
    ]
    assert assistant_text(events) == "Answer after thinking."
    usage = next(e.data for e in events if e.event == "usage")
    assert usage["prompt_tokens"] == 162  # 12 + 100 cache write + 50 cache read
    assert usage["completion_tokens"] == 9
    assert usage["cached_tokens"] == 50
    assert usage["cache_write_tokens"] == 100


def test_429_surfaces_error_event(client: httpx.Client, mock_provider) -> None:
    """v3 reports a retryable 429 as ``rate_limit`` and ``provider_status``
    events (no ``error`` event), then ends the turn without any assistant text.
    ``retry-after: 1`` keeps the five attempts to about four seconds."""
    mock_provider.load("provider_error_429")
    configure_backend_provider(client, mock_provider)
    _, events = send_and_collect(client, "say hello")

    assert len(mock_provider.requests) == 5
    rate_limits = [e.data for e in events if e.event == "rate_limit"]
    assert [r["attempt"] for r in rate_limits] == [1, 2, 3, 4, 5]
    assert {(r["retry_after"], r["max_attempts"]) for r in rate_limits} == {(1, 5)}
    statuses = [e.data for e in events if e.event == "provider_status"]
    assert [s["status"] for s in statuses] == ["retrying"] * 4 + ["exhausted"]
    assert {s["status_code"] for s in statuses} == {429}
    assert statuses[-1]["model"] == "router9:mock-model"
    assert not [e for e in events if e.event == "message"]
    assert events[-1].event == "done"
