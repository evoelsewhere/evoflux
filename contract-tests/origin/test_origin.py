"""Host and Origin checks of the local API (owner decision 2026-11-01).

Rust-only difference (KNOWN_DIFFERENCES): Python answers any Origin and Host
(``CORSMiddleware`` with ``CORS_ORIGINS = ["*"]``); the Rust gateway refuses a
foreign ``Origin`` or ``Host`` with 403 in front of every route, Rust- or
Python-owned. Requests with no ``Origin`` and the app's own origins still work
on both backends.
"""

from __future__ import annotations

import httpx
import pytest

# /api/health/live is Rust-owned under TARGET=rust (edge-stateless); /api/agents
# stays Python-owned.
ROUTES = ("/api/health/live", "/api/agents")
EVIL_ORIGIN = "https://evil.example"
FORBIDDEN_ORIGIN = {"detail": "Origin not allowed.", "code": "origin_not_allowed"}
FORBIDDEN_HOST = {"detail": "Host not allowed.", "code": "host_not_allowed"}


def _python_skip(target: str) -> None:
    if target == "python":
        pytest.skip("Python allows any Origin and Host (KNOWN_DIFFERENCES)")


@pytest.mark.parametrize("path", ROUTES)
def test_no_origin_is_allowed(client: httpx.Client, path: str) -> None:
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:{port}", "http://localhost:5173", "tauri://localhost"]
)
def test_own_and_app_origins_are_allowed(
    client: httpx.Client, backend, path: str, origin: str
) -> None:
    origin = origin.format(port=backend.base_url.rsplit(":", 1)[1])
    response = client.get(path, headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_evil_origin_is_403(
    client: httpx.Client, target: str, path: str, method: str
) -> None:
    _python_skip(target)
    response = client.request(method, path, headers={"Origin": EVIL_ORIGIN})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_ORIGIN
    assert "access-control-allow-origin" not in response.headers
    assert "Origin" in response.headers["vary"]


def test_evil_origin_sse_is_403(client: httpx.Client, target: str) -> None:
    _python_skip(target)
    response = client.get(
        "/api/team/no-such-session/stream",
        headers={"Origin": EVIL_ORIGIN, "Accept": "text/event-stream"},
    )
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_ORIGIN


@pytest.mark.parametrize("path", ROUTES)
def test_evil_host_is_403(client: httpx.Client, target: str, path: str) -> None:
    _python_skip(target)
    response = client.get(path, headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert response.json() == FORBIDDEN_HOST


@pytest.mark.parametrize("path", ROUTES)
def test_python_cors_headers_do_not_leak(
    client: httpx.Client, target: str, path: str
) -> None:
    """Starlette answers ``*``-style CORS; the gateway echoes only the checked origin."""
    _python_skip(target)
    response = client.get(path)
    assert not [h for h in response.headers if h.startswith("access-control-")]
    assert "Origin" in response.headers["vary"]


@pytest.mark.parametrize("path", ROUTES)
def test_preflight_from_an_app_origin(
    client: httpx.Client, target: str, path: str
) -> None:
    _python_skip(target)
    response = client.options(
        path,
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
    assert response.headers["access-control-allow-headers"] == "authorization"
    assert "POST" in response.headers["access-control-allow-methods"]
