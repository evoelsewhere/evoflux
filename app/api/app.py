"""FastAPI application factory."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.agent.mcp import mcp_manager
from app.api.routes.agents import router as agents_router
from app.api.routes.artifacts import router as artifacts_router
from app.api.routes.auth import router as auth_router
from app.api.routes.code_context import router as code_context_router
from app.api.routes.commands import router as commands_router
from app.api.routes.diagnostics import router as diagnostics_router
from app.api.routes.dream import router as dream_router
from app.api.routes.health import router as health_router
from app.api.routes.mcp import router as mcp_router
from app.api.routes.observability import router as observability_router
from app.api.routes.quote import router as quote_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.settings import router as settings_router
from app.api.routes.skills import router as skills_router
from app.api.routes.snippets import router as snippets_router
from app.api.routes.team import router as team_router
from app.api.routes.wiki import router as wiki_router
from app.api.routes.workflows import router as workflows_router
from app.core.config import settings
from app.core.desktop_auth import DesktopTokenMiddleware
from app.core.exception_handlers import EXCEPTION_HANDLERS
from app.core.metrics import HTTPMetricsMiddleware, metrics_endpoint
from app.core.middlewares import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.core.otel import setup_otel, shutdown_otel
from app.core.otel_retention import start_otel_retention, stop_otel_retention
from app.core.runtime_settings import load_runtime_settings
from app.core.schema_version import (
    ensure_database_revision_is_supported,
    inspect_database_schema,
)
from app.core.wiki_seed import seed_wiki
from app.core.workspace_init import ensure_workspace_initialized
from app.scheduler.scheduler import task_scheduler
from app.services import memory_stream_store as stream_store, team_manager
from app.services.dream_scheduler import DreamScheduler

from app.core.version import VERSION


def _log_startup_timing(
    phase: str, phase_started: float, process_started: float
) -> None:
    now = perf_counter()
    logger.info(
        "startup_timing phase={} duration_ms={} total_ms={}",
        phase,
        round((now - phase_started) * 1000),
        round((now - process_started) * 1000),
    )


async def _start_optional_services(app: FastAPI, process_started: float) -> None:
    """Start non-critical services after the HTTP server becomes available."""

    # Let Uvicorn finish lifespan startup, flip ``server.started``, and let the
    # desktop handshake escape before any synchronous config/file scanning.
    await asyncio.sleep(0.1)

    phase_started = perf_counter()
    try:
        start_otel_retention()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "optional_service_start_failed service=otel_retention error={}", exc
        )
    _log_startup_timing("otel_retention", phase_started, process_started)

    phase_started = perf_counter()
    try:
        # Start even with an absent/empty config: the manager owns the
        # mcp.json watcher that hot-activates servers created by EvoFlux
        # itself after startup.
        await mcp_manager.start()
    except Exception as exc:  # noqa: BLE001
        logger.error("optional_service_start_failed service=mcp error={}", exc)
    _log_startup_timing("mcp", phase_started, process_started)

    phase_started = perf_counter()
    try:
        if not team_manager.validate_agents_dir():
            logger.warning("agents_dir_empty_or_missing path={}", settings.AGENTS_DIR)
    except ValueError as exc:
        # Invalid agent files should not make the local HTTP API disappear.
        # Agent endpoints will surface the same configuration error when used.
        logger.error("agents_dir_invalid path={} error={}", settings.AGENTS_DIR, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "optional_service_start_failed service=agents_validation error={}", exc
        )
    _log_startup_timing("agents_validation", phase_started, process_started)

    phase_started = perf_counter()
    try:
        if await task_scheduler.has_enabled_tasks():
            await task_scheduler.start()
        else:
            logger.info("scheduler_no_enabled_tasks")
    except Exception as exc:  # noqa: BLE001
        logger.error("optional_service_start_failed service=scheduler error={}", exc)
    _log_startup_timing("scheduler", phase_started, process_started)

    phase_started = perf_counter()
    runtime_settings = app.state.runtime_settings
    try:
        if runtime_settings.dream.enabled:
            await app.state.dream_scheduler.start()
        else:
            logger.info("dream_scheduler_disabled enabled=false")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "optional_service_start_failed service=dream_scheduler error={}", exc
        )
    _log_startup_timing("dream_scheduler", phase_started, process_started)

    app.state.optional_services_ready = True
    logger.info(
        "optional_services_ready total_ms={}",
        round((perf_counter() - process_started) * 1000),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    process_started = perf_counter()
    logger.info("server_starting version={}", VERSION)

    phase_started = perf_counter()
    ensure_workspace_initialized()
    _log_startup_timing("workspace_init", phase_started, process_started)

    # ── Workflow runner ↔ team turn-boundary hooks (plan v5 §6.1) ─────────
    # Registered here rather than imported by team.py to avoid a circular
    # import between the team package and app.workflow.
    from app.agent.mode.team.team import set_workflow_hooks
    from app.workflow.runner import runner as workflow_runner

    set_workflow_hooks(
        workflow_runner.on_turn_boundary_capture,
        workflow_runner.on_turn_boundary_advance,
    )

    # Fail any execution left ``running``/``waiting_gate`` by a previous
    # process: the in-memory runner starts empty, so a paused gate from
    # before the restart is unanswerable and must not show as live.
    from app.workflow.runner import reconcile_orphaned_executions

    phase_started = perf_counter()
    await reconcile_orphaned_executions()
    _log_startup_timing("workflow_reconcile", phase_started, process_started)

    # ── Auto-migrate DB in production ───────────────────────────────
    if settings.APP_ENV == "production":
        # Alembic's ``env.py`` calls ``asyncio.run(run_migrations_online())``
        # which fails when invoked from inside uvicorn's running loop. Push
        # the sync call onto a worker thread so its private loop is isolated.
        from app.core.db import run_migrations

        phase_started = perf_counter()
        schema_status = await asyncio.to_thread(inspect_database_schema)
        ensure_database_revision_is_supported(schema_status)
        if schema_status.at_head:
            logger.info("auto_migrate_skipped reason=already_at_head")
        else:
            await asyncio.to_thread(run_migrations)
        _log_startup_timing("migrations", phase_started, process_started)

    # ── Seed wiki directory on first boot ──────────────────────────────
    phase_started = perf_counter()
    seed_wiki()
    _log_startup_timing("wiki_seed", phase_started, process_started)

    phase_started = perf_counter()
    setup_otel(service_name="EvoFlux")
    _log_startup_timing("otel", phase_started, process_started)

    # Construct optional services now so routes can reference them immediately,
    # but start their I/O-heavy work in the background after lifespan yields.
    runtime_settings = load_runtime_settings()
    from app.core.db import async_session_factory

    dream_scheduler = DreamScheduler(db_factory=async_session_factory)
    app.state.dream_scheduler = dream_scheduler
    app.state.runtime_settings = runtime_settings

    app.state.optional_services_ready = False

    # Start WebBridge extension cleanup task
    from app.services.webbridge_service import webbridge_manager

    webbridge_cleanup_task = asyncio.create_task(webbridge_manager.run_cleanup_loop())
    app.state.webbridge_cleanup_task = webbridge_cleanup_task
    from app.services.webbridge_artifact_service import run_artifact_cleanup_loop

    webbridge_artifact_cleanup_task = asyncio.create_task(run_artifact_cleanup_loop())
    app.state.webbridge_artifact_cleanup_task = webbridge_artifact_cleanup_task
    optional_startup_task = asyncio.create_task(
        _start_optional_services(app, process_started),
        name="optional-service-startup",
    )
    app.state.optional_startup_task = optional_startup_task
    # Give the optional task one scheduling turn. This starts cheap services
    # immediately while preserving the non-blocking startup boundary for any
    # service that performs real I/O.
    await asyncio.sleep(0)

    logger.info(
        "critical_startup_ready total_ms={}",
        round((perf_counter() - process_started) * 1000),
    )

    yield

    if not optional_startup_task.done():
        optional_startup_task.cancel()
    await asyncio.gather(optional_startup_task, return_exceptions=True)
    from app.services.code_index.project import repository_indexes

    repository_indexes.close_all()
    webbridge_cleanup_task = getattr(app.state, "webbridge_cleanup_task", None)
    if webbridge_cleanup_task:
        webbridge_cleanup_task.cancel()
    webbridge_artifact_cleanup_task = getattr(
        app.state, "webbridge_artifact_cleanup_task", None
    )
    if webbridge_artifact_cleanup_task:
        webbridge_artifact_cleanup_task.cancel()
    await dream_scheduler.stop()
    await task_scheduler.stop()
    await team_manager.stop()
    await mcp_manager.stop()

    # Command and Preview process groups would outlive the sidecar without
    # explicit shutdown. The in-app browser is owned by Tauri.
    from app.agent.tools.builtin.process import stop_all_processes
    from app.agent.tools.builtin.preview import stop_all_servers
    from app.agent.lsp_manager import close_language_servers

    await stop_all_processes()
    await stop_all_servers()
    await close_language_servers()

    await stream_store.close()
    await stop_otel_retention()
    shutdown_otel()

    logger.info("server_shutdown")


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(
        title="EvoFlux",
        description="On-machine AI agents",
        version=VERSION,
        lifespan=lifespan,
        exception_handlers=EXCEPTION_HANDLERS,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    # Metrics first (outermost) so it wraps everything else and records the
    # true end-to-end latency, including CORS / size-limit rejects.
    app.add_middleware(HTTPMetricsMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    # Desktop token auth — no-op unless EVOFLUX_DESKTOP_TOKEN is set
    # (Tauri shell sets it; CLI/server users get the existing open behaviour).
    app.add_middleware(DesktopTokenMiddleware)
    # Security headers run *inside* CORS so CORS preflights still receive the
    # right `Access-Control-*` headers unobstructed.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── /metrics (Prometheus scrape target) ───────────────────────────────────
    # Deliberately un-prefixed (not under /api) to match Prometheus convention.
    app.add_route("/metrics", metrics_endpoint, methods=["GET"])

    # ── Routers (all under /api) ─────────────────────────────────────────────
    app.include_router(health_router, prefix="/api/health", tags=["health"])
    app.include_router(team_router, prefix="/api/team", tags=["team"])
    app.include_router(quote_router, prefix="/api/quote", tags=["quote"])
    app.include_router(wiki_router, prefix="/api/wiki", tags=["wiki"])
    app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
    app.include_router(artifacts_router, prefix="/api/artifacts", tags=["artifacts"])
    app.include_router(skills_router, prefix="/api/skills", tags=["skills"])
    app.include_router(commands_router, prefix="/api/commands", tags=["commands"])
    app.include_router(workflows_router, prefix="/api/workflows", tags=["workflows"])
    app.include_router(
        code_context_router,
        prefix="/api/code-context",
        tags=["code-context"],
    )
    app.include_router(snippets_router, prefix="/api/snippets", tags=["snippets"])
    app.include_router(
        observability_router, prefix="/api/observability", tags=["observability"]
    )
    app.include_router(scheduler_router, prefix="/api/scheduler", tags=["scheduler"])
    app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
    app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(dream_router, prefix="/api", tags=["dream"])
    app.include_router(
        diagnostics_router, prefix="/api/diagnostics", tags=["diagnostics"]
    )

    logger.debug("api_only_app_ready")

    return app
