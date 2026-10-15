from __future__ import annotations

import asyncio

import pytest

from app.agent.schemas.events import MotionProgressEvent
from app.services.motion_review_service import (
    MotionReviewSampleUpload,
    MotionReviewServiceError,
    clear_motion_review_requests,
    pending_motion_review_count,
    submit_motion_samples,
    wait_for_motion_samples,
)


def jpeg(width: int = 1, height: int = 1, *, padding: int = 0) -> bytes:
    sof = (
        b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return (
        b"\xff\xd8"
        + sof
        + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x00\xff\xd9"
        + b"x" * padding
    )


def webp() -> bytes:
    payload = b"\x2f\x00\x00\x00\x00"  # VP8L lossless 1 x 1
    return (
        b"RIFF"
        + (17).to_bytes(4, "little")
        + b"WEBPVP8L"
        + len(payload).to_bytes(4, "little")
        + payload
    )


def event() -> MotionProgressEvent:
    return MotionProgressEvent(
        agent="lead",
        job_id="motion-" + "a" * 32,
        sequence=2,
        artifact_id="rainfall-story",
        artifact_revision=3,
        status="running",
        phase="reviewing",
        sample_request_id="request-1",
        selected_samples=[
            {
                "sample_id": "intake-hit",
                "beat_id": "intake",
                "frame_index": 42,
                "timestamp_ms": 1400,
                "role": "impact",
            }
        ],
    )


def upload(**overrides: object) -> MotionReviewSampleUpload:
    values = dict(
        sample_id="intake-hit",
        frame_index=42,
        timestamp_ms=1400,
        mime_type="image/jpeg",
        image_bytes=jpeg(),
    )
    values.update(overrides)
    return MotionReviewSampleUpload(**values)


def submit(
    session_id: str,
    job_id: str,
    request_id: str,
    samples: list[MotionReviewSampleUpload],
):
    return submit_motion_samples(
        session_id,
        job_id,
        request_id,
        samples,
        artifact_id="rainfall-story",
        artifact_revision=3,
    )


@pytest.fixture(autouse=True)
async def cleanup_requests():
    await clear_motion_review_requests()
    yield
    await clear_motion_review_requests()


@pytest.mark.asyncio
async def test_valid_submission_resolves_only_the_matching_pending_request() -> None:
    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)
    assert pending_motion_review_count() == 1

    await submit("session-1", event().job_id, "request-1", [upload()])
    received = await waiting
    assert received[0].sample_id == "intake-hit"
    assert received[0].beat_id == "intake"
    assert received[0].role == "impact"
    assert received[0].image_bytes == jpeg()
    assert pending_motion_review_count() == 0


@pytest.mark.asyncio
async def test_accepts_webp_dimensions_from_the_lossless_header() -> None:
    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)
    await submit(
        "session-1",
        event().job_id,
        "request-1",
        [upload(mime_type="image/webp", image_bytes=webp())],
    )
    received = await waiting
    assert received[0].mime_type == "image/webp"
    assert received[0].image_bytes == webp()


@pytest.mark.asyncio
async def test_rejects_wrong_session_job_revision_sample_and_mime() -> None:
    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)

    for session_id, job_id, request_id in (
        ("other-session", event().job_id, "request-1"),
        ("session-1", "motion-" + "b" * 32, "request-1"),
        ("session-1", event().job_id, "other-request"),
    ):
        with pytest.raises(MotionReviewServiceError):
            await submit(session_id, job_id, request_id, [upload()])

    with pytest.raises(MotionReviewServiceError, match="revision"):
        await submit_motion_samples(
            "session-1",
            event().job_id,
            "request-1",
            [upload()],
            artifact_id="rainfall-story",
            artifact_revision=4,
        )

    with pytest.raises(MotionReviewServiceError, match="sample"):
        await submit(
            "session-1", event().job_id, "request-1", [upload(sample_id="wrong")]
        )
    with pytest.raises(MotionReviewServiceError, match="mime"):
        await submit(
            "session-1", event().job_id, "request-1", [upload(mime_type="image/png")]
        )

    await submit("session-1", event().job_id, "request-1", [upload()])
    await waiting


@pytest.mark.asyncio
async def test_rejects_invalid_headers_oversize_and_dimensions() -> None:
    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)

    with pytest.raises(MotionReviewServiceError, match="image"):
        await submit(
            "session-1",
            event().job_id,
            "request-1",
            [upload(image_bytes=b"not an image")],
        )
    with pytest.raises(MotionReviewServiceError, match="200 KiB"):
        await submit(
            "session-1",
            event().job_id,
            "request-1",
            [upload(image_bytes=jpeg(padding=204_800))],
        )
    with pytest.raises(MotionReviewServiceError, match="640"):
        await submit(
            "session-1",
            event().job_id,
            "request-1",
            [upload(image_bytes=jpeg(width=641))],
        )
    with pytest.raises(MotionReviewServiceError, match="requested"):
        await submit("session-1", event().job_id, "request-1", [upload(), upload()])

    await submit("session-1", event().job_id, "request-1", [upload()])
    await waiting


@pytest.mark.asyncio
async def test_timeout_and_cancellation_remove_pending_future() -> None:
    with pytest.raises(TimeoutError):
        await wait_for_motion_samples("session-1", event(), timeout_seconds=0.01)
    assert pending_motion_review_count() == 0

    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert pending_motion_review_count() == 0


@pytest.mark.asyncio
async def test_duplicate_submission_is_rejected_after_resolution() -> None:
    waiting = asyncio.create_task(
        wait_for_motion_samples("session-1", event(), timeout_seconds=1)
    )
    await asyncio.sleep(0)
    await submit("session-1", event().job_id, "request-1", [upload()])
    await waiting
    with pytest.raises(MotionReviewServiceError, match="pending"):
        await submit("session-1", event().job_id, "request-1", [upload()])
