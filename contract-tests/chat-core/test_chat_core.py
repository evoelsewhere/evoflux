"""chat-core contract: POST /api/team/chat, the session SSE stream and history.

Each turn runs against the mock provider (``chatcore_*`` recordings start with a
400 ms delay so the stream attaches before the first chunk). SSE is compared as
a normalized event sequence against snapshots recorded from Python.

Python generates the session title concurrently with the turn (a hook, not in
chat-core), so where it lands in the stream is not deterministic even between
two Python runs. ``canon_events`` projects it out: ``title_update`` events go,
the ``title`` phase is removed from turn totals, and a turn total that only
repeats the previous one once the title phase is gone is dropped. The
``ingress`` status is pushed before the 202 and cleared from the replay journal
when the turn starts, so whether a client sees it depends on when it attaches;
it is dropped too. The checkpoint snapshot id on a later user message is a
checkpoint feature, also outside chat-core.
"""

from __future__ import annotations

import copy
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from backends import start_backend
from normalize import normalize
from provider_setup import configure_backend_provider
from sse import Event, collect_events

_TOTAL_KEYS = (
    "input",
    "output",
    "cache",
    "cache_write",
    "calls",
    "thoughts",
    "tool_use",
)


def _strip_title_phase(usage: dict[str, Any]) -> dict[str, Any] | None:
    """A turn-usage snapshot without its ``title`` phase; None when empty."""
    usage = copy.deepcopy(usage)
    title = usage.get("phases", {}).pop("title", None)
    if title is None:
        return usage
    if not usage["phases"]:
        return None
    for key in _TOTAL_KEYS:
        if key in title and key in usage:
            usage[key] -= title[key]
            if key in ("thoughts", "tool_use") and not usage[key]:
                del usage[key]
    models = sorted({m for p in usage["phases"].values() for m in p.get("models", [])})
    if models:
        usage["models"] = models
    else:
        usage.pop("models", None)
    return usage


def canon_events(events: list[Event]) -> list[list[Any]]:
    out: list[list[Any]] = []
    last_total: Any = None
    for event in events:
        data = copy.deepcopy(event.data)
        if event.event == "title_update":
            continue
        if event.event == "agent_status" and data.get("metadata") == {
            "phase": "ingress"
        }:
            continue
        if event.event == "usage" and data.get("metadata", {}).get("turn_total"):
            meta = data["metadata"]
            snapshot = {
                "input": data["prompt_tokens"],
                "output": data["completion_tokens"],
                "cache": data["cached_tokens"],
                "cache_write": data["cache_write_tokens"],
                "calls": meta["calls"],
                "phases": meta["phases"],
                "models": meta["models"],
            }
            stripped = _strip_title_phase(snapshot)
            if stripped is None or stripped == last_total:
                continue
            last_total = stripped
            data["prompt_tokens"] = stripped["input"]
            data["completion_tokens"] = stripped["output"]
            data["total_tokens"] = stripped["input"] + stripped["output"]
            meta["calls"] = stripped["calls"]
            meta["phases"] = stripped["phases"]
            meta["models"] = stripped.get("models")
        if event.event == "desktop_notification":
            data["body"] = "<title>"
            data["metadata"]["title"] = "<title>"
        if event.event == "tool_end":
            data["metadata"]["duration_ms"] = "<ms>"
            if data["name"] == "date":
                data["result"] = "<date>"
        out.append([event.event, data])
    return normalize(out)


