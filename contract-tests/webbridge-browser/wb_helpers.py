"""Shared builders for the ``webbridge-browser`` contract."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass

from websockets.sync.client import connect

UNAUTHORIZED_BODY = {"detail": "Unauthorized — EvoFlux access key required."}
EXTENSION_ORIGIN = "chrome-extension://lghglpnddenmebbhkfachafichhglafi"
T = "/api/team/webbridge"
INVALID_PAIRING = {
    "detail": {"code": "invalid_pairing", "message": "Pair WebBridge first."}
}
ALL_SCOPES = [
    "bindings:write",
    "handoff:reply",
    "interactions:write",
    "relay",
    "session-stream:read",
    "session:messages:write",
    "sessions:create",
    "sessions:list",
    "teach:drafts:write",
]


@dataclass
class Pairing:
    id: str
    credential: str
    scopes: list[str]

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credential}"}


def dumps(value: object) -> str:
    return json.dumps(value)


class FakeExtension:
    """Stands in for the browser extension: connects with a ticket, registers, answers commands."""

    def __init__(self, base_url: str, ticket: str, *, answer=None, tabs=None) -> None:
        self.tabs = tabs
        self.url = (
            base_url.replace("http://", "ws://")
            + "/api/team/webbridge/relay?_ticket="
            + ticket
        )
        self.commands: list[dict] = []
        self.answer = answer or (
            lambda command: {"success": True, "data": {"ok": True}}
        )
        self.ws = None
        self._thread: threading.Thread | None = None
        self.registered: dict | None = None

    def __enter__(self) -> "FakeExtension":
        self.ws = connect(self.url, open_timeout=30)
        self.ws.send(
            dumps(
                {
                    "type": "register",
                    "browser": "chrome",
                    "version": "120",
                    "capabilities": {"commands": ["navigate"]},
                }
            )
        )
        self.registered = json.loads(self.ws.recv(timeout=30))
        if self.tabs is not None:
            url = self.tabs[0].get("url", "")
            self.ws.send(
                dumps(
                    {
                        "type": "event",
                        "event": "tab_updated",
                        "data": {"tabs": self.tabs, "url": url, "title": "Page"},
                    }
                )
            )
            self.ws.send(dumps({"type": "ping"}))
            assert json.loads(self.ws.recv(timeout=30)) == {"type": "pong"}
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        return self

    def _pump(self) -> None:
        try:
            while True:
                raw = self.ws.recv(timeout=60)
                message = json.loads(raw)
                if message.get("type") == "command":
                    self.commands.append(message)
                    result = self.answer(message)
                    if result is not None:
                        self.ws.send(
                            dumps(
                                {
                                    "type": "response",
                                    "request_id": message["request_id"],
                                    **result,
                                }
                            )
                        )
        except Exception:
            return

    def __exit__(self, *exc) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
