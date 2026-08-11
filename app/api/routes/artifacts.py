"""Format-neutral Artifact Fabric status and revision routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import FileResponse

from app.artifacts.domain import ArtifactFormat
from app.artifacts.service import get_artifact_service

router = APIRouter()


@router.get("/catalog")
async def artifact_catalog(
    format: ArtifactFormat | None = Query(default=None),
) -> dict:
    try:
        return get_artifact_service().catalog(format)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs")
async def list_artifact_jobs(
    session_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None, max_length=24),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    jobs = await get_artifact_service().list_jobs(
        session_id=session_id,
        status=status,
        limit=limit,
    )
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_artifact_job(job_id: UUID) -> dict:
    try:
        return await get_artifact_service().status(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/revisions/{revision_id}/content")
async def download_artifact_revision(revision_id: UUID) -> FileResponse:
    service = get_artifact_service()
    try:
        revision = await service.get_revision(revision_id)
        path = service.store.resolve_blob(revision.blob_key)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=revision.media_type,
        filename=revision.candidate_name,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/revisions/{revision_id}/previews/{preview_number}")
async def get_artifact_revision_preview(
    revision_id: UUID,
    preview_number: Annotated[int, Path(ge=1)],
) -> FileResponse:
    service = get_artifact_service()
    try:
        revision = await service.get_revision(revision_id)
        preview = revision.previews[preview_number - 1]
        path = service.store.resolve_preview(str(preview["key"]))
    except (KeyError, IndexError, FileNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=404, detail="Artifact preview not found."
        ) from exc
    return FileResponse(
        path,
        media_type=str(preview.get("media_type") or "image/png"),
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
