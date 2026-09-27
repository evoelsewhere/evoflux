"""Remote-use route shapes, serve control, and the 409 lock body."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.app import create_app
from app.api.routes.remote_use import router as remote_use_router
from app.core.desktop_auth import DesktopTokenMiddleware
from app.services import remote_use_service as service

LOGIN_HEADER = "Tailscale-User-Login"


@pytest.fixture
def remote_app() -> FastAPI:
    """The routes behind the identity hook, as mounted in production."""
    app = FastAPI()
    app.add_middleware(DesktopTokenMiddleware)
    app.include_router(remote_use_router, prefix="/api/remote-use")
    return app


async def test_remote_use_router_is_mounted_on_create_app() -> None:
    app = create_app()
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/remote-use/status" in paths
    assert "/api/remote-use/bootstrap" in paths
    assert "/api/remote-use/connect" in paths
    assert "/api/remote-use/enable" in paths
    assert "/api/remote-use/disable" in paths
    assert "/api/remote-use/release" in paths


async def test_embedded_connect_returns_login_url(monkeypatch, remote_app) -> None:
    monkeypatch.setenv(service.EMBEDDED_TAILNET_BIN_ENV, "/bundled/evoflux-tailnet")

    async def fake_request(method: str, path: str, port: int | None):
        assert (method, path) == ("POST", "/v1/login")
        assert port is not None
        return {
            "tailscale": {
                "provider": "embedded",
                "installed": True,
                "logged_in": False,
                "https_certs": None,
                "auth_url": "https://login.tailscale.com/a/example",
                "error": None,
            },
            "serve": {"enabled": False, "url": None},
        }

    monkeypatch.setattr(service._embedded_manager, "request", fake_request)
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/remote-use/connect")
    assert response.status_code == 200
    assert response.json()["tailscale"]["provider"] == "embedded"
    assert response.json()["tailscale"]["auth_url"].startswith(
        "https://login.tailscale.com/"
    )
    assert response.json()["lock"] is None


async def test_status_shape_when_ready_and_unlocked(
    tailscale_stub: Path, remote_app
) -> None:
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/remote-use/status")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"tailscale", "serve", "lock"}
    assert set(payload["tailscale"]) == {
        "installed",
        "logged_in",
        "https_certs",
        "error",
    }
    assert set(payload["serve"]) == {"enabled", "url"}
    assert payload["tailscale"]["installed"] is True
    assert payload["tailscale"]["logged_in"] is True
    assert payload["tailscale"]["error"] is None
    assert payload["serve"]["enabled"] is True
    assert payload["serve"]["url"] == "https://machine.tailnet-example.ts.net"
    assert payload["lock"] is None


async def test_status_reports_the_live_lock_holder(
    tailscale_stub: Path, remote_app
) -> None:
    claimed = await service.claim("[EMAIL_6]", "phone")
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = (await client.get("/api/remote-use/status")).json()
    lock = payload["lock"]
    assert lock == {
        "user_login": "[EMAIL_6]",
        "device_label": "phone",
        "claimed_at": claimed.claimed_at.isoformat(),
        "last_seen_at": claimed.last_seen_at.isoformat(),
    }


async def test_enable_and_disable_roundtrip(tailscale_stub: Path, remote_app) -> None:
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        enabled = await client.post("/api/remote-use/enable")
        disabled = await client.post("/api/remote-use/disable")
    assert enabled.status_code == 200
    assert set(enabled.json()) == {"tailscale", "serve", "lock"}
    assert enabled.json()["tailscale"]["error"] is None
    calls = (tailscale_stub / "calls.log").read_text(encoding="utf-8")
    assert "serve --bg http://" + ".".join(("127", "0", "0", "1")) + ":" in calls
    assert disabled.status_code == 200
    assert set(disabled.json()) == {"tailscale", "serve", "lock"}
    assert "serve reset" in calls
    # Uniform payload: enable/disable also report the lock section.
    assert enabled.json()["lock"] is None


async def test_release_force_releases_the_lock(
    tailscale_stub: Path, remote_app
) -> None:
    await service.claim("[EMAIL_6]", "phone")
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        before = (await client.get("/api/remote-use/status")).json()
        released = await client.post("/api/remote-use/release")
        after = (await client.get("/api/remote-use/status")).json()
    assert before["lock"]["user_login"] == "[EMAIL_6]"
    assert released.status_code == 200
    assert released.json()["lock"] is None
    assert after["lock"] is None
    assert await service.get_lock_holder() is None


async def test_conflicting_remote_status_request_is_409(
    tailscale_stub: Path, remote_app
) -> None:
    await service.claim("[EMAIL_6]", "phone")
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/remote-use/status",
            headers={LOGIN_HEADER: "[EMAIL_7]", "User-Agent": "iPad"},
        )
    assert response.status_code == 409
    body = response.json()
    assert set(body) == {"detail", "current", "live_window_minutes"}
    assert body["current"]["user_login"] == "[EMAIL_6]"
    assert body["live_window_minutes"] == 30
    assert "[EMAIL_6]" in body["detail"]


async def test_remote_status_claim_is_transparent_for_the_holder(
    tailscale_stub: Path, remote_app
) -> None:
    transport = ASGITransport(app=remote_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/remote-use/status",
            headers={LOGIN_HEADER: "[EMAIL_6]", "User-Agent": "Pixel-8"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["lock"]["user_login"] == "[EMAIL_6]"
    assert payload["lock"]["device_label"] == "Pixel-8"
