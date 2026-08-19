from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.search_everywhere import (
    SearchEverywhereItemResponse,
    SearchEverywhereRequest,
    SearchEverywhereResponse,
)
from app.services import team_manager
from app.services.search_everywhere_service import search_everywhere

router = APIRouter(prefix="/workspace/search-everywhere")


@router.post("", response_model=SearchEverywhereResponse)
async def search_everywhere_route(
    workspace: str, body: SearchEverywhereRequest
) -> SearchEverywhereResponse:
    try:
        root = Path(team_manager.validate_workspace(workspace)).resolve()
        items = await search_everywhere(root, body.query, limit=body.limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SearchEverywhereResponse(
        items=[
            SearchEverywhereItemResponse.model_validate(asdict(item)) for item in items
        ]
    )
