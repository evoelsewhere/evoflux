from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.language_servers import (
    LanguageServerOverviewResponse,
    LanguageServerStatusRequest,
    LanguageServerStatusResponse,
)
from app.services import team_manager
from app.services.language_server_service import (
    LanguageServerInstallError,
    install_language_server,
    language_server_overview,
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


@router.post("/{language_id}/install", response_model=LanguageServerStatusResponse)
async def install_language_server_route(
    language_id: str,
) -> LanguageServerStatusResponse:
    try:
        status = await install_language_server(language_id)
    except LanguageServerInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LanguageServerStatusResponse.model_validate(asdict(status))
