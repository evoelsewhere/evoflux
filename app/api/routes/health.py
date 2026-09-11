"""Health probes.

Three endpoints:

- ``GET /api/health/live``         → always 200 if the process is up.
- ``GET /api/health/ready``        → 200 only when DB + team are ready; 503 otherwise.
- ``GET /api/health/diagnostics``  → active check of every subsystem with
                                     per-check status + actionable hints.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.core.version import VERSION
from app.services import team_manager

router = APIRouter()

# ``validate_agents_dir`` globs + parses every agent .md (and may write
# blueprint files). Health/diagnostics endpoints are polled, so run it off
# the loop and cache the outcome — including a ValueError — briefly.
_VALIDATE_AGENTS_TTL_S = 30.0
_validate_agents_cache: tuple[float, bool | ValueError] | None = None


async def validate_agents_dir_cached() -> bool:
    """Off-loop, briefly-cached wrapper around ``team_manager.validate_agents_dir``."""
    global _validate_agents_cache
    now = time.monotonic()
    cached = _validate_agents_cache
    if cached is not None and now - cached[0] < _VALIDATE_AGENTS_TTL_S:
        outcome = cached[1]
        if isinstance(outcome, ValueError):
            raise outcome
        return outcome
    try:
        result = await asyncio.to_thread(team_manager.validate_agents_dir)
    except ValueError as exc:
        _validate_agents_cache = (now, exc)
        raise
    _validate_agents_cache = (now, result)
    return result


@router.get("/live")
async def health_live() -> dict:
    """Liveness probe — returns 200 as long as the event loop is alive.

    Never touches the DB; safe for high-frequency orchestrator polling.
    """
    return {"status": "ok", "version": VERSION}


async def _check_ready(session: AsyncSession) -> dict:
    checks: dict[str, str] = {}

    # ── DB ────────────────────────────────────────────────────────────────
    # ``session.exec`` overloads only cover Select/UpdateBase, so a raw
    # ``text(...)`` SELECT 1 ping doesn't match — works at runtime via the
    # SQLAlchemy passthrough but the type checker can't see it.
    try:
        await session.exec(text("SELECT 1"))  # ty: ignore[no-matching-overload]
        checks["db"] = "ok"
    except SQLAlchemyError as exc:
        logger.warning("health_ready_db_failed error={}", exc)
        checks["db"] = "fail"

    # ── Team ──────────────────────────────────────────────────────────────
    # Teams build lazily on first use, so an in-memory team is not a useful
    # readiness signal.  Report on whether the agents directory is loadable
    # (parses + has a lead) instead.
    try:
        checks["team"] = "ok" if await validate_agents_dir_cached() else "missing"
    except ValueError as exc:
        logger.warning("health_ready_team_invalid error={}", exc)
        checks["team"] = "invalid"

    ready = checks["db"] == "ok"  # team "missing" is tolerable (empty agents dir)
    return {
        "status": "ok" if ready else "degraded",
        "version": VERSION,
        "checks": checks,
    }


@router.get("/ready")
async def health_ready(session: AsyncSession = Depends(get_session)) -> dict:
    """Readiness probe — 200 when dependencies are healthy, 503 otherwise."""
    result = await _check_ready(session)
    if result["status"] != "ok":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=result,
        )
    return result


# ---------------------------------------------------------------------------
# /api/health/diagnostics — active subsystem checks with hints
# ---------------------------------------------------------------------------

# Provider keys worth surfacing to the user (label → settings field name).
_PROVIDER_KEY_FIELDS: dict[str, str] = {
    "Anthropic": "ANTHROPIC_API_KEY",
    "Google AI Studio": "GOOGLE_API_KEY",
    "Vertex AI": "VERTEXAI_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
    "xAI": "XAI_API_KEY",
    "NVIDIA": "NVIDIA_API_KEY",
    "DeepSeek": "DEEPSEEK_API_KEY",
    "Moonshot": "MOONSHOT_API_KEY",
    "zAI": "ZAI_API_KEY",
}

# Local-inference providers that don't need a secret key.
_LOCAL_PROVIDER_FIELDS: dict[str, str] = {
    "Ollama": "OLLAMA_BASE_URL",
}


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, SecretStr):
        return bool(value.get_secret_value().strip())
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


#: ``PRAGMA auto_vacuum`` values. A database created before the incremental
#: pragma reports NONE and only a full VACUUM can move it, which is the one
#: case where reclaiming rewrites the file instead of trimming its free list.
_AUTO_VACUUM_NONE = 0
_AUTO_VACUUM_INCREMENTAL = 2

_DB_RECLAIM_HINT = {
    "incremental": (
        "Free pages are reclaimed a little at a time on startup. "
        "Reclaim them now to finish in one pass."
    ),
    "full": (
        "This database predates incremental reclamation, so freeing the pages "
        "rewrites the file once. It runs as a single atomic step — an "
        "interrupted rewrite leaves the original untouched — but it needs "
        "free disk space roughly the size of the database, and writes wait "
        "while it runs."
    ),
}


def _db_reclaim_action(auto_vacuum: int, reclaimable_mib: float) -> dict[str, Any]:
    """The button the Diagnostics row offers for a bloated database."""

    full = auto_vacuum != _AUTO_VACUUM_INCREMENTAL
    return {
        "id": "db_reclaim",
        "label": "Reclaim space",
        "running_label": "Reclaiming…",
        "confirm_title": "Reclaim database space?",
        "confirm_body": (
            (
                "EvoFlux rewrites the database once to release "
                f"{reclaimable_mib:.0f} MiB and switches it to incremental "
                "reclamation, so this is a one-off. Writes wait until it "
                "finishes; no data is changed."
            )
            if full
            else (
                f"EvoFlux releases the {reclaimable_mib:.0f} MiB of free pages "
                "back to the filesystem. No data is changed."
            )
        ),
        "confirm_label": "Reclaim",
    }


def _check(
    id: str,  # noqa: A002
    label: str,
    status_val: str,
    detail: str,
    hint: str | None = None,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "status": status_val,
        "detail": detail,
        "hint": hint,
        "action": action,
    }


@router.get("/diagnostics")
async def health_diagnostics(session: AsyncSession = Depends(get_session)) -> dict:
    """Active health check across all EvoFlux subsystems.

    Each check in the returned ``checks`` list has:

    - ``id``     — machine-readable identifier
    - ``label``  — human-readable name shown in the UI
    - ``status`` — ``"ok"`` | ``"warn"`` | ``"fail"``
    - ``detail`` — one-line explanation of the current state
    - ``hint``   — actionable fix suggestion, or ``null``
    """
    checks: list[dict[str, Any]] = []

    # ── 1. Database ──────────────────────────────────────────────────────────
    try:
        await session.exec(text("SELECT 1"))  # ty: ignore[no-matching-overload]
        checks.append(_check("db", "Database", "ok", "Connected and responding"))
        if session.get_bind().dialect.name == "sqlite":
            page_count = int(
                (await session.exec(text("PRAGMA page_count"))).one()[0]  # ty: ignore[no-matching-overload]
            )
            free_pages = int(
                (await session.exec(text("PRAGMA freelist_count"))).one()[0]  # ty: ignore[no-matching-overload]
            )
            page_size = int(
                (await session.exec(text("PRAGMA page_size"))).one()[0]  # ty: ignore[no-matching-overload]
            )
            free_ratio = free_pages / page_count if page_count else 0
            reclaimable_mib = free_pages * page_size / (1024 * 1024)
            auto_vacuum = int(
                (await session.exec(text("PRAGMA auto_vacuum"))).one()[0]  # ty: ignore[no-matching-overload]
            )
            needs_reclaim = free_ratio >= 0.3
            checks.append(
                _check(
                    "db_storage",
                    "Database storage",
                    "warn" if needs_reclaim else "ok",
                    (
                        f"{free_ratio:.0%} free pages; "
                        f"{reclaimable_mib:.1f} MiB reclaimable"
                    ),
                    hint=(
                        _DB_RECLAIM_HINT[
                            "incremental"
                            if auto_vacuum == _AUTO_VACUUM_INCREMENTAL
                            else "full"
                        ]
                        if needs_reclaim
                        else None
                    ),
                    action=(
                        _db_reclaim_action(auto_vacuum, reclaimable_mib)
                        if needs_reclaim
                        else None
                    ),
                )
            )
    except SQLAlchemyError as exc:
        logger.warning("diagnostics_db_failed error={}", exc)
        checks.append(
            _check(
                "db",
                "Database",
                "fail",
                f"Query failed: {exc}",
                hint="Check that the data directory is writable and not full.",
            )
        )

    # ── 2. Providers ─────────────────────────────────────────────────────────
    configured = [
        label
        for label, field in _PROVIDER_KEY_FIELDS.items()
        if _truthy(getattr(settings, field, None))
    ]
    # Ollama is available if its base URL is reachable (we just check if set/default)
    ollama_url = getattr(settings, "OLLAMA_BASE_URL", "")
    has_local = bool(ollama_url)

    if configured:
        checks.append(
            _check(
                "providers",
                "Providers",
                "ok",
                f"{len(configured)} key(s) configured: {', '.join(configured)}",
            )
        )
    elif has_local:
        checks.append(
            _check(
                "providers",
                "Providers",
                "ok",
                "Local inference (Ollama) configured",
            )
        )
    else:
        checks.append(
            _check(
                "providers",
                "Providers",
                "warn",
                "No provider API keys configured",
                hint="Add a provider key in Settings → Providers.",
            )
        )

    # ── 3. Team / agents ─────────────────────────────────────────────────────
    try:
        agents_ok = await validate_agents_dir_cached()
        if agents_ok:
            checks.append(_check("team", "Agents", "ok", "Agents directory is valid"))
        else:
            checks.append(
                _check(
                    "team",
                    "Agents",
                    "warn",
                    "Agents directory is empty or missing",
                    hint="Run 'evoflux init' or add agent files to the config directory.",
                )
            )
    except ValueError as exc:
        checks.append(
            _check(
                "team",
                "Agents",
                "fail",
                f"Agent config invalid: {exc}",
                hint="Open Settings → Agents and fix the YAML frontmatter errors.",
            )
        )

    # ── 4. MCP servers ───────────────────────────────────────────────────────
    try:
        from app.agent.mcp import mcp_manager

        statuses = mcp_manager.list_status()
        if not statuses:
            checks.append(
                _check("mcp", "MCP Servers", "ok", "No MCP servers configured")
            )
        else:
            errored = [s for s in statuses if s.state == "error"]
            ready = [s for s in statuses if s.state == "ready"]
            if errored:
                names = ", ".join(s.name for s in errored)
                checks.append(
                    _check(
                        "mcp",
                        "MCP Servers",
                        "warn",
                        f"{len(ready)}/{len(statuses)} ready — errored: {names}",
                        hint="Open Settings → MCP Servers and check the server command / env.",
                    )
                )
            else:
                checks.append(
                    _check(
                        "mcp",
                        "MCP Servers",
                        "ok",
                        f"{len(ready)}/{len(statuses)} server(s) ready",
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostics_mcp_failed error={}", exc)
        checks.append(
            _check("mcp", "MCP Servers", "warn", f"Could not read MCP status: {exc}")
        )

    # ── 5. Disk space ────────────────────────────────────────────────────────
    _WARN_BYTES = 500 * 1024 * 1024  # 500 MB
    _FAIL_BYTES = 100 * 1024 * 1024  # 100 MB
    try:
        data_dir = Path(settings.EVOFLUX_DATA_DIR)
        usage = shutil.disk_usage(data_dir if data_dir.exists() else Path.home())
        free_mb = usage.free // (1024 * 1024)
        detail = f"{free_mb:,} MB free on data volume"
        if usage.free < _FAIL_BYTES:
            checks.append(
                _check(
                    "disk",
                    "Disk Space",
                    "fail",
                    detail,
                    hint="Free up disk space — EvoFlux needs at least 100 MB to operate.",
                )
            )
        elif usage.free < _WARN_BYTES:
            checks.append(
                _check(
                    "disk",
                    "Disk Space",
                    "warn",
                    detail,
                    hint="Disk space is low. Consider cleaning old sessions or artifacts.",
                )
            )
        else:
            checks.append(_check("disk", "Disk Space", "ok", detail))
    except OSError as exc:
        checks.append(
            _check("disk", "Disk Space", "warn", f"Could not read disk usage: {exc}")
        )

    # ── 6. Code context ──────────────────────────────────────────────────────
    try:
        cache_root = Path(settings.EVOFLUX_CACHE_DIR) / "code-index"
        has_index = any(cache_root.glob("*/code-context.sqlite3"))
        if has_index:
            checks.append(
                _check(
                    "code_context",
                    "Code Context",
                    "ok",
                    "At least one repository index is cached",
                )
            )
        else:
            checks.append(
                _check(
                    "code_context",
                    "Code Context",
                    "warn",
                    "No repositories indexed yet",
                    hint="Run a code-context query from a coding workspace.",
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostics_code_context_failed error={}", exc)
        checks.append(
            _check(
                "code_context",
                "Code Context",
                "warn",
                f"Could not inspect the code-context cache: {exc}",
            )
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    statuses_list = [c["status"] for c in checks]
    if "fail" in statuses_list:
        summary = "fail"
    elif "warn" in statuses_list:
        summary = "warn"
    else:
        summary = "ok"

    return {"checks": checks, "summary": summary}


@router.post("/diagnostics/actions/db_reclaim")
async def diagnostics_db_reclaim() -> dict[str, Any]:
    """Release SQLite's free pages back to the filesystem.

    Two shapes, chosen by what the database already supports:

    - ``auto_vacuum=INCREMENTAL`` — ``PRAGMA incremental_vacuum`` trims the
      free list in place. No rewrite, no extra disk, no long lock.
    - ``auto_vacuum=NONE`` — a database from before that pragma. Setting the
      pragma only takes effect through a full ``VACUUM``, so we do both once
      and every later reclaim takes the cheap path. VACUUM is atomic: an
      interrupted run leaves the original file intact.

    Refused while an agent is working, because the rewrite holds a write lock
    for its whole duration and a turn mid-flight would stall on it.
    """
    from app.core.db import _is_sqlite, engine, incremental_vacuum

    if not _is_sqlite:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Space reclamation only applies to SQLite databases.",
        )
    if team_manager.has_active_team_turn():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                "An agent is working. Wait for the turn to finish, then "
                "reclaim space."
            ),
        )

    started = time.monotonic()
    async with engine.begin() as connection:
        page_size = int(
            (await connection.exec_driver_sql("PRAGMA page_size")).scalar_one()
        )
        before_free = int(
            (await connection.exec_driver_sql("PRAGMA freelist_count")).scalar_one()
        )
        auto_vacuum = int(
            (await connection.exec_driver_sql("PRAGMA auto_vacuum")).scalar_one()
        )

    full = auto_vacuum != _AUTO_VACUUM_INCREMENTAL
    if full:
        db_path = Path(str(engine.url.database or ""))
        db_bytes = db_path.stat().st_size if db_path.is_file() else 0
        free_bytes = shutil.disk_usage(db_path.parent).free if db_bytes else 0
        # VACUUM builds the new file beside the old one before swapping.
        if db_bytes and free_bytes < db_bytes * 1.2:
            raise HTTPException(
                status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=(
                    "Rewriting the database needs about "
                    f"{db_bytes / (1024 * 1024):.0f} MiB of free disk space; "
                    f"only {free_bytes / (1024 * 1024):.0f} MiB is available."
                ),
            )

    try:
        # VACUUM cannot run inside a transaction, and neither statement should
        # be wrapped in one — AUTOCOMMIT keeps SQLAlchemy from opening it.
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            if full:
                await autocommit.exec_driver_sql("PRAGMA auto_vacuum=INCREMENTAL")
                await autocommit.exec_driver_sql("VACUUM")
            else:
                await incremental_vacuum(autocommit)
            after_free = int(
                (await autocommit.exec_driver_sql("PRAGMA freelist_count")).scalar_one()
            )
    except SQLAlchemyError as exc:
        logger.warning("diagnostics_db_reclaim_failed full={} error={}", full, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not reclaim space: {exc}",
        ) from exc

    reclaimed_mib = max(0, before_free - after_free) * page_size / (1024 * 1024)
    elapsed_s = time.monotonic() - started
    logger.info(
        "diagnostics_db_reclaim_done full={} reclaimed_mib={:.1f} elapsed_s={:.1f}",
        full,
        reclaimed_mib,
        elapsed_s,
    )
    return {
        "reclaimed_mib": round(reclaimed_mib, 1),
        "elapsed_s": round(elapsed_s, 1),
        "rewrote_database": full,
        "message": (
            f"Reclaimed {reclaimed_mib:.0f} MiB"
            if reclaimed_mib >= 1
            else "Nothing left to reclaim"
        ),
    }
