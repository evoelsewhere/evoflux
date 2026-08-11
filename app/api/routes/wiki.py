"""Wiki HTTP API — tree view and single-file CRUD over the wiki store.

All routes operate on relative paths under ``{EVOFLUX_WIKI_DIR}/``.
Path validation happens inside :mod:`app.services.wiki`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.services.dream import get_unprocessed_notes
from app.services.wiki import (
    WikiFileInfo,
    WikiPathError,
    read_file,
    write_file,
    delete_file,
    list_tree,
)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class WikiFileInfoResponse(BaseModel):
    path: str
    description: str = ""
    updated: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: str | None = None
    sources: list[str] = Field(default_factory=list)


class WikiTreeResponse(BaseModel):
    """Memory/wiki tree grouped by root files and one-level subdirectories."""

    system: list[WikiFileInfoResponse]
    notes: list[WikiFileInfoResponse]
    topics: list[WikiFileInfoResponse]
    entities: list[WikiFileInfoResponse] = Field(default_factory=list)
    sources: list[WikiFileInfoResponse] = Field(default_factory=list)
    comparisons: list[WikiFileInfoResponse] = Field(default_factory=list)
    imports: list[WikiFileInfoResponse] = Field(default_factory=list)


class WikiFileResponse(BaseModel):
    path: str
    content: str
    description: str = ""
    updated: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: str | None = None
    sources: list[str] = Field(default_factory=list)


class WikiWriteRequest(BaseModel):
    path: str
    content: str


# ── Routes ───────────────────────────────────────────────────────────────────


def _info(i: WikiFileInfo) -> WikiFileInfoResponse:
    return WikiFileInfoResponse(
        path=i.path,
        description=i.description,
        updated=i.updated,
        tags=list(i.tags),
        confidence=i.confidence,
        sources=list(i.sources),
    )


@router.get("/tree", response_model=WikiTreeResponse)
async def get_wiki_tree(
    unprocessed_only: bool = Query(
        False,
        description="When true, notes/ is filtered to files not yet processed by the dream agent.",
    ),
    db: AsyncSession = Depends(get_session),
) -> WikiTreeResponse:
    """Return the full memory/wiki tree."""
    unprocessed: set[str] | None = None
    if unprocessed_only:
        unprocessed = set(await get_unprocessed_notes(db))

    tree = await asyncio.to_thread(list_tree, unprocessed_notes=unprocessed)
    return WikiTreeResponse(
        system=[_info(i) for i in tree.system],
        notes=[_info(i) for i in tree.notes],
        imports=[_info(i) for i in tree.imports],
        topics=[_info(i) for i in tree.topics],
        entities=[_info(i) for i in tree.entities],
        sources=[_info(i) for i in tree.sources],
        comparisons=[_info(i) for i in tree.comparisons],
    )


@router.get("/file", response_model=WikiFileResponse)
async def get_wiki_file(
    path: str = Query(description="Relative path under EVOFLUX_WIKI_DIR."),
) -> WikiFileResponse:
    """Return raw contents of a wiki file."""
    try:
        f = await asyncio.to_thread(read_file, path)
    except WikiPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WikiFileResponse(
        path=f.path,
        content=f.content,
        description=f.description,
        updated=f.updated,
        tags=list(f.tags),
        confidence=f.confidence,
        sources=list(f.sources),
    )


@router.put("/file", response_model=WikiFileResponse)
async def put_wiki_file(body: WikiWriteRequest) -> WikiFileResponse:
    """Create or overwrite a wiki file."""
    try:
        f = await asyncio.to_thread(write_file, body.path, body.content)
    except WikiPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WikiFileResponse(
        path=f.path,
        content=f.content,
        description=f.description,
        updated=f.updated,
        tags=list(f.tags),
        confidence=f.confidence,
        sources=list(f.sources),
    )


@router.delete("/file")
async def delete_wiki_file(
    path: str = Query(description="Relative path under EVOFLUX_WIKI_DIR."),
) -> dict[str, str]:
    """Delete a wiki file."""
    try:
        await asyncio.to_thread(delete_file, path)
    except WikiPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "path": path}
