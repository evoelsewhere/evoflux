"""Loop settings API routes.

Exposes runtime settings for the Loop Engine v2 at
``GET/PUT /api/loop/config``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.runtime_settings import load_runtime_settings, save_runtime_settings

router = APIRouter(tags=["loop"])


# ── Config schemas ────────────────────────────────────────────────────────────


class LoopConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_max_iterations: int
    default_evolve_prompt: bool
    default_verify_command: str
    default_max_total_tokens: int | None
    default_no_progress_threshold: int
    default_max_consecutive_errors: int
    default_delay_between_iterations: float


class LoopConfigWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_max_iterations: int
    default_evolve_prompt: bool
    default_verify_command: str = ""
    default_max_total_tokens: int | None = None
    default_no_progress_threshold: int
    default_max_consecutive_errors: int
    default_delay_between_iterations: float


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/loop/config", response_model=LoopConfigResponse)
async def get_loop_config() -> LoopConfigResponse:
    """Return Loop Engine runtime settings."""
    cfg = load_runtime_settings().loop
    return LoopConfigResponse(
        default_max_iterations=cfg.default_max_iterations,
        default_evolve_prompt=cfg.default_evolve_prompt,
        default_verify_command=cfg.default_verify_command or "",
        default_max_total_tokens=cfg.default_max_total_tokens,
        default_no_progress_threshold=cfg.default_no_progress_threshold,
        default_max_consecutive_errors=cfg.default_max_consecutive_errors,
        default_delay_between_iterations=cfg.default_delay_between_iterations,
    )


@router.put("/loop/config", response_model=LoopConfigResponse)
async def put_loop_config(body: LoopConfigWriteRequest) -> LoopConfigResponse:
    """Save Loop Engine runtime settings."""
    try:
        settings = load_runtime_settings()
        settings.loop.default_max_iterations = body.default_max_iterations
        settings.loop.default_evolve_prompt = body.default_evolve_prompt
        settings.loop.default_verify_command = body.default_verify_command.strip() or None
        settings.loop.default_max_total_tokens = body.default_max_total_tokens
        settings.loop.default_no_progress_threshold = body.default_no_progress_threshold
        settings.loop.default_max_consecutive_errors = body.default_max_consecutive_errors
        settings.loop.default_delay_between_iterations = body.default_delay_between_iterations
        save_runtime_settings(settings)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write settings.yaml: {exc}"
        ) from exc

    cfg = settings.loop
    return LoopConfigResponse(
        default_max_iterations=cfg.default_max_iterations,
        default_evolve_prompt=cfg.default_evolve_prompt,
        default_verify_command=cfg.default_verify_command or "",
        default_max_total_tokens=cfg.default_max_total_tokens,
        default_no_progress_threshold=cfg.default_no_progress_threshold,
        default_max_consecutive_errors=cfg.default_max_consecutive_errors,
        default_delay_between_iterations=cfg.default_delay_between_iterations,
    )
