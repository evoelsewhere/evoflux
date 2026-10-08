"""Local lifecycle and event ingestion endpoints for skill recordings."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.api.schemas.skill_recordings import (
    SkillRecordingCreated,
    SkillRecordingDeleteResponse,
    SkillRecordingDraftRequest,
    SkillRecordingEventBatch,
    SkillRecordingArtifactUploaded,
    SkillRecordingPreviewRequest,
)
from app.services import skill_recording_service as service
from app.services import skill_distillation_service as distillation

router = APIRouter()


def _raise_http(exc: service.SkillRecordingError) -> NoReturn:
    if isinstance(exc, service.SkillRecordingNotFoundError):
        status = 404
    elif isinstance(exc, service.SkillRecordingConflictError):
        status = 409
    elif isinstance(exc, service.SkillRecordingValidationError):
        status = 422
    elif isinstance(exc, service.SkillRecordingPathError):
        status = 400
    else:
        status = 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _raise_distillation_http(exc: distillation.SkillDistillationError) -> NoReturn:
    if isinstance(exc, distillation.SkillDistillationValidationError):
        status = 422
    elif isinstance(exc, distillation.SkillDistillationTimeoutError):
        status = 504
    elif isinstance(exc, distillation.SkillDistillationProviderError):
        status = 502
    else:
        status = 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("", status_code=201, response_model=SkillRecordingCreated)
async def create_recording() -> dict:
    return service.create_session()


@router.post("/{recording_id}/events")
async def append_events(recording_id: str, body: SkillRecordingEventBatch) -> dict:
    try:
        events = [event.model_dump(mode="json") for event in body.events]
        return service.append_events(recording_id, events)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.post("/{recording_id}/pause")
async def pause_recording(recording_id: str) -> dict:
    try:
        return service.pause_session(recording_id)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.post("/{recording_id}/resume")
async def resume_recording(recording_id: str) -> dict:
    try:
        return service.resume_session(recording_id)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.post("/{recording_id}/stop")
async def stop_recording(recording_id: str) -> dict:
    try:
        return service.stop_session(recording_id)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.put(
    "/{recording_id}/video",
    status_code=201,
    response_model=SkillRecordingArtifactUploaded,
)
async def upload_video(recording_id: str, request: Request) -> dict:
    content_type = (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type != "video/webm":
        raise HTTPException(
            status_code=415, detail="Only video/webm artifacts are supported."
        )
    try:
        return await service.store_video(recording_id, request.stream())
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.get("/{recording_id}/video")
async def read_video(recording_id: str) -> FileResponse:
    try:
        path = service.video_path(recording_id)
        return FileResponse(
            path,
            media_type="video/webm",
            headers={"Cache-Control": "no-store"},
        )
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.post("/{recording_id}/draft")
async def create_draft(recording_id: str, body: SkillRecordingDraftRequest) -> dict:
    try:
        return await distillation.create_skill_draft(
            recording_id,
            confirm_processing=body.confirm_processing,
            selected_event_ids=body.selected_event_ids,
            redactions=body.redactions,
            preview_sha256=body.preview_sha256,
            model=body.model,
            goal=body.goal,
        )
    except distillation.SkillDistillationError as exc:
        _raise_distillation_http(exc)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.post("/{recording_id}/preview")
async def preview_draft(recording_id: str, body: SkillRecordingPreviewRequest) -> dict:
    try:
        return distillation.preview_payload(
            recording_id,
            selected_event_ids=body.selected_event_ids,
            redactions=body.redactions,
            goal=body.goal,
            model=body.model,
        )
    except distillation.SkillDistillationError as exc:
        _raise_distillation_http(exc)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.get("/{recording_id}")
async def get_recording(recording_id: str) -> dict:
    try:
        return service.get_session(recording_id)
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.get("/{recording_id}/screenshots/{sequence}")
async def get_screenshot(recording_id: str, sequence: int) -> Response:
    try:
        content = service.read_screenshot(recording_id, sequence)
        return Response(
            content, media_type="image/png", headers={"Cache-Control": "no-store"}
        )
    except service.SkillRecordingError as exc:
        _raise_http(exc)


@router.delete("/{recording_id}", response_model=SkillRecordingDeleteResponse)
async def delete_recording(recording_id: str) -> SkillRecordingDeleteResponse:
    try:
        service.delete_session(recording_id)
    except service.SkillRecordingError as exc:
        _raise_http(exc)
    return SkillRecordingDeleteResponse(id=recording_id)
