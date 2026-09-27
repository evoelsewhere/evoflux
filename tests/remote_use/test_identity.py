"""Identity attribution: Serve header → remote session, absent → desktop."""

from __future__ import annotations

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.desktop_auth import DesktopTokenMiddleware, remote_session_login
from app.services import remote_use_service as service

LOGIN_HEADER = "Tailscale-User-Login"


def _app_with_token(token: str) -> FastAPI:
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware, expected_token=token)

    @app.get("/api/_probe/whoami")
    async def whoami(request: Request) -> dict:  # noqa: F821
        return {"login": remote_session_login(request)}

    return app


async def test_header_attributes_remote_session(identity_app: FastAPI) -> None:
    transport = ASGITransport(app=identity_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/_probe/whoami",
            headers={LOGIN_HEADER: "alice@example.com", "User-Agent": "Pixel-8"},
        )
    assert response.status_code == 200
    assert response.json() == {"login": "alice@example.com"}
    # The transparent claim on API paths recorded the session...
    holder = await service.get_lock_holder()
    assert holder is not None
    assert holder.user_login == "alice@example.com"
    assert holder.device_label == "Pixel-8"


async def test_no_header_is_a_desktop_session(identity_app: FastAPI) -> None:
    transport = ASGITransport(app=identity_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/_probe/whoami")
    assert response.status_code == 200
    assert response.json() == {"login": None}
    # ...and no desktop request ever touches the lock.
    assert await service.get_lock_holder() is None


async def test_conflicting_remote_request_gets_409_body(
    identity_app: FastAPI,
) -> None:
    await service.claim("alice@example.com", "phone")
    transport = ASGITransport(app=identity_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/_probe/whoami",
            headers={LOGIN_HEADER: "bob@example.com", "User-Agent": "iPad"},
        )
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"detail", "current", "live_window_minutes"}
    assert body["current"]["user_login"] == "alice@example.com"
    assert body["current"]["device_label"] == "phone"
    assert body["live_window_minutes"] == 30
    assert "alice@example.com" in body["detail"]


async def test_same_device_reclaim_stays_200(identity_app: FastAPI) -> None:
    await service.claim("alice@example.com", "Pixel-8")
    transport = ASGITransport(app=identity_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/_probe/whoami",
            headers={LOGIN_HEADER: "alice@example.com", "User-Agent": "Pixel-8"},
        )
    assert response.status_code == 200
    assert response.json() == {"login": "alice@example.com"}


async def test_non_api_path_attributes_without_claiming(
    identity_app: FastAPI,
) -> None:
    transport = ASGITransport(app=identity_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/assets/app.js", headers={LOGIN_HEADER: "alice@example.com"}
        )
    assert response.status_code == 200
    assert response.json() == {"login": "alice@example.com"}
    assert await service.get_lock_holder() is None


async def test_remote_header_authorizes_without_desktop_token() -> None:
    app = _app_with_token("sekrit")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/_probe/whoami", headers={LOGIN_HEADER: "alice@example.com"}
        )
    assert response.status_code == 200
    assert response.json() == {"login": "alice@example.com"}
    assert await service.get_lock_holder() is not None


async def test_desktop_request_still_requires_the_token() -> None:
    app = _app_with_token("sekrit")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        rejected = await client.get("/api/_probe/whoami")
        accepted = await client.get(
            "/api/_probe/whoami", headers={"Authorization": "Bearer sekrit"}
        )
    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"login": None}
