"""Session-authorized endpoint for bounded motion-review frame samples."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import ReadDbSession
from app.models.chat import ChatSession
from app.services.motion_review_service import (
    MotionReviewSampleUpload,
    MotionReviewServiceError,
    submit_motion_samples,
)

router = APIRouter()
MAX_MOTION_REVIEW_BODY_BYTES = 3_450_000
_JOB_ID_RE = re.compile(r"^motion-[a-f0-9]{32}$")


class MotionReviewHttpSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=64)
    frame_index: int = Field(ge=0, le=10_000_000)
    timestamp_ms: int = Field(ge=0, le=120_000)
    mime_type: Literal["image/jpeg", "image/webp"]
    image_base64: str = Field(min_length=1, max_length=273_068)


class MotionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_request_id: str = Field(min_length=1, max_length=120)
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    artifact_revision: int = Field(ge=1)
    samples: list[MotionReviewHttpSample] = Field(min_length=1, max_length=12)


@router.post("/{session_id}/motion-review/{job_id}")
async def post_motion_review_samples(
    session_id: UUID,
    job_id: str,
    request: Request,
    db: ReadDbSession,
) -> dict[str, int | bool]:
    if not _JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=422, detail="Invalid motion job id.")
    session = await db.get(ChatSession, session_id)
    if session is None or session.parent_session_id is not None:
        raise HTTPException(status_code=404, detail="Team session not found.")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid Content-Length."
            ) from exc
        if declared_length > MAX_MOTION_REVIEW_BODY_BYTES:
            raise HTTPException(
                status_code=413, detail="Motion review request is too large."
            )

    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_MOTION_REVIEW_BODY_BYTES:
            raise HTTPException(
                status_code=413, detail="Motion review request is too large."
            )
        chunks.append(chunk)
    try:
        body = MotionReviewRequest.model_validate_json(b"".join(chunks))
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_url=False)
        ) from exc

    try:
        await submit_motion_samples(
            str(session_id),
            job_id,
            body.sample_request_id,
            [
                MotionReviewSampleUpload(**sample.model_dump())
                for sample in body.samples
            ],
            artifact_id=body.artifact_id,
            artifact_revision=body.artifact_revision,
        )
    except MotionReviewServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"accepted": True, "sample_count": len(body.samples)}
