"""Opt-in gateway mode: the Rust gateway's startup contract for Python."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from app.api import app as app_module
from app.core import gateway_mode
from app.core.gateway_mode import GATEWAY_HEADER, GatewaySecretMiddleware

SECRET = "s3cr3t-gateway-value"
DENIED = {"detail": "Direct backend access is not allowed."}


def _guarded_app(secret: str | None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/health/live")
    async def live() -> dict[str, str]:
        return {"ok": "yes"}

    @app.websocket("/ws")
    async def ws_probe(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text("open")

    app.add_middleware(GatewaySecretMiddleware, secret=secret)
    return app


def test_gateway_secret_rejects_missing_header() -> None:
    client = TestClient(_guarded_app(SECRET))
    response = client.get("/api/health/live")
    assert response.status_code == 403
    assert response.json() == DENIED


def test_gateway_secret_rejects_wrong_header() -> None:
    client = TestClient(_guarded_app(SECRET))
    response = client.get("/api/health/live", headers={GATEWAY_HEADER: "nope"})
    assert response.status_code == 403
    assert response.json() == DENIED


def test_gateway_secret_accepts_correct_header() -> None:
    client = TestClient(_guarded_app(SECRET))
    response = client.get("/api/health/live", headers={GATEWAY_HEADER: SECRET})
    assert response.status_code == 200
    assert response.json() == {"ok": "yes"}


def test_gateway_secret_has_no_exempt_paths() -> None:
    client = TestClient(_guarded_app(SECRET))
    assert client.get("/metrics").status_code == 403
    assert client.get("/").status_code == 403


def test_gateway_secret_websocket_rejected_without_header() -> None:
    client = TestClient(_guarded_app(SECRET))
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={GATEWAY_HEADER: "nope"}):
            pass


def test_gateway_secret_websocket_accepted_with_header() -> None:
    client = TestClient(_guarded_app(SECRET))
    with client.websocket_connect("/ws", headers={GATEWAY_HEADER: SECRET}) as ws:
        assert ws.receive_text() == "open"


def test_no_gateway_secret_env_means_no_check() -> None:
    client = TestClient(_guarded_app(None))
    assert client.get("/api/health/live").status_code == 200
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_text() == "open"


def test_create_app_reads_gateway_secret_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVOFLUX_GATEWAY_SECRET", SECRET)
    client = TestClient(app_module.create_app())
    assert client.get("/api/health/live").status_code == 403
    ok = client.get("/api/health/live", headers={GATEWAY_HEADER: SECRET})
    assert ok.status_code != 403


def test_create_app_without_gateway_secret_env_is_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVOFLUX_GATEWAY_SECRET", raising=False)
    client = TestClient(app_module.create_app())
    assert client.get("/api/health/live").status_code != 403


def test_gateway_check_runs_before_desktop_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVOFLUX_GATEWAY_SECRET", SECRET)
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "desktop-token")
    client = TestClient(app_module.create_app())
    # Without the gateway header the desktop-token 401 must not be reached.
    assert client.get("/api/settings").status_code == 403
    through = client.get("/api/settings", headers={GATEWAY_HEADER: SECRET})
    assert through.status_code == 401


# ── EVOFLUX_DISABLE_SERVICES ────────────────────────────────────────────────


def test_disabled_services_default_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOFLUX_DISABLE_SERVICES", raising=False)
    assert gateway_mode.disabled_services() == frozenset()


def test_disabled_services_parses_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOFLUX_DISABLE_SERVICES", " scheduler, mcp ,,dream_scheduler ")
    assert gateway_mode.disabled_services() == frozenset(
        {"scheduler", "mcp", "dream_scheduler"}
    )


def test_service_names_are_exactly_the_twelve() -> None:
    assert gateway_mode.SERVICE_NAMES == frozenset(
        {
            "otel_retention",
            "model_registry_refresh",
            "mcp",
            "plugin_mcp",
            "conductor",
            "agents_validation",
            "scheduler",
            "dream_scheduler",
            "memory_backfill",
            "standalone_coding_purge",
            "webbridge_cleanup",
            "webbridge_artifact_cleanup",
        }
    )


def test_disabled_services_unknown_name_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVOFLUX_DISABLE_SERVICES", "scheduler,bogus")
    with pytest.raises(ValueError, match="bogus"):
        gateway_mode.disabled_services()


@pytest.fixture
def slim_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.settings, "APP_ENV", "test")
    monkeypatch.setattr(app_module, "ensure_workspace_initialized", Mock())
    monkeypatch.setattr(app_module, "seed_wiki", Mock())
    monkeypatch.setattr(app_module, "setup_otel", Mock())
    monkeypatch.setattr(app_module, "stop_otel_retention", AsyncMock())
    monkeypatch.setattr(app_module, "shutdown_otel", Mock())
    monkeypatch.setattr(app_module.stream_store, "close", AsyncMock())
    monkeypatch.setattr(app_module.team_manager, "stop", AsyncMock())
    monkeypatch.setattr(app_module.task_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(app_module.mcp_manager, "stop", AsyncMock())
    dream = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(app_module, "DreamScheduler", Mock(return_value=dream))
    monkeypatch.setattr(
        app_module,
        "load_runtime_settings",
        Mock(return_value=SimpleNamespace(dream=SimpleNamespace(enabled=True))),
    )


async def _run_lifespan() -> FastAPI:
    app = FastAPI()
    async with app_module.lifespan(app):
        await app.state.optional_startup_task
    return app


@pytest.mark.asyncio
async def test_disable_services_skips_scheduler_and_mcp(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.setenv(
        "EVOFLUX_DISABLE_SERVICES", ",".join(sorted(gateway_mode.SERVICE_NAMES))
    )
    start_otel = Mock()
    start_registry = Mock()
    mcp_start = AsyncMock()
    scheduler_start = AsyncMock()
    has_tasks = AsyncMock(return_value=True)
    validate_dir = Mock(return_value=True)
    monkeypatch.setattr(app_module, "start_otel_retention", start_otel)
    monkeypatch.setattr(app_module, "start_model_registry_refresh", start_registry)
    monkeypatch.setattr(app_module.mcp_manager, "start", mcp_start)
    monkeypatch.setattr(app_module.task_scheduler, "start", scheduler_start)
    monkeypatch.setattr(app_module.task_scheduler, "has_enabled_tasks", has_tasks)
    monkeypatch.setattr(app_module.team_manager, "validate_agents_dir", validate_dir)

    from app.conductor import conductor_service
    from app.plugin_platform.runtime import plugin_mcp_runtime
    from app.services import (
        coding_purge_service,
        scoped_memory,
        webbridge_artifact_service,
        webbridge_service,
    )

    plugin_start = AsyncMock()
    conductor_start = AsyncMock()
    purge = AsyncMock()
    backfill = AsyncMock()
    cleanup = AsyncMock()
    artifact_cleanup = AsyncMock()
    monkeypatch.setattr(plugin_mcp_runtime, "start", plugin_start)
    monkeypatch.setattr(plugin_mcp_runtime, "stop", AsyncMock())
    monkeypatch.setattr(conductor_service, "start", conductor_start)
    monkeypatch.setattr(conductor_service, "stop", AsyncMock())
    monkeypatch.setattr(coding_purge_service, "purge_standalone_coding_sessions", purge)
    monkeypatch.setattr(scoped_memory, "backfill_extracted_note_projections", backfill)
    monkeypatch.setattr(
        webbridge_service.webbridge_manager, "run_cleanup_loop", cleanup
    )
    monkeypatch.setattr(
        webbridge_artifact_service, "run_artifact_cleanup_loop", artifact_cleanup
    )

    app = await _run_lifespan()

    start_otel.assert_not_called()
    start_registry.assert_not_called()
    mcp_start.assert_not_awaited()
    plugin_start.assert_not_awaited()
    conductor_start.assert_not_awaited()
    validate_dir.assert_not_called()
    purge.assert_not_awaited()
    has_tasks.assert_not_awaited()
    scheduler_start.assert_not_awaited()
    backfill.assert_not_awaited()
    app.state.dream_scheduler.start.assert_not_awaited()
    cleanup.assert_not_called()
    artifact_cleanup.assert_not_called()
    assert app.state.optional_services_ready is True


@pytest.mark.asyncio
async def test_disable_services_logs_each_disabled_service(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.setenv("EVOFLUX_DISABLE_SERVICES", "mcp,scheduler")
    monkeypatch.setattr(app_module, "start_otel_retention", Mock())
    monkeypatch.setattr(app_module, "start_model_registry_refresh", Mock())
    monkeypatch.setattr(app_module.mcp_manager, "start", AsyncMock())
    monkeypatch.setattr(app_module.task_scheduler, "start", AsyncMock())
    monkeypatch.setattr(
        app_module.team_manager, "validate_agents_dir", Mock(return_value=True)
    )
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="INFO")
    try:
        await _run_lifespan()
    finally:
        logger.remove(sink)
    joined = "\n".join(messages)
    assert "optional_service_disabled service=mcp" in joined
    assert "optional_service_disabled service=scheduler" in joined
    app_module.mcp_manager.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_unset_disable_services_still_starts_everything(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.delenv("EVOFLUX_DISABLE_SERVICES", raising=False)
    start_otel = Mock()
    mcp_start = AsyncMock()
    monkeypatch.setattr(app_module, "start_otel_retention", start_otel)
    monkeypatch.setattr(app_module, "start_model_registry_refresh", Mock())
    monkeypatch.setattr(app_module.mcp_manager, "start", mcp_start)
    monkeypatch.setattr(
        app_module.task_scheduler, "has_enabled_tasks", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        app_module.team_manager, "validate_agents_dir", Mock(return_value=True)
    )
    await _run_lifespan()
    start_otel.assert_called_once()
    mcp_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_disable_services_unknown_name_fails_startup(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.setenv("EVOFLUX_DISABLE_SERVICES", "scheduler,not_a_service")
    init = Mock()
    monkeypatch.setattr(app_module, "ensure_workspace_initialized", init)
    with pytest.raises(ValueError, match="not_a_service"):
        async with app_module.lifespan(FastAPI()):
            pass
    init.assert_not_called()


# ── EVOFLUX_REMOTE_PROXY_SECRET ─────────────────────────────────────────────

_SECRET_CODE = (
    "from app.core.desktop_auth import embedded_remote_proxy_secret as s; print(s())"
)


def _secret_in_child(**env: str) -> str:
    base = {k: v for k, v in os.environ.items() if k != "EVOFLUX_REMOTE_PROXY_SECRET"}
    base.update(env)
    return subprocess.run(
        [sys.executable, "-c", _SECRET_CODE],
        capture_output=True,
        text=True,
        check=True,
        env=base,
    ).stdout.strip()


def test_remote_proxy_secret_from_env() -> None:
    assert _secret_in_child(EVOFLUX_REMOTE_PROXY_SECRET="abc123fixed") == "abc123fixed"


def test_remote_proxy_secret_defaults_to_random() -> None:
    first, second = _secret_in_child(), _secret_in_child()
    assert len(first) == 64 and len(second) == 64
    assert first != second


def test_remote_proxy_secret_blank_env_falls_back_to_random() -> None:
    assert len(_secret_in_child(EVOFLUX_REMOTE_PROXY_SECRET="  ")) == 64