def canon_history(body: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(body)
    lead = body["lead"]
    lead["title"] = "<title>"
    messages = lead["messages"]
    for index, message in enumerate(messages):
        extra = message.get("extra") or {}
        extra.pop("snapshot", None)
        if "duration_ms" in extra:
            extra["duration_ms"] = "<ms>"
        ends_turn = index + 1 == len(messages) or messages[index + 1]["role"] == "user"
        if not ends_turn:
            # A title that finishes late stamps its total on the newest
            # assistant row, which may be an earlier one of the turn.
            extra.pop("turn_usage", None)
        if "turn_usage" in extra:
            stripped = _strip_title_phase(extra["turn_usage"])
            if stripped is None:
                del extra["turn_usage"]
            else:
                extra["turn_usage"] = stripped
        if message["role"] == "tool" and message.get("name") == "date":
            message["content"] = "<date>"
    return normalize(body)


def send(client: httpx.Client, data: dict[str, str]) -> httpx.Response:
    return client.post("/api/team/chat", data=data)


def turn(
    client: httpx.Client, message: str, session_id: str | None = None
) -> tuple[str, list[Event]]:
    data = {"message": message}
    if session_id:
        data["session_id"] = session_id
    sent = send(client, data)
    assert sent.status_code == 202, sent.text
    body = sent.json()
    assert body["status"] == "accepted"
    sid = body["session_id"]
    events = collect_events(
        client,
        f"/api/team/{sid}/stream",
        until=lambda e: e.event == "done",
        timeout_s=60,
    )
    return sid, events


def history(client: httpx.Client, sid: str) -> dict[str, Any]:
    # The stream ends when ``done`` is pushed; give the last write a moment.
    for _ in range(50):
        response = client.get(f"/api/team/{sid}/history")
        assert response.status_code == 200, response.text
        body = response.json()
        if not body["lead"]["running"]:
            return body
        time.sleep(0.1)
    return body


@pytest.fixture
def chat(client: httpx.Client, mock_provider):
    def load(recording: str) -> httpx.Client:
        mock_provider.load(recording)
        configure_backend_provider(client, mock_provider)
        return client

    return load


def test_text_turn(chat, mock_provider, snapshot) -> None:
    client = chat("chatcore_text")
    sid, events = turn(client, "say hello")
    snapshot.check("text_turn_events.json", canon_events(events))
    snapshot.check("text_turn_history.json", canon_history(history(client, sid)))
    assert len(mock_provider.requests) == 1
    request = mock_provider.requests[0]
    assert request["messages"][-1] == {"role": "user", "content": "say hello"}
    assert request["stream"] is True


def test_second_turn_sends_history(chat, mock_provider, snapshot) -> None:
    client = chat("chatcore_text")
    sid, _ = turn(client, "say hello")
    history(client, sid)
    _, events = turn(client, "again", sid)
    snapshot.check("second_turn_events.json", canon_events(events))
    snapshot.check("second_turn_history.json", canon_history(history(client, sid)))
    sent = mock_provider.requests[1]["messages"]
    assert [m for m in sent if m["role"] != "system"] == [
        {"role": "user", "content": "say hello"},
        {"role": "assistant", "content": "Hello from mock."},
        {"role": "user", "content": "again"},
    ]


def test_reasoning_turn(chat, snapshot) -> None:
    client = chat("chatcore_reasoning")
    sid, events = turn(client, "think about it")
    snapshot.check("reasoning_turn_events.json", canon_events(events))
    snapshot.check("reasoning_turn_history.json", canon_history(history(client, sid)))


def test_tool_turn(chat, mock_provider, snapshot) -> None:
    client = chat("chatcore_tool")
    sid, events = turn(client, "what day is it")
    snapshot.check("tool_turn_events.json", canon_events(events))
    snapshot.check("tool_turn_history.json", canon_history(history(client, sid)))
    assert len(mock_provider.requests) == 2
    first_tools = {t["function"]["name"] for t in mock_provider.requests[0]["tools"]}
    assert {"read", "ls", "glob", "grep", "date"} <= first_tools
    sent = mock_provider.requests[1]["messages"]
    assert [m for m in sent if m["role"] != "system"][1:] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {"name": "date", "arguments": "{}"},
                }
            ],
        },
        {
            "role": "tool",
            "content": sent[-1]["content"],
            "tool_call_id": "call_mock_1",
            "name": "date",
        },
    ]
    assert sent[-1]["content"]


def test_unknown_tool_gets_python_not_found_result(
    chat, mock_provider, snapshot
) -> None:
    client = chat("chatcore_unknown_tool")
    sid, events = turn(client, "call a tool")
    snapshot.check("unknown_tool_events.json", canon_events(events))
    snapshot.check("unknown_tool_history.json", canon_history(history(client, sid)))
    assert mock_provider.requests[1]["messages"][-1]["content"] == (
        "Error: Tool 'no_such_tool' not found."
    )


