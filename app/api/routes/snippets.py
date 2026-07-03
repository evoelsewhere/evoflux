"""Prompt-snippet discovery and rendering for the coding composer."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.snippets import (
    SnippetListResponse,
    SnippetRenderResponse,
    SnippetSummary,
)
from app.services.snippets import discover_snippets

router = APIRouter()


def _workspace_path(workspace: str | None) -> Path:
    if workspace is None:
        raise HTTPException(status_code=422, detail="Snippet workspace is required.")
    path = Path(workspace).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"Workspace does not exist or is not a directory: {path}",
        )
    return path


@router.get("")
async def list_snippets(
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> SnippetListResponse:
    workspace_path = _workspace_path(workspace)
    snippets = await asyncio.to_thread(discover_snippets, workspace_path)
    rows = [
        SnippetSummary(name=item.name, description=item.description, source=item.source)
        for item in snippets.values()
    ]
    rows.sort(key=lambda r: r.name)
    return SnippetListResponse(snippets=rows)


@router.post("/{name:path}/render")
async def render_snippet(
    name: str,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> SnippetRenderResponse:
    workspace_path = _workspace_path(workspace)
    snippets = await asyncio.to_thread(discover_snippets, workspace_path)
    snippet = snippets.get(name)
    if snippet is None:
        raise HTTPException(status_code=404, detail=f"Snippet '{name}' not found.")
    return SnippetRenderResponse(name=snippet.name, content=snippet.body)
