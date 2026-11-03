"""Every HTTP route of the unit needs the access key, before any validation; the socket too."""

from __future__ import annotations

import uuid

import httpx
import pytest
from websockets.sync.client import connect

from tp_helpers import UNAUTHORIZED_BODY

SID = "11111111-1111-1111-1111-111111111111"
WS = "C:/does-not-matter"
T = "/api/team"

ROUTES: list[tuple[str, str, dict[str, str], object]] = [
    ("GET", f"{T}/{SID}/terminals", {}, None),
    ("DELETE", f"{T}/{SID}/terminals/default", {}, None),
    ("GET", f"{T}/processes", {}, None),
    ("DELETE", f"{T}/processes/proc_x", {}, None),
    ("GET", f"{T}/preview/targets", {"workspace": WS}, None),
    ("POST", f"{T}/preview/start", {}, {"workspace": WS, "name": "web"}),
    ("POST", f"{T}/preview/stop", {}, {"workspace": WS, "name": "web"}),
    ("GET", f"{T}/workspace/watch", {"workspace": WS}, None),
    ("GET", f"{T}/{SID}/files/watch", {}, None),
]


@pytest.mark.parametrize(
    ("method", "path", "query", "body"),
    ROUTES,
    ids=[f"{m} {p.removeprefix(T)}" for m, p, _, _ in ROUTES],
)
def test_route_requires_the_access_key(backend, method, path, query, body) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        response = anonymous.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": "Bearer wrong"},
        timeout=30.0,
    ) as wrong:
        response = wrong.request(method, path, params=query, json=body)
        assert response.status_code == 401
        assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize("query", ["", "?_token=wrong", "?_token="])
def test_the_terminal_socket_is_refused_before_it_is_accepted(backend, query: str) -> None:
    """A WebSocket skips the HTTP middleware, so the route authenticates itself: 403 at the handshake."""
    url = backend.base_url.replace("http://", "ws://")
    with pytest.raises(Exception) as caught:  # noqa: PT011 - websockets raises InvalidStatus
        with connect(f"{url}/api/team/{uuid.uuid4()}/terminal{query}", open_timeout=30):
            pass
    response = getattr(caught.value, "response", None)
    assert response is not None, repr(caught.value)
    assert response.status_code == 403
