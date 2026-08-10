"""Artifact Fabric status, revision, and local WebView-render bridge routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.artifacts.domain import ArtifactFormat
from app.artifacts.service import get_artifact_service
from app.services.html_slide_render_service import get_html_slide_render_broker

router = APIRouter()


class HtmlSlideRenderResult(BaseModel):
    preview_png_base64: str = Field(min_length=1, max_length=56_000_000)
    shell_png_base64: str = Field(min_length=1, max_length=56_000_000)
    editable_elements: list[dict] = Field(default_factory=list, max_length=1000)
    issues: list[dict] = Field(default_factory=list, max_length=1000)


class HtmlSlideRenderFailure(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/renderers/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def heartbeat_html_slide_renderer(session_id: UUID) -> Response:
    await get_html_slide_render_broker().heartbeat(str(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/renderers/{session_id}/next", response_model=None)
async def claim_html_slide_render(session_id: UUID, response: Response) -> Response | dict:
    response.headers["Cache-Control"] = "no-store"
    value = await get_html_slide_render_broker().claim(str(session_id))
    if value is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return response
    return value


@router.post(
    "/renderers/{session_id}/requests/{request_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_html_slide_render(
    session_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderResult,
) -> Response:
    accepted = await get_html_slide_render_broker().complete(
        str(session_id), request_id, body.model_dump()
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/renderers/{session_id}/requests/{request_id}/fail",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def fail_html_slide_render(
    session_id: UUID,
    request_id: UUID,
    body: HtmlSlideRenderFailure,
) -> Response:
    accepted = await get_html_slide_render_broker().fail(
        str(session_id), request_id, body.message
    )
    if not accepted:
        raise HTTPException(status_code=404, detail="Slide render request not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/catalog")
async def artifact_catalog(
    format: ArtifactFormat | None = Query(default=None),
) -> dict:
    return get_artifact_service().catalog(format)


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