def test_unported_tool_ends_the_turn(chat, target) -> None:
    """``get_goal`` is a Python tool Rust has not ported (KNOWN_DIFFERENCES):
    Rust ends the turn with Python's lead-failure error event; Python runs it."""
    client = chat("chatcore_unported_tool")
    sid, events = turn(client, "check the goal")
    names = [name for name, _ in canon_events(events)]
    assert names[:2] == ["agent_status"] * 2
    assert ("tool_call", "get_goal") in [(e.event, e.data.get("name")) for e in events]
    if target == "python":
        assert "error" not in names
        return
    tail = canon_events(events)[-6:]
    assert [name for name, _ in tail] == [
        "tool_end",
        "error",
        "agent_status",
        "desktop_notification",
        "turn_changes",
        "done",
    ]
    assert tail[0][1]["result"] == "Error: Tool 'get_goal' not found."
    assert tail[1][1] == {
        "type": "error",
        "message": "Lead agent 'evoflux' failed: Tool 'get_goal' not found.",
        "metadata": {"agent": "evoflux", "exception": "ToolNotFoundError"},
    }
    assert tail[2][1]["status"] == "error"
    messages = history(client, sid)["lead"]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    assert messages[2]["content"] == "Error: Tool 'get_goal' not found."


def test_restricted_workspace_is_refused(client, target) -> None:
    """Rust-only difference (KNOWN_DIFFERENCES): Python takes any absolute
    ``workspace``, so ``~`` gives the model the whole home folder. Rust refuses
    the home folder, filesystem roots, credential folders and system folders."""
    if target == "python":
        pytest.skip("Python accepts any absolute workspace")
    for workspace in (
        "~",
        "~/",
        "~/.ssh",
        "~/.ssh/new",
        os.path.abspath(os.sep),
        "~/projects/../.aws",
        "~/.azure",
        "~/Library",
        *(
            (
                "~\\.ssh.",
                "~\\.ssh ",
                "~\\.kube::$INDEX_ALLOCATION",
                "\\\\localhost\\C$\\Users",
                "\\\\127.0.0.1\\C$\\Users",
                "\\\\?\\UNC\\localhost\\C$\\Users",
            )
            if os.name == "nt"
            else ()
        ),
    ):
        sent = send(client, {"message": "hi", "workspace": workspace})
        assert sent.status_code == 422, (workspace, sent.text)
        assert sent.json()["detail"].startswith("Workspace path is not allowed"), (
            workspace
        )
    sent = send(client, {"message": "hi", "workspace": "~/projects/x"})
    assert sent.status_code == 202, sent.text


def test_provider_error_400(chat, mock_provider, snapshot) -> None:
    client = chat("chatcore_error_400")
    sid, events = turn(client, "say hello")
    snapshot.check("error_400_events.json", canon_events(events))
    snapshot.check("error_400_history.json", canon_history(history(client, sid)))
    assert len(mock_provider.requests) == 1


def test_provider_error_401(chat, snapshot) -> None:
    client = chat("chatcore_error_401")
    sid, events = turn(client, "say hello")
    snapshot.check("error_401_events.json", canon_events(events))
    snapshot.check("error_401_history.json", canon_history(history(client, sid)))


