"""Application-wide command-palette search — POST /team/search-app.

Repository search lives in :mod:`app.api.routes.team.search_everywhere` and is
scoped to one authorized workspace. This route covers everything the
application itself owns (sessions, dialogue, projects, workspaces, Memory,
scheduled tasks, agents, skills), so the palette can answer a query in Work
mode and before any workspace is chosen.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from app.api.deps import ReadDbSession
from app.api.schemas.app_search import (
    AppSearchItemResponse,
    AppSearchRequest,
    AppSearchResponse,
)
from app.services.app_search_service import search_app

router = APIRouter(prefix="/search-app")


@router.post("", response_model=AppSearchResponse)
async def search_app_route(
    db: ReadDbSession, body: AppSearchRequest
) -> AppSearchResponse:
    items = await search_app(db, body.query, limit=body.limit)
    return AppSearchResponse(
        items=[AppSearchItemResponse.model_validate(asdict(item)) for item in items]
    )
