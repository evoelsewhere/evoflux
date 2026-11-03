"""The extension relay socket, the external agent socket, status and audit."""

from __future__ import annotations

import json
import time

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from wb_helpers import FakeExtension, T, dumps

TABS = [{"id": 3, "url": "https://example.com/page", "title": "Example"}]


def _ws(backend, path: str) -> str:
    return backend.base_url.replace("http://", "ws://") + path


def _ticket(paired) -> str:
    return paired.post(f"{T}/relay-ticket").json()["ticket"]


def _wait_for(check, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    return check()


def test_status_and_audit_when_nothing_is_connected(client) -> None:
    assert client.get(f"{T}/status").json() == {"connected": False, "extensions": []}
    assert client.get(f"{T}/audit").json() == {"entries": []}
    assert client.get(f"{T}/audit", params={"limit": 0}).json() == {"entries": []}
    for bad in ["x", "1.5", ""]:
        response = client.get(f"{T}/audit", params={"limit": bad})
        assert response.status_code == 422, bad
        assert response.json()["detail"][0]["loc"] == ["query", "limit"]


def test_register_acknowledges_with_the_pairing_identity(
    backend, client, pairing, paired
) -> None:
    with connect(
        _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"), open_timeout=30
    ) as ws:
        ws.send(
            dumps(
                {
                    "type": "register",
                    "extension_id": "ignored-by-server",
                    "browser": "edge",
                    "version": "126.1",
                    "protocol_version": 2,
                    "capabilities": {"commands": ["navigate", "click"]},
                }
            )
        )
        ack = json.loads(ws.recv(timeout=30))
        assert ack == {
            "type": "registered",
            "extension_id": pairing.id,
            "pairing_id": pairing.id,
            "protocol_version": 2,
        }
        status = client.get(f"{T}/status").json()
        assert status["connected"] is True
        (info,) = status["extensions"]
        assert list(info) == [
            "extension_id",
            "browser",
            "version",
            "protocol_version",
            "capabilities",
            "connected_at",
            "current_url",
            "current_title",
            "tabs",
            "automation",
        ]
        assert info["extension_id"] == pairing.id
        assert (info["browser"], info["version"]) == ("edge", "126.1")
        assert info["protocol_version"] == 2
        assert info["capabilities"] == {"commands": ["navigate", "click"]}
        assert isinstance(info["connected_at"], float)
        assert (
            info["current_url"],
            info["current_title"],
            info["tabs"],
            info["automation"],
        ) == (
            "",
            "",
            [],
            {},
        )
        # tab and automation events update the live status
        ws.send(
            dumps(
                {
                    "type": "event",
                    "event": "tab_updated",
                    "data": {"tabs": TABS, "url": TABS[0]["url"], "title": "Example"},
                }
            )
        )
        ws.send(
            dumps(
                {"type": "event", "event": "automation_state", "data": {"active": True}}
            )
        )
        ws.send(dumps({"type": "ping"}))
        assert json.loads(ws.recv(timeout=30)) == {"type": "pong"}
        (info,) = client.get(f"{T}/status").json()["extensions"]
        assert info["tabs"] == TABS
        assert info["current_url"] == "https://example.com/page"
        assert info["current_title"] == "Example"
        assert info["automation"] == {"active": True}
    assert _wait_for(
        lambda: (
            client.get(f"{T}/status").json() == {"connected": False, "extensions": []}
        )
    )


def test_register_defaults_and_ignored_frames(backend, client, pairing, paired) -> None:
    with connect(
        _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"), open_timeout=30
    ) as ws:
        # frames before register, non-JSON text and unknown types are ignored
        ws.send(dumps({"type": "ping"}))
        ws.send("not json")
        ws.send(dumps({"type": "mystery"}))
        ws.send(dumps({"type": "register"}))
        assert json.loads(ws.recv(timeout=30))["type"] == "registered"
        (info,) = client.get(f"{T}/status").json()["extensions"]
        assert (
            info["browser"],
            info["version"],
            info["protocol_version"],
            info["capabilities"],
        ) == (
            "unknown",
            "unknown",
            1,
            {},
        )
        ws.send(dumps({"type": "pong"}))
        ws.send(dumps({"type": "ping"}))
        assert json.loads(ws.recv(timeout=30)) == {"type": "pong"}


def test_a_ticket_works_once(backend, paired) -> None:
    ticket = _ticket(paired)
    with connect(_ws(backend, f"{T}/relay?_ticket={ticket}"), open_timeout=30):
        pass
    with pytest.raises(Exception) as caught:  # noqa: PT011
        with connect(_ws(backend, f"{T}/relay?_ticket={ticket}"), open_timeout=30):
            pass
    assert caught.value.response.status_code == 403


def test_a_new_registration_displaces_the_old_socket_with_4409(
    backend, client, pairing, paired
) -> None:
    with connect(
        _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"), open_timeout=30
    ) as first:
        first.send(dumps({"type": "register", "browser": "first"}))
        assert json.loads(first.recv(timeout=30))["type"] == "registered"
        with connect(
            _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"), open_timeout=30
        ) as second:
            second.send(dumps({"type": "register", "browser": "second"}))
            assert json.loads(second.recv(timeout=30))["type"] == "registered"
            with pytest.raises(ConnectionClosed) as closed:
                first.recv(timeout=30)
            assert closed.value.rcvd.code == 4409
            (info,) = client.get(f"{T}/status").json()["extensions"]
            assert info["browser"] == "second"
        assert _wait_for(lambda: client.get(f"{T}/status").json()["connected"] is False)


def test_deleting_the_pairing_closes_its_socket_with_4403(
    backend, client, pairing, paired
) -> None:
    with connect(
        _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"), open_timeout=30
    ) as ws:
        ws.send(dumps({"type": "register"}))
        assert json.loads(ws.recv(timeout=30))["type"] == "registered"
        assert client.delete(f"{T}/pairings/{pairing.id}").status_code == 204
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=30)
        assert closed.value.rcvd.code == 4403
    assert client.get(f"{T}/status").json()["connected"] is False