def test_client_supplied_session_id_and_raw_sse(chat) -> None:
    client = chat("chatcore_text")
    sid = str(uuid.uuid4())
    sent = send(client, {"message": "say hello", "session_id": sid})
    assert sent.status_code == 202
    assert sent.json() == {"status": "accepted", "session_id": sid}
    with client.stream("GET", f"/api/team/{sid}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
        raw = ""
        for chunk in response.iter_text():
            raw += chunk
            if "event: done" in raw:
                break
    assert (
        "event: agent_status\r\ndata: "
        '{"type": "agent_status", "agent": "evoflux", "status": "working", '
        '"metadata": {}}\r\n\r\n'
    ) in raw
    assert (
        "event: message\r\ndata: "
        '{"type": "message", "agent": "evoflux", "text": "Hello ", '
        '"metadata": {"model": "mock-model"}}\r\n\r\n'
    ) in raw


def test_stream_without_a_turn_is_empty(client: httpx.Client) -> None:
    response = client.get(f"/api/team/{uuid.uuid4()}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.text == ""


def test_history_errors(client: httpx.Client, snapshot) -> None:
    results = {
        "missing": client.get(f"/api/team/{uuid.uuid4()}/history"),
        "bad_uuid": client.get("/api/team/not-a-uuid/history"),
    }
    snapshot.check(
        "history_errors.json",
        normalize({k: [r.status_code, r.json()] for k, r in results.items()}),
    )


def test_history_cursor(chat, snapshot) -> None:
    client = chat("chatcore_text")
    sid, _ = turn(client, "say hello")
    body = history(client, sid)
    oldest = body["lead"]["messages"][0]["created_at"]
    before = client.get(f"/api/team/{sid}/history", params={"before": oldest})
    bad = client.get(f"/api/team/{sid}/history", params={"before": "yesterday"})
    snapshot.check(
        "history_cursor.json",
        normalize(
            {
                "before": [before.status_code, canon_history(before.json())],
                "bad": [bad.status_code, bad.json()],
            }
        ),
    )


def test_chat_validation(client: httpx.Client, snapshot) -> None:
    cases = {
        "missing_message": {},
        "blank_message": {"message": "   "},
        "interrupt_and_message": {"message": "x", "interrupt": "true"},
        "interrupt_without_session": {"interrupt": "true"},
        "bad_mode": {"message": "x", "mode": "other"},
        "bad_delivery": {"message": "x", "delivery": "later"},
        "model_without_provider": {"message": "x", "model": "gpt"},
        "bad_session_id": {"message": "x", "session_id": "nope"},
        "loop_removed": {"message": "/loop every 5m"},
        "bad_permission_mode": {"message": "x", "permission_mode": "yolo"},
        "bad_folder_id": {"message": "x", "folder_id": "nope"},
        "bad_workspace": {"message": "x", "workspace": "relative/dir"},
    }
    results = {name: send(client, data) for name, data in cases.items()}
    snapshot.check(
        "chat_validation.json",
        {name: [r.status_code, r.json()] for name, r in results.items()},
    )


def test_python_reads_history_written_by_this_target(
    chat, mock_provider, backend, tmp_path: Path
) -> None:
    """The rows this target wrote load in Python: history, the sessions list,
    and a next turn that sends them back to the model."""
    client = chat("chatcore_tool")
    sid, _ = turn(client, "what day is it")
    written = canon_history(history(client, sid))
    backend.stop()

    python = start_backend("python", tmp_path)
    try:
        with httpx.Client(
            base_url=python.base_url,
            headers={"Authorization": f"Bearer {python.token}"},
            timeout=30.0,
        ) as py:
            read = py.get(f"/api/team/{sid}/history")
            assert read.status_code == 200, read.text
            assert canon_history(read.json()) == written
            sessions = py.get("/api/team/sessions").json()
            listed = [s for s in sessions["data"] if s["id"] == sid]
            assert len(listed) == 1
            assert listed[0]["agent_name"] == "evoflux"
            assert listed[0]["mode"] == "work"

            mock_provider.load("chatcore_text")
            configure_backend_provider(py, mock_provider)
            served = len(mock_provider.requests)
            _, events = turn(py, "and now?", sid)
            assert [e.data["text"] for e in events if e.event == "message"] == [
                "Hello ",
                "from mock.",
            ]
            sent = mock_provider.requests[served]["messages"]
            roles = [m["role"] for m in sent if m["role"] != "system"]
            assert roles == ["user", "assistant", "tool", "assistant", "user"]
            assert sent[2]["tool_calls"][0]["id"] == "call_mock_1"
    finally:
        python.stop()


def test_first_turn_generates_a_title(chat, mock_provider) -> None:
    client = chat("chatcore_text")
    sid, _ = turn(client, "say hello")
    for _ in range(50):
        if history(client, sid)["lead"]["title"] == "Mock title":
            break
        time.sleep(0.1)
    assert history(client, sid)["lead"]["title"] == "Mock title"
    assert len(mock_provider.side_requests) == 1
    side = mock_provider.side_requests[0]
    assert side["stream"] is False
    assert side["max_completion_tokens"] == 20
    assert side["messages"][1] == {"role": "user", "content": "say hello"}
    turn(client, "again", sid)
    assert len(mock_provider.side_requests) == 1
