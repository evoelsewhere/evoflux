"""Every WebSocket route authenticates before it accepts.

``DesktopTokenMiddleware`` derives from ``BaseHTTPMiddleware``, which
Starlette runs for ``http`` scopes only — a WebSocket route passes it
untouched. Three routes relied on it anyway and were reachable with no
credential at all: the terminal one spawned a PTY and replayed the
session's scrollback to whoever connected.

Loopback binding is not the defence people assume it is here. A
WebSocket handshake is not subject to CORS, so any page the user happens
to be visiting can open a socket to 127.0.0.1 and be handed a live
connection. The browser does send an ``Origin`` on that handshake, which
is what these tests pin.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core import desktop_auth
from app.core.desktop_auth import trusted_local_origin, websocket_authorized


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.websocket("/api/team/{session_id}/probe")
    async def probe(ws: WebSocket, session_id: str) -> None:
        if not await websocket_authorized(ws):
            return
        await ws.accept()
        await ws.send_text(f"open:{session_id}")

    return TestClient(app)


def _connect(client: TestClient, path: str, **kwargs) -> str:
    with client.websocket_connect(path, **kwargs) as ws:
        return ws.receive_text()


class TestOriginGate:
    """With no token configured, the origin is the whole defence."""

    @pytest.fixture(autouse=True)
    def _no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop_auth, "expected_desktop_token", lambda: "")

    def test_a_page_on_another_site_is_refused(self, client: TestClient) -> None:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            _connect(
                client,
                "/api/team/s1/probe",
                headers={"origin": "https://evil.example"},
            )
        assert excinfo.value.code == 4401

    def test_the_apps_own_page_is_allowed(self, client: TestClient) -> None:
        assert (
            _connect(
                client,
                "/api/team/s1/probe",
                headers={"origin": "http://localhost:5173"},
            )
            == "open:s1"
        )

    def test_a_non_browser_client_is_allowed(self, client: TestClient) -> None:
        """No Origin means a CLI, a test, or the Tauri shell — not a page."""
        assert _connect(client, "/api/team/s1/probe") == "open:s1"

    @pytest.mark.parametrize(
        "origin",
        [
            "http://127.0.0.1:5173",
            "http://[::1]:5173",
            "https://localhost",
        ],
    )
    def test_loopback_spellings_are_allowed(self, origin: str) -> None:
        assert trusted_local_origin(origin) is True

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "http://localhost.evil.example",
            "http://127.0.0.1.evil.example",
            "file://",
            "chrome-extension://abcdef",
            "not a url",
        ],
    )
    def test_everything_else_is_refused(self, origin: str) -> None:
        assert trusted_local_origin(origin) is False


class TestTokenGate:
    """With a token configured, the token is required — origin is moot."""

    @pytest.fixture(autouse=True)
    def _token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(desktop_auth, "expected_desktop_token", lambda: "s3cret")

    def test_the_matching_token_is_accepted(self, client: TestClient) -> None:
        assert _connect(client, "/api/team/s1/probe?_token=s3cret") == "open:s1"

    @pytest.mark.parametrize("query", ["", "?_token=", "?_token=wrong"])
    def test_a_missing_or_wrong_token_is_refused(
        self, client: TestClient, query: str
    ) -> None:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            _connect(client, f"/api/team/s1/probe{query}")
        assert excinfo.value.code == 4401

    def test_a_local_origin_does_not_substitute_for_the_token(
        self, client: TestClient
    ) -> None:
        """The desktop tier is strict: being local is not being authorised."""
        with pytest.raises(WebSocketDisconnect) as excinfo:
            _connect(
                client,
                "/api/team/s1/probe",
                headers={"origin": "http://localhost:5173"},
            )
        assert excinfo.value.code == 4401


class TestEveryRouteIsGuarded:
    def test_no_websocket_route_accepts_before_authenticating(self) -> None:
        """A new WebSocket route must not be able to forget this.

        Guarding is one line, and the cost of omitting it is a PTY handed
        to an unauthenticated caller — so the check is asserted over the
        whole app rather than route by route.
        """
        import inspect

        from app.api.routes.team import browser, terminal, webbridge

        sources = [
            inspect.getsource(module)
            for module in (browser, terminal, webbridge)
        ]
        routes = 0
        for source in sources:
            for block in source.split("@router.websocket(")[1:]:
                routes += 1
                body = block.split("\n\n\n")[0]
                accept = body.find("await ws.accept()")
                assert accept != -1, "a websocket route that never accepts?"
                guard = max(
                    body.find("websocket_authorized"),
                    body.find("_agent_ws_authorized"),
                    body.find("_consume_extension_ticket"),
                )
                assert guard != -1, f"unguarded websocket route:\n{body[:200]}"
                assert guard < accept, (
                    f"websocket route accepts before authenticating:\n{body[:200]}"
                )
        assert routes == 5
