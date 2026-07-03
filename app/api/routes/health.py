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


def _check(
    id: str,  # noqa: A002
    label: str,
    status_val: str,
    detail: str,
    hint: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "status": status_val,
        "detail": detail,
        "hint": hint,
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

    # ── 6. Code graph ────────────────────────────────────────────────────────
    try:
        from sqlmodel import select as sql_select

        from app.models.code_graph import CodeIndexState

        result = await session.exec(  # ty: ignore[no-matching-overload]
            sql_select(CodeIndexState.workspace_id).limit(1)
        )
        has_index = result.first() is not None
        if has_index:
            checks.append(
                _check(
                    "code_graph", "Code Graph", "ok", "At least one workspace indexed"
                )
            )
        else:
            checks.append(
                _check(
                    "code_graph",
                    "Code Graph",
                    "warn",
                    "No workspaces indexed yet",
                    hint="Open a coding workspace and click 'Build index' in the Graph tab.",
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostics_code_graph_failed error={}", exc)
        checks.append(
            _check(
                "code_graph", "Code Graph", "warn", f"Could not query code graph: {exc}"
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
