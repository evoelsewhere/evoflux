"""Dream API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.runtime_settings import load_runtime_settings, save_runtime_settings
from app.services.dream import run_dream, run_dream_lint

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
async def run_dream_now(db: AsyncSession = Depends(get_session)) -> dict:
    """Manually trigger the dream agent to process unprocessed sessions and notes.

    Uses ``drain=True`` so a manual click processes every pending item in one
    go, ignoring ``batch_size``.  ``batch_size`` still bounds the scheduler's
    cron-driven fires.
    """
    return await run_dream(db, drain=True)


@router.post("/lint")
async def run_dream_lint_now(db: AsyncSession = Depends(get_session)) -> dict:
    """Run a dream-agent lint pass over the wiki.

    Produces ``wiki/LINT.md`` with contradictions, orphans, stale claims,
    etc.  Separate from ``POST /run`` — lint is read-only over the wiki
    except for the report file itself.
    """
    return await run_dream_lint(db)
