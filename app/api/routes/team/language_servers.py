from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.language_servers import (
    LanguageServerInstallResponse,
    LanguageServerOverviewResponse,
    LanguageServerStatusRequest,
)
from app.services import team_manager
from app.services.language_server_service import (
    LanguageServerInstallError,
    dismiss_install_error,
    language_server_overview,
    start_language_server_install,
)

router = APIRouter(prefix="/workspace/language-servers")


def _validated_roots(raw_workspaces: list[str]) -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_workspaces:
        try:
            root = Path(team_manager.validate_workspace(raw)).resolve()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if root not in seen:
            seen.add(root)
            roots.append(root)
    return tuple(roots)


@router.post("/status", response_model=LanguageServerOverviewResponse)
async def language_server_status_route(
    body: LanguageServerStatusRequest,
) -> LanguageServerOverviewResponse:
    roots = _validated_roots(body.workspaces)
    overview = await asyncio.to_thread(language_server_overview, roots)
    return LanguageServerOverviewResponse.model_validate(asdict(overview))


@router.post("/{language_id}/install", response_model=LanguageServerInstallResponse)
async def install_language_server_route(
    language_id: str,
) -> LanguageServerInstallResponse:
    """Start an install and report its state; progress arrives via /status."""
    try:
        job = start_language_server_install(language_id)
    except LanguageServerInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LanguageServerInstallResponse.model_validate(asdict(job))


@router.post("/{language_id}/install/dismiss", status_code=204)
async def dismiss_install_error_route(language_id: str) -> None:
    """Drop a failed install so the row stops reporting it."""
    dismiss_install_error(language_id)
