"""The desktop in-app browser and computer-app bridges (sockets stand in for the desktop shell)."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from wb_helpers import dumps

SID = "66666666-6666-6666-6666-666666666666"
API = "/api/team"


def _ws(backend, path: str) -> str:
    return (
        backend.base_url.replace("http://", "ws://") + f"{path}?_token={backend.token}"
    )


def _wait_for(check, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    return check()


def _ready(ws, **extra) -> None:
    ws.send(dumps({"type": "ready", **extra}))


class Desktop:
    """Answers each command frame with ``answer(frame)`` on a background thread."""

    def __init__(self, ws, answer) -> None:
        self.ws = ws
        self.frames: list[dict] = []
        self.answer = answer
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                frame = json.loads(self.ws.recv(timeout=60))
                self.frames.append(frame)
                reply = self.answer(frame)
                if reply is not None and "id" in frame:
                    self.ws.send(dumps({"id": frame["id"], **reply}))
        except Exception:
            return


def test_idle_state(client) -> None:
    assert client.get(f"{API}/browser/agent/sessions").json() == []
    assert client.get(f"{API}/{SID}/browser").json() == {
        "active": False,
        "cdp_url": None,
        "cdp_http": None,
        "current_url": None,
        "current_title": None,
        "tabs": [],
    }
    assert client.get(f"{API}/{SID}/browser/agent").json() == {
        "connected": False,
        "available": False,
        "protocol_version": 0,
        "capabilities": {},
    }
    assert client.get(f"{API}/{SID}/computer/agent").json() == {
        "connected": False,
        "protocol_version": 0,
        "capabilities": {},
    }
    closed = client.post(f"{API}/{SID}/computer/closed")
    assert closed.status_code == 204
    assert closed.content == b""


def test_surface_free_commands_answer_offline_without_mounting(client) -> None:
    status = client.post(
        f"{API}/{SID}/browser/agent/command", json={"action": "status"}
    )
    assert (status.status_code, status.json()) == (
        200,
        {"result": {"connected": False, "tabs": []}},
    )
    tabs = client.post(
        f"{API}/{SID}/browser/agent/command", json={"action": "get_tabs"}
    )
    assert (tabs.status_code, tabs.json()) == (200, {"result": "No tabs open."})


def test_command_validation(client) -> None:
    for body in [{}, {"action": 1}, {"action": "x", "params": []}, {"params": {}}]:
        response = client.post(f"{API}/{SID}/browser/agent/command", json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)


def test_a_command_with_no_desktop_fails_with_409_after_waiting(client) -> None:
    started = time.time()
    response = client.post(
        f"{API}/{SID}/browser/agent/command", json={"action": "click"}
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": "EvoFlux Desktop in-app browser is unavailable for this session"
    }
    assert time.time() - started >= 7.0


def test_presence_registers_a_session_that_can_mount(backend, client) -> None:
    with connect(_ws(backend, f"{API}/{SID}/browser/presence"), open_timeout=30):
        assert _wait_for(
            lambda: client.get(f"{API}/browser/agent/sessions").json() == [SID]
        )
        assert client.get(f"{API}/{SID}/browser/agent").json() == {
            "connected": False,
            "available": True,
            "protocol_version": 0,
            "capabilities": {},
        }
        other = "77777777-7777-7777-7777-777777777777"
        with connect(_ws(backend, f"{API}/{other}/browser/presence"), open_timeout=30):
            assert _wait_for(
                lambda: len(client.get(f"{API}/browser/agent/sessions").json()) == 2
            )
            assert client.get(f"{API}/browser/agent/sessions").json() == sorted(
                [SID, other]
            )
    assert _wait_for(lambda: client.get(f"{API}/browser/agent/sessions").json() == [])


def test_browser_command_round_trip(backend, client) -> None:
    def answer(frame: dict) -> dict | None:
        if frame["action"] == "status":
            return {
                "ok": True,
                "result": {
                    "url": "https://example.com/",
                    "title": "Example",
                    "tabs": [
                        {"index": 0, "url": "https://example.com/", "title": "Example"},
                        {"index": 1, "url": "https://other.test/"},
                    ],
                },
            }
        if frame["action"] == "fail":
            return {"ok": False, "error": "boom"}
        if frame["action"] == "fail-silently":
            return {"ok": False}
        return {"ok": True, "result": {"echo": frame["params"]}}

    with connect(_ws(backend, f"{API}/{SID}/browser/agent"), open_timeout=30) as ws:
        desktop = Desktop(ws, answer)
        # attached but not ready: not connected, commands wait for a mount
        assert client.get(f"{API}/{SID}/browser/agent").json()["connected"] is False
        _ready(
            ws,
            protocol_version=3,
            capabilities={"commands": ["status", "click", "fail", "fail-silently"]},
        )
        assert _wait_for(
            lambda: client.get(f"{API}/{SID}/browser/agent").json()["connected"]
        )
        assert client.get(f"{API}/{SID}/browser/agent").json() == {
            "connected": True,
            "available": False,
            "protocol_version": 3,
            "capabilities": {"commands": ["status", "click", "fail", "fail-silently"]},
        }
        ok = client.post(
            f"{API}/{SID}/browser/agent/command",
            json={"action": "click", "params": {"selector": "#a"}},
        )
        assert (ok.status_code, ok.json()) == (
            200,
            {"result": {"echo": {"selector": "#a"}}},
        )
        assert desktop.frames[-1]["action"] == "click"
        assert desktop.frames[-1]["params"] == {"selector": "#a"}
        assert isinstance(desktop.frames[-1]["id"], str)
        default_params = client.post(
            f"{API}/{SID}/browser/agent/command", json={"action": "click"}
        )
        assert default_params.json() == {"result": {"echo": {}}}
        failed = client.post(
            f"{API}/{SID}/browser/agent/command", json={"action": "fail"}
        )
        assert (failed.status_code, failed.json()) == (422, {"detail": "boom"})
        silent = client.post(
            f"{API}/{SID}/browser/agent/command", json={"action": "fail-silently"}
        )
        assert (silent.status_code, silent.json()) == (
            422,
            {"detail": "Browser command failed"},
        )
        unsupported = client.post(
            f"{API}/{SID}/browser/agent/command", json={"action": "evaluate"}
        )
        assert unsupported.status_code == 422
        assert unsupported.json() == {
            "detail": "Desktop browser protocol v3 does not support 'evaluate'. Update EvoFlux Desktop."
        }
        # surface-free actions are forwarded once connected
        status = client.post(
            f"{API}/{SID}/browser/agent/command", json={"action": "status"}
        )
        assert status.json()["result"]["url"] == "https://example.com/"
        assert client.get(f"{API}/{SID}/browser").json() == {
            "active": True,
            "cdp_url": None,
            "cdp_http": None,
            "current_url": "https://example.com/",
            "current_title": "Example",
            "tabs": [
                {"index": 0, "url": "https://example.com/", "title": "Example"},
                {"index": 1, "url": "https://other.test/", "title": ""},
            ],
        }
    assert _wait_for(
        lambda: client.get(f"{API}/{SID}/browser/agent").json()["connected"] is False
    )
    assert client.get(f"{API}/{SID}/browser/agent").json()["protocol_version"] == 0


def test_browser_status_when_the_desktop_cannot_answer(backend, client) -> None:
    replies = iter(
        [
            {"ok": False, "error": "no"},
            {"ok": True, "result": "not a dict"},
            {"ok": True, "result": {"url": 5, "title": None, "tabs": None}},
        ]
    )
    with connect(_ws(backend, f"{API}/{SID}/browser/agent"), open_timeout=30) as ws:
        Desktop(ws, lambda _frame: next(replies))
        _ready(ws)
        assert _wait_for(
            lambda: client.get(f"{API}/{SID}/browser/agent").json()["connected"]
        )
        # a ready frame without a version or capabilities defaults to protocol 1
        assert client.get(f"{API}/{SID}/browser/agent").json()["protocol_version"] == 1
        active_only = {
            "active": True,
            "cdp_url": None,
            "cdp_http": None,
            "current_url": None,
            "current_title": None,
            "tabs": [],
        }
        for _ in range(3):
            assert client.get(f"{API}/{SID}/browser").json() == active_only


def test_a_command_mounts_the_browser_through_the_presence_socket(
    backend, client
) -> None:
    with connect(
        _ws(backend, f"{API}/{SID}/browser/presence"), open_timeout=30
    ) as presence:
        assert _wait_for(
            lambda: client.get(f"{API}/browser/agent/sessions").json() == [SID]
        )
        result: dict = {}

        def call() -> None:
            with httpx.Client(
                base_url=backend.base_url,
                headers={"Authorization": f"Bearer {backend.token}"},
                timeout=30.0,
            ) as http:
                response = http.post(
                    f"{API}/{SID}/browser/agent/command", json={"action": "navigate"}
                )
                result["status"] = response.status_code
                result["body"] = response.json()

        caller = threading.Thread(target=call)
        caller.start()
        assert json.loads(presence.recv(timeout=30)) == {"action": "open"}
        with connect(_ws(backend, f"{API}/{SID}/browser/agent"), open_timeout=30) as ws:
            Desktop(ws, lambda frame: {"ok": True, "result": "navigated"})
            _ready(ws)
            caller.join(timeout=30)
        assert result == {"status": 200, "body": {"result": "navigated"}}


def test_a_second_browser_attach_displaces_the_first_with_4409(backend, client) -> None:
    with connect(_ws(backend, f"{API}/{SID}/browser/agent"), open_timeout=30) as first:
        _ready(first)
        assert _wait_for(
            lambda: client.get(f"{API}/{SID}/browser/agent").json()["connected"]
        )
        with connect(
            _ws(backend, f"{API}/{SID}/browser/agent"), open_timeout=30
        ) as second:
            with pytest.raises(ConnectionClosed) as closed:
                first.recv(timeout=30)
            assert closed.value.rcvd.code == 4409
            # the newcomer is not ready until it says so
            assert client.get(f"{API}/{SID}/browser/agent").json()["connected"] is False
            _ready(second, version=2)
            assert _wait_for(
                lambda: client.get(f"{API}/{SID}/browser/agent").json()["connected"]
            )
            assert (
                client.get(f"{API}/{SID}/browser/agent").json()["protocol_version"] == 2
            )


def test_computer_bridge_status_and_displacement(backend, client) -> None:
    with connect(_ws(backend, f"{API}/{SID}/computer/agent"), open_timeout=30) as first:
        first.send(dumps(["not", "a", "dict"]))
        first.send(
            dumps({"type": "ready", "protocol_version": 0, "capabilities": ["x"]})
        )
        assert _wait_for(
            lambda: client.get(f"{API}/{SID}/computer/agent").json()["connected"]
        )
        assert client.get(f"{API}/{SID}/computer/agent").json() == {
            "connected": True,
            "protocol_version": 1,
            "capabilities": {},
        }
        with connect(
            _ws(backend, f"{API}/{SID}/computer/agent"), open_timeout=30
        ) as second:
            with pytest.raises(ConnectionClosed) as closed:
                first.recv(timeout=30)
            assert closed.value.rcvd.code == 4409
            second.send(
                dumps(
                    {
                        "type": "ready",
                        "protocol_version": 4,
                        "capabilities": {"commands": ["status"]},
                    }
                )
            )
            assert _wait_for(
                lambda: (
                    client.get(f"{API}/{SID}/computer/agent").json()["protocol_version"]
                    == 4
                )
            )
            assert client.get(f"{API}/{SID}/computer/agent").json() == {
                "connected": True,
                "protocol_version": 4,
                "capabilities": {"commands": ["status"]},
            }
    assert _wait_for(
        lambda: client.get(f"{API}/{SID}/computer/agent").json()["connected"] is False
    )
