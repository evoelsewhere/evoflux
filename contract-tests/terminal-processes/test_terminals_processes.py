"""Terminals (WebSocket PTY), the unified process list and its termination."""

from __future__ import annotations

import json
import re
import time

import httpx
from websockets.sync.client import connect

T = "/api/team"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def socket_url(backend, session: str, **params: str) -> str:
    query = "&".join(f"{k}={v}" for k, v in {"_token": backend.token, **params}.items())
    return f"{backend.base_url.replace('http://', 'ws://')}{T}/{session}/terminal?{query}"


def read_until(ws, pattern: str, timeout: float = 30.0) -> str:
    """Collect PTY output until ``pattern`` (a regex) matches the ANSI-stripped text."""
    output = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            frame = ws.recv(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            break
        if isinstance(frame, bytes):
            output += frame.decode("utf-8", "replace")
            if re.search(pattern, ANSI.sub("", output)):
                return output
    raise AssertionError(f"no match for {pattern!r} in {ANSI.sub('', output)!r}")


def terminals(client: httpx.Client, session: str) -> list[dict]:
    response = client.get(f"{T}/{session}/terminals")
    assert response.status_code == 200, response.text
    return response.json()["terminals"]


def wait_for(check, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise AssertionError("condition not reached")


def test_a_session_without_terminals_lists_none(client: httpx.Client, session_id: str) -> None:
    response = client.get(f"{T}/{session_id}/terminals")
    assert response.status_code == 200
    assert response.json() == {"terminals": []}
    # any string is a session id here: nothing is looked up
    assert client.get(f"{T}/not-a-uuid/terminals").json() == {"terminals": []}


def test_closing_a_terminal_that_does_not_exist_is_a_204(client: httpx.Client, session_id: str) -> None:
    response = client.delete(f"{T}/{session_id}/terminals/nope")
    assert response.status_code == 204 and response.content == b""


def test_a_terminal_runs_commands_is_listed_and_can_be_closed(
    backend, client: httpx.Client, session_id: str
) -> None:
    with connect(socket_url(backend, session_id, cols="100", rows="30"), open_timeout=30) as ws:
        ws.send(json.dumps({"type": "input", "data": "echo contract-marker-1\r"}))
        read_until(ws, r"(?m)^contract-marker-1\s*$")
        assert terminals(client, session_id) == [{"id": "1"}]
        ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
        ws.send("not json")  # ignored, never closes the socket
        ws.send(json.dumps({"type": "input", "data": 5}))  # ignored
        ws.send(json.dumps({"type": "input", "data": "echo contract-marker-2\r"}))
        read_until(ws, r"(?m)^contract-marker-2\s*$")
    # the shell outlives the socket so a reconnecting client lands in the same session
    assert terminals(client, session_id) == [{"id": "1"}]
    with connect(socket_url(backend, session_id), open_timeout=30) as again:
        replay = ANSI.sub("", read_until(again, r"contract-marker-2"))
        assert "contract-marker-1" in replay
    assert client.delete(f"{T}/{session_id}/terminals/1").status_code == 204
    wait_for(lambda: terminals(client, session_id) == [])


def test_several_terminals_per_session_by_tid(backend, client: httpx.Client, session_id: str) -> None:
    with connect(socket_url(backend, session_id, tid="a"), open_timeout=30) as one, connect(
        socket_url(backend, session_id, tid="b"), open_timeout=30
    ) as two:
        one.send(json.dumps({"type": "input", "data": "echo only-in-a\r"}))
        two.send(json.dumps({"type": "input", "data": "echo only-in-b\r"}))
        read_until(one, r"(?m)^only-in-a\s*$")
        text_b = ANSI.sub("", read_until(two, r"(?m)^only-in-b\s*$"))
        assert "only-in-a" not in text_b
        assert sorted(t["id"] for t in terminals(client, session_id)) == ["a", "b"]
        one.send(json.dumps({"type": "close"}))
    wait_for(lambda: [t["id"] for t in terminals(client, session_id)] == ["b"])
    client.delete(f"{T}/{session_id}/terminals/b")
    wait_for(lambda: terminals(client, session_id) == [])


def test_the_terminal_socket_ignores_bad_size_parameters(
    backend, client: httpx.Client, session_id: str
) -> None:
    with connect(socket_url(backend, session_id, cols="abc", rows="-"), open_timeout=30) as ws:
        ws.send(json.dumps({"type": "input", "data": "echo sized\r"}))
        read_until(ws, r"(?m)^sized\s*$")
        ws.send(json.dumps({"type": "close"}))
    client.delete(f"{T}/{session_id}/terminals/1")


# ── processes ─────────────────────────────────────────────────────────────────


def test_the_process_list_is_empty_when_nothing_runs(client: httpx.Client) -> None:
    response = client.get(f"{T}/processes")
    assert response.status_code == 200
    assert response.json() == {"processes": []}


def test_a_terminal_is_listed_as_a_process_and_can_be_terminated(
    backend, client: httpx.Client, session_id: str
) -> None:
    with connect(socket_url(backend, session_id), open_timeout=30) as ws:
        ws.send(json.dumps({"type": "input", "data": "echo up\r"}))
        read_until(ws, r"(?m)^up\s*$")
        rows = client.get(f"{T}/processes").json()["processes"]
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == {
            "id", "kind", "label", "command", "session_id", "pid", "cwd",
            "elapsed_seconds", "killable", "metadata", "session_title",
        }
        assert row["kind"] == "terminal" and row["command"] == "Interactive shell"
        assert row["label"] == "Terminal 1" and row["session_id"] == session_id
        assert row["id"].startswith("terminal_") and len(row["id"]) == len("terminal_") + 20
        assert row["killable"] is True and row["metadata"] == {"terminal_id": "1"}
        assert row["elapsed_seconds"] >= 0 and row["session_title"] is None
        done = client.delete(f"{T}/processes/{row['id']}")
        assert done.status_code == 204 and done.content == b""
    wait_for(lambda: client.get(f"{T}/processes").json() == {"processes": []})


def test_terminating_an_unknown_process_is_a_404(client: httpx.Client) -> None:
    for process_id in ["proc_nope", "terminal_nope", "preview_nope", "x"]:
        response = client.delete(f"{T}/processes/{process_id}")
        assert response.status_code == 404, process_id
        assert response.json() == {"detail": "Process not found"}
