"""Dream API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import async_session_factory, get_session
from app.core.runtime_settings import load_runtime_settings, save_runtime_settings
from app.services.dream import (
    get_manual_dream_run_status,
    run_dream_lint,
    start_manual_dream_run,
)

router = APIRouter(prefix="/dream", tags=["dream"])


# ── Config schemas ────────────────────────────────────────────────────────────


class DreamConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    model: str
    schedule: str


class DreamConfigWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    model: str = ""
    schedule: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/config", response_model=DreamConfigResponse)
async def get_dream_config() -> DreamConfigResponse:
    """Return Dream runtime settings."""
    cfg = load_runtime_settings().dream
    return DreamConfigResponse(
        enabled=cfg.enabled,
        model=cfg.model or "",
        schedule=cfg.schedule,
    )


@router.put("/config", response_model=DreamConfigResponse)
async def put_dream_config(
    body: DreamConfigWriteRequest,
    request: Request,
) -> DreamConfigResponse:
    """Save Dream runtime settings and reload the scheduler."""
    try:
        cfg = load_runtime_settings()
        cfg.dream.enabled = body.enabled
        cfg.dream.model = body.model.strip() or None
        cfg.dream.schedule = body.schedule.strip() or "0 2 * * *"
        save_runtime_settings(cfg)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write settings.yaml: {exc}"
        ) from exc

    # Reload the live scheduler so the new schedule / enabled flag takes
    # effect immediately — no server restart required.
    scheduler = getattr(request.app.state, "dream_scheduler", None)
    if scheduler is not None:
        await scheduler.reload()

    return DreamConfigResponse(
        enabled=cfg.dream.enabled,
        model=cfg.dream.model or "",
        schedule=cfg.dream.schedule,
    )


@router.post("/run")
async def run_dream_now() -> dict:
    """Kick off a manual dream drain in the background and return immediately.

    Uses ``drain=True`` internally so the run processes every pending item in
    one go, ignoring ``batch_size`` (which still bounds the scheduler's
    cron-driven fires). A drain can take minutes across a large backlog — one
    LLM call per item — so this no longer awaits completion inline; poll
    ``GET /dream/run/status`` for progress and the final result.
    """
    return start_manual_dream_run(async_session_factory)


@router.get("/run/status")
async def get_dream_run_status_now() -> dict:
    """Return the current/last manual dream run's progress.

    ``running`` reflects whether a manual drain kicked off via ``POST /run``
    is still in flight; ``result``/``error`` hold that run's outcome once it
    finishes (``None`` while still running or before any manual run has
    happened).
    """
    return get_manual_dream_run_status()


@router.post("/lint")
async def run_dream_lint_now(db: AsyncSession = Depends(get_session)) -> dict:
    """Run a dream-agent lint pass over the wiki.

    Produces ``wiki/LINT.md`` with contradictions, orphans, stale claims,
    etc.  Separate from ``POST /run`` — lint is read-only over the wiki
    except for the report file itself.
    """
    return await run_dream_lint(db)
