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
                "print('app.services.code_graph.indexer' in sys.modules)"
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
        code_graph=SimpleNamespace(watch_enabled=False),
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
                code_graph=SimpleNamespace(watch_enabled=False),
            )
        ),
    )

    await _run_lifespan()

    app_module.mcp_manager.start.assert_awaited_once()
    app_module.task_scheduler.start.assert_awaited_once()
    slim_lifespan.start.assert_awaited_once()
