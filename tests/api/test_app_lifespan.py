from __future__ import annotations

from contextlib import asynccontextmanager
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from app.api import app as app_module


def test_app_import_keeps_optional_runtime_modules_lazy() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.api.app; "
                "print('app.agent.mcp.manager' in sys.modules); "
                "print('mcp.client' in sys.modules); "
                "print('app.agent.loader' in sys.modules); "
                "print('app.agent.agent_loop.core' in sys.modules); "
                "print('app.agent.tools.builtin.browser_use_tool' in sys.modules); "
                "print('app.agent.tools.builtin.webbridge_tool' in sys.modules); "
                "print('app.services.code_index.project' in sys.modules); "
                # AC-1: with no enabled connection, importing app.api.app
                # (which now registers the /api/remote routes) must never
                # pull either Telegram module into sys.modules.
                "print('app.remote.telegram.adapter' in sys.modules); "
                "print('app.remote.telegram.client' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout.splitlines() == [
        "False",
        "False",
        "False",
        "False",
        "False",
        "False",
        "True",
        "False",
        "False",
    ]


@asynccontextmanager
async def _noop_context():
    yield


async def _run_lifespan() -> FastAPI:
    app = FastAPI()
    async with app_module.lifespan(app):
        await app.state.optional_startup_task
    return app


@pytest.fixture
def slim_lifespan(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(app_module.settings, "APP_ENV", "test")
    monkeypatch.setattr(app_module, "ensure_workspace_initialized", Mock())
    monkeypatch.setattr(app_module, "seed_wiki", Mock())
    monkeypatch.setattr(app_module, "setup_otel", Mock())
    monkeypatch.setattr(app_module, "start_otel_retention", Mock())
    monkeypatch.setattr(app_module, "stop_otel_retention", AsyncMock())
    monkeypatch.setattr(app_module, "shutdown_otel", Mock())
    monkeypatch.setattr(app_module.stream_store, "close", AsyncMock())
    monkeypatch.setattr(
        app_module.team_manager, "validate_agents_dir", Mock(return_value=True)
    )
    monkeypatch.setattr(app_module.team_manager, "stop", AsyncMock())
    monkeypatch.setattr(app_module.task_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(app_module.mcp_manager, "stop", AsyncMock())

    dream_scheduler = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(
        app_module, "DreamScheduler", Mock(return_value=dream_scheduler)
    )
    # Mock runtime_settings referenced by lifespan
    rt_settings = SimpleNamespace(
        dream=SimpleNamespace(enabled=False),
    )
    monkeypatch.setattr(
        app_module, "load_runtime_settings", Mock(return_value=rt_settings)
    )
    return dream_scheduler


@pytest.mark.asyncio
async def test_lifespan_skips_idle_startup_services(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.setattr(app_module.mcp_manager, "start", AsyncMock())
    monkeypatch.setattr(
        app_module.task_scheduler, "has_enabled_tasks", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(app_module.task_scheduler, "start", AsyncMock())

    app = await _run_lifespan()

    # MCP owns a lightweight config watcher and must start even when the
    # initial file is empty so self-created servers hot-activate later.
    app_module.mcp_manager.start.assert_awaited_once()
    app_module.task_scheduler.start.assert_not_awaited()
    slim_lifespan.start.assert_not_awaited()
    assert app.state.dream_scheduler is slim_lifespan


@pytest.mark.asyncio
async def test_lifespan_starts_configured_services(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    monkeypatch.setattr(app_module.mcp_manager, "start", AsyncMock())
    monkeypatch.setattr(
        app_module.task_scheduler, "has_enabled_tasks", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(app_module.task_scheduler, "start", AsyncMock())
    monkeypatch.setattr(
        app_module,
        "load_runtime_settings",
        Mock(
            return_value=SimpleNamespace(
                dream=SimpleNamespace(enabled=True),
            )
        ),
    )

    await _run_lifespan()

    app_module.mcp_manager.start.assert_awaited_once()
    app_module.task_scheduler.start.assert_awaited_once()
    slim_lifespan.start.assert_awaited_once()


def _quiet_optional_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the other optional services so a remote-runtime test isn't
    coupled to their behavior."""
    monkeypatch.setattr(app_module.mcp_manager, "start", AsyncMock())
    monkeypatch.setattr(
        app_module.task_scheduler, "has_enabled_tasks", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(app_module.task_scheduler, "start", AsyncMock())


@pytest.mark.asyncio
async def test_lifespan_starts_remote_runtime(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    """The remote runtime is started alongside the other optional services
    (AC-1's lazy behavior itself is proven in tests/remote/test_runtime.py;
    this only proves the lifespan actually calls ``start()``)."""
    _quiet_optional_services(monkeypatch)
    from app.remote.runtime import remote_runtime

    start_mock = AsyncMock()
    monkeypatch.setattr(remote_runtime, "start", start_mock)

    app = await _run_lifespan()

    start_mock.assert_awaited_once()
    assert app.state.optional_services_ready is True


@pytest.mark.asyncio
async def test_lifespan_remote_runtime_start_failure_keeps_health_ready(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    """A remote-runtime startup failure must not fail app startup or health
    readiness — it is wrapped the same defensive way every other optional
    service is in ``_start_optional_services``."""
    _quiet_optional_services(monkeypatch)
    from app.remote.runtime import remote_runtime

    monkeypatch.setattr(
        remote_runtime, "start", AsyncMock(side_effect=RuntimeError("boom"))
    )

    app = await _run_lifespan()

    assert app.state.optional_services_ready is True


@pytest.mark.asyncio
async def test_lifespan_shutdown_stops_remote_runtime(
    monkeypatch: pytest.MonkeyPatch, slim_lifespan
) -> None:
    """``remote_runtime.stop()`` runs during shutdown — after the optional
    startup task has been awaited/cancelled — placed next to the existing
    Conductor/Scheduler cleanup calls."""
    _quiet_optional_services(monkeypatch)
    from app.remote.runtime import remote_runtime

    start_mock = AsyncMock()
    stop_mock = AsyncMock()
    monkeypatch.setattr(remote_runtime, "start", start_mock)
    monkeypatch.setattr(remote_runtime, "stop", stop_mock)

    app = FastAPI()
    async with app_module.lifespan(app):
        await app.state.optional_startup_task
        # Still "up": shutdown has not run yet, so stop() must not have
        # fired even though startup already completed.
        stop_mock.assert_not_awaited()

    start_mock.assert_awaited_once()
    stop_mock.assert_awaited_once()
