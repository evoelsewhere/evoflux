"""Access-key routes, pairing-credential routes and the sockets that authenticate themselves."""

from __future__ import annotations

import httpx
import pytest
from websockets.sync.client import connect

from wb_helpers import INVALID_PAIRING, T, UNAUTHORIZED_BODY

SID = "11111111-1111-1111-1111-111111111111"
PID = "22222222-2222-2222-2222-222222222222"
API = "/api/team"

# Every route outside the exact custom-auth list needs the app access key before
# validation or lookup.
ACCESS_KEY_ROUTES: list[tuple[str, str, object]] = [
    ("GET", f"{T}/native-discovery", None),
    ("GET", f"{T}/pairings", None),
    ("DELETE", f"{T}/pairings/{PID}", None),
    ("PUT", f"{T}/pairings/{PID}/sessions/{SID}", None),
    ("GET", f"{T}/status", None),
    ("GET", f"{T}/audit", None),
    ("GET", f"{T}/teach-drafts/review", None),
    ("POST", f"{T}/teach-drafts/{PID}/approve", None),
    ("DELETE", f"{T}/teach-drafts/{PID}", None),
    ("POST", f"{T}/teach-drafts/{PID}/replay", {}),
    ("POST", f"{T}/teach-drafts/{PID}/replay/resolve", {}),
    ("GET", f"{API}/browser/agent/sessions", None),
    ("GET", f"{API}/{SID}/browser", None),
    ("GET", f"{API}/{SID}/browser/agent", None),
    ("POST", f"{API}/{SID}/browser/agent/command", {"action": "status"}),
    ("GET", f"{API}/{SID}/computer/agent", None),
    ("POST", f"{API}/{SID}/computer/closed", None),
    ("GET", "/api/settings/webbridge", None),
    ("PUT", "/api/settings/webbridge", {}),
    ("GET", "/api/settings/webbridge/agent-browsing", None),
    ("PUT", "/api/settings/webbridge/agent-browsing", {"enabled": True}),
    ("GET", "/api/settings/computer-app", None),
    ("PUT", "/api/settings/computer-app", {}),
]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    ACCESS_KEY_ROUTES,
    ids=[f"{m} {p.removeprefix(API)}" for m, p, _ in ACCESS_KEY_ROUTES],
)
def test_route_requires_the_access_key(backend, method, path, body) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}):
        with httpx.Client(
            base_url=backend.base_url, headers=headers, timeout=30.0
        ) as caller:
            response = caller.request(method, path, json=body)
            assert response.status_code == 401
            assert response.json() == UNAUTHORIZED_BODY


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{T}/appearance"),
        ("GET", f"{T}/bindings"),
        ("DELETE", f"{T}/bindings/3"),
        ("POST", f"{T}/relay-ticket"),
        ("GET", f"{T}/sessions"),
        ("GET", f"{T}/models"),
    ],
)
def test_pairing_routes_refuse_without_a_pairing_credential(
    backend, client, method, path
) -> None:
    """The access key is not a pairing credential; these routes skip the middleware."""
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": f"Bearer {backend.token}"},
        {"Authorization": "Basic abc"},
    ):
        with httpx.Client(
            base_url=backend.base_url, headers=headers, timeout=30.0
        ) as caller:
            response = caller.request(method, path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == INVALID_PAIRING


def test_validation_runs_before_the_pairing_check_on_custom_auth_routes(
    backend,
) -> None:
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        invalid = anonymous.put(f"{T}/bindings/3", json={})
        assert invalid.status_code == 422
        assert invalid.json()["detail"][0]["loc"] == ["body", "session_id"]
        valid = anonymous.put(f"{T}/bindings/3", json={"session_id": SID})
        assert valid.status_code == 401
        assert valid.json() == INVALID_PAIRING
        non_int = anonymous.put(f"{T}/bindings/x", json={"session_id": SID})
        assert non_int.status_code == 422
        assert non_int.json()["detail"][0]["loc"] == ["path", "tab_id"]
        teach = anonymous.post(f"{T}/teach-drafts", json={})
        assert teach.status_code == 422


@pytest.mark.parametrize("query", ["", "?_token=wrong", "?_token="])
@pytest.mark.parametrize(
    "path",
    [
        f"{API}/{SID}/browser/agent",
        f"{API}/{SID}/browser/presence",
        f"{API}/{SID}/computer/agent",
        f"{T}/agent/{SID}",
    ],
)
def test_bridge_sockets_are_refused_before_they_are_accepted(
    backend, path: str, query: str
) -> None:
    url = backend.base_url.replace("http://", "ws://")
    with pytest.raises(Exception) as caught:  # noqa: PT011 - websockets raises InvalidStatus
        with connect(f"{url}{path}{query}", open_timeout=30):
            pass
    response = getattr(caught.value, "response", None)
    assert response is not None, repr(caught.value)
    assert response.status_code == 403


@pytest.mark.parametrize(
    "query", ["", "?_ticket=wrong", "?_ticket=00000000-0000-0000-0000-000000000000"]
)
def test_the_extension_relay_refuses_a_missing_or_unknown_ticket(
    backend, query: str
) -> None:
    url = backend.base_url.replace("http://", "ws://")
    with pytest.raises(Exception) as caught:  # noqa: PT011
        with connect(f"{url}{T}/relay{query}", open_timeout=30):
            pass
    response = getattr(caught.value, "response", None)
    assert response is not None, repr(caught.value)
    assert response.status_code == 403


def test_the_access_key_does_not_open_the_extension_relay(backend) -> None:
    url = backend.base_url.replace("http://", "ws://")
    with pytest.raises(Exception) as caught:  # noqa: PT011
        with connect(f"{url}{T}/relay?_token={backend.token}", open_timeout=30):
            pass
    assert caught.value.response.status_code == 403