def test_an_oversize_frame_closes_the_relay_with_1009(backend, paired) -> None:
    with connect(
        _ws(backend, f"{T}/relay?_ticket={_ticket(paired)}"),
        open_timeout=30,
        max_size=None,
    ) as ws:
        ws.send(dumps({"type": "register"}))
        assert json.loads(ws.recv(timeout=30))["type"] == "registered"
        ws.send("x" * 1_000_001)
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=30)
        assert closed.value.rcvd.code == 1009


def test_agent_socket_without_an_extension_answers_no_extension(
    backend, client
) -> None:
    url = _ws(backend, f"{T}/agent/session-x?_token={backend.token}")
    with connect(url, open_timeout=30) as ws:
        ws.send(dumps({"action": "navigate", "url": "https://example.com"}))
        assert json.loads(ws.recv(timeout=30)) == {
            "type": "no_extension",
            "error": "No browser extension connected. Install the EvoFlux WebBridge extension and open Chrome/Edge.",
        }
        # frames without an action and non-JSON frames get no reply; status is answered
        ws.send("not json")
        ws.send(dumps({"nothing": True}))
        ws.send(dumps({"action": "status"}))
        reply = json.loads(ws.recv(timeout=30))
        assert reply["type"] == "response"
        assert reply == {
            "type": "response",
            "success": True,
            "data": {"connected": False, "extensions": []},
            "error": None,
        }


def test_agent_socket_forwards_commands_and_events(
    backend, client, pairing, paired
) -> None:
    def answer(command: dict) -> dict:
        return {"success": True, "data": {"echo": command["action"]}}

    with FakeExtension(
        backend.base_url, _ticket(paired), answer=answer, tabs=TABS
    ) as extension:
        url = _ws(backend, f"{T}/agent/agent-session?_token={backend.token}")
        with connect(url, open_timeout=30) as ws:
            ws.send(dumps({"action": "get_tabs"}))
            reply = json.loads(ws.recv(timeout=30))
            assert reply["type"] == "response"
            assert reply["success"] is True
            assert reply["data"] == {"echo": "get_tabs"}
            assert isinstance(reply["request_id"], str)
            sent = extension.commands[-1]
            assert sent["type"] == "command"
            assert sent["action"] == "get_tabs"
            assert sent["request_id"] == reply["request_id"]
            # a tab-scoped command with no bound or explicit tab fails closed, before the extension
            ws.send(dumps({"action": "evaluate", "script": "1+1"}))
            refused = json.loads(ws.recv(timeout=30))
            assert refused["type"] == "response"
            assert refused["success"] is False
            assert refused["error"].startswith("UNBOUND_TARGET: No tab is bound")
            assert [c["action"] for c in extension.commands] == ["get_tabs"]
            ws.send(dumps({"action": "evaluate", "script": "1+1", "tab_id": 3}))
            second = json.loads(ws.recv(timeout=30))
            assert second["type"] == "response"
            assert second["success"] is True
            assert extension.commands[-1]["action"] == "evaluate"
            assert extension.commands[-1]["params"]["script"] == "1+1"
            assert extension.commands[-1]["params"]["tab_id"] == 3
            # events from the extension fan out to the subscribed agent socket
            extension.ws.send(
                dumps(
                    {
                        "type": "event",
                        "event": "tab_updated",
                        "data": {"tabs": TABS, "url": "u", "title": "t"},
                    }
                )
            )
            event = json.loads(ws.recv(timeout=30))
            assert event["type"] == "event"
            assert event["event"] == "tab_updated"
    audit = client.get(f"{T}/audit").json()["entries"]
    assert [(e["action"], e["success"]) for e in audit] == [
        ("evaluate", True),
        ("unbound_target", False),
        ("get_tabs", True),
    ]
    assert all(e["direction"] == "agent_out" for e in audit)
    assert all(e["url"] == "https://example.com/page" for e in audit)
    assert audit[0]["session_id"] == "agent-session"
    limited = client.get(f"{T}/audit", params={"limit": 1}).json()["entries"]
    assert [e["action"] for e in limited] == ["evaluate"]
    assert client.get(f"{T}/audit", params={"limit": -1}).json() == {"entries": []}


def test_agent_socket_oversize_frame_closes_with_1009(backend) -> None:
    url = _ws(backend, f"{T}/agent/s?_token={backend.token}")
    with connect(url, open_timeout=30, max_size=None) as ws:
        ws.send("x" * 1_000_001)
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=30)
        assert closed.value.rcvd.code == 1009
