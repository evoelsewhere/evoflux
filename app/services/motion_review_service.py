"""Bounded in-memory rendezvous for browser-rendered motion review frames."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas.events import MotionProgressEvent, MotionReviewSampleDescriptor

MAX_MOTION_REVIEW_SAMPLES = 12
MAX_MOTION_REVIEW_SAMPLE_BYTES = 200 * 1024
MAX_MOTION_REVIEW_TOTAL_BYTES = 2_516_582  # 2.4 MiB
MAX_MOTION_REVIEW_WIDTH = 640
MAX_MOTION_REVIEW_HEIGHT = 360
DEFAULT_MOTION_REVIEW_TIMEOUT_SECONDS = 20.0


class MotionReviewServiceError(ValueError):
    """A sample upload does not match a pending, bounded review request."""


class MotionReviewSampleUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(min_length=1, max_length=64)
    frame_index: int = Field(ge=0, le=10_000_000)
    timestamp_ms: int = Field(ge=0, le=120_000)
    mime_type: str = Field(min_length=1, max_length=40)
    image_base64: str | None = Field(default=None, max_length=273_068)
    image_bytes: bytes | None = None

    def decoded_bytes(self) -> bytes:
        if self.image_bytes is not None:
            return self.image_bytes
        if self.image_base64 is None:
            raise MotionReviewServiceError("sample image data is required")
        try:
            return base64.b64decode(self.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise MotionReviewServiceError("sample image base64 is invalid") from exc


class MotionReviewSample(MotionReviewSampleDescriptor):
    mime_type: str
    image_bytes: bytes


@dataclass
class _PendingRequest:
    session_id: str
    event: MotionProgressEvent
    future: asyncio.Future[list[MotionReviewSample]]


_pending: dict[tuple[str, str, str], _PendingRequest] = {}
_lock = asyncio.Lock()


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                return None
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += segment_length
    return None


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return (
            1 + int.from_bytes(data[24:27], "little"),
            1 + int.from_bytes(data[27:30], "little"),
        )
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
    return None


def _validate_image(mime_type: str, data: bytes) -> tuple[int, int]:
    if mime_type not in {"image/jpeg", "image/webp"}:
        raise MotionReviewServiceError(
            "sample mime type must be image/jpeg or image/webp"
        )
    if not data or len(data) > MAX_MOTION_REVIEW_SAMPLE_BYTES:
        raise MotionReviewServiceError("each sample must be at most 200 KiB")
    dimensions = (
        _jpeg_dimensions(data) if mime_type == "image/jpeg" else _webp_dimensions(data)
    )
    if dimensions is None:
        raise MotionReviewServiceError("sample image header is invalid or unsupported")
    width, height = dimensions
    if (
        width < 1
        or height < 1
        or width > MAX_MOTION_REVIEW_WIDTH
        or height > MAX_MOTION_REVIEW_HEIGHT
    ):
        raise MotionReviewServiceError(
            "sample image dimensions must be at most 640 x 360"
        )
    return dimensions


async def wait_for_motion_samples(
    session_id: str,
    event: MotionProgressEvent,
    timeout_seconds: float = DEFAULT_MOTION_REVIEW_TIMEOUT_SECONDS,
) -> list[MotionReviewSample]:
    if not event.sample_request_id:
        raise MotionReviewServiceError("motion sample request id is missing")
    key = (session_id, event.job_id, event.sample_request_id)
    loop = asyncio.get_running_loop()
    pending = _PendingRequest(session_id, event, loop.create_future())
    async with _lock:
        if key in _pending:
            raise MotionReviewServiceError("motion sample request is already pending")
        _pending[key] = pending
    try:
        return await asyncio.wait_for(
            pending.future, timeout=max(0.001, timeout_seconds)
        )
    finally:
        async with _lock:
            if _pending.get(key) is pending:
                _pending.pop(key, None)
        if not pending.future.done():
            pending.future.cancel()


async def submit_motion_samples(
    session_id: str,
    job_id: str,
    request_id: str,
    samples: list[MotionReviewSampleUpload],
    *,
    artifact_id: str,
    artifact_revision: int,
) -> None:
    key = (session_id, job_id, request_id)
    async with _lock:
        pending = _pending.get(key)
        if pending is None:
            raise MotionReviewServiceError("no matching pending motion review request")
        event = pending.event
        if (
            event.artifact_id != artifact_id
            or event.artifact_revision != artifact_revision
        ):
            raise MotionReviewServiceError(
                "sample artifact revision does not match the request"
            )
        expected = {sample.sample_id: sample for sample in event.selected_samples}
        if not 1 <= len(samples) <= MAX_MOTION_REVIEW_SAMPLES or len(samples) != len(
            expected
        ):
            raise MotionReviewServiceError(
                "sample count does not match the requested frames"
            )
        if len({sample.sample_id for sample in samples}) != len(samples):
            raise MotionReviewServiceError("sample ids must be unique")
        total_bytes = 0
        validated: list[MotionReviewSample] = []
        for sample in samples:
            descriptor = expected.get(sample.sample_id)
            if descriptor is None:
                raise MotionReviewServiceError("sample id was not requested")
            if (
                sample.frame_index != descriptor.frame_index
                or sample.timestamp_ms != descriptor.timestamp_ms
            ):
                raise MotionReviewServiceError(
                    "sample frame or timestamp does not match the request"
                )
            image_bytes = sample.decoded_bytes()
            _validate_image(sample.mime_type, image_bytes)
            total_bytes += len(image_bytes)
            if total_bytes > MAX_MOTION_REVIEW_TOTAL_BYTES:
                raise MotionReviewServiceError("review samples exceed 2.4 MiB total")
            validated.append(
                MotionReviewSample(
                    **descriptor.model_dump(),
                    mime_type=sample.mime_type,
                    image_bytes=image_bytes,
                )
            )
        pending.future.set_result(validated)


async def clear_motion_review_requests() -> None:
    async with _lock:
        pending = list(_pending.values())
        _pending.clear()
    for request in pending:
        if not request.future.done():
            request.future.cancel()


def pending_motion_review_count() -> int:
    return len(_pending)
