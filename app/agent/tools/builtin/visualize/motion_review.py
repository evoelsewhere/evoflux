"""Let vision-capable agents inspect a bounded set of rendered motion frames."""

from __future__ import annotations

import asyncio
import base64
import secrets
from typing import Annotated, Any

from pydantic import Field, ValidationError

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.schemas.events import MotionReviewSampleDescriptor
from app.agent.tools import tool
from app.agent.tools.registry import InjectedArg
from app.agent.tools.builtin.visualize.motion_progress import (
    publish_motion_progress_update,
)
from app.services.motion_review_service import (
    DEFAULT_MOTION_REVIEW_TIMEOUT_SECONDS,
    MotionReviewSample,
    MotionReviewServiceError,
    wait_for_motion_samples,
)


@tool(
    name="motion_review",
    tiers=("work", "coding"),
    concurrency_safe=False,
    description=(
        "Inspect up to 12 representative frames from the current motion artifact. "
        "Use only after a draft or targeted revision has rendered. Select storyboard "
        "key states and before/at/after important transitions or hits; do not request "
        "every encoded frame. The runtime returns images only to vision-capable models. "
        "If samples are unavailable, continue without claiming visual inspection."
    ),
)
async def motion_review(
    artifact_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")],
    artifact_revision: Annotated[int, Field(ge=1)],
    samples: Annotated[
        list[MotionReviewSampleDescriptor], Field(min_length=1, max_length=12)
    ],
    _state: Annotated[Any | None, InjectedArg()] = None,
    agent_name: Annotated[str, InjectedArg()] = "",
    session_id: Annotated[str, InjectedArg()] = "",
) -> ToolResult:
    state = _state
    metadata = getattr(state, "metadata", None)
    capabilities = getattr(state, "capabilities", None)
    vision = bool(getattr(getattr(capabilities, "input", None), "vision", False))
    if not vision:
        return ToolResult(
            parts=[
                TextBlock(
                    text=(
                        "samples_unavailable: this model does not accept image input, so no frames "
                        "were inspected. Use renderer progress and continue without claiming visual review."
                    )
                )
            ]
        )
    if not isinstance(metadata, dict):
        return ToolResult(
            parts=[
                TextBlock(
                    text="samples_unavailable: no active motion job is available."
                )
            ]
        )
    jobs = metadata.get("_motion_progress_jobs")
    job = jobs.get(artifact_id) if isinstance(jobs, dict) else None
    if (
        not isinstance(job, dict)
        or job.get("artifact_revision") != artifact_revision
        or job.get("terminal")
    ):
        return ToolResult(
            parts=[
                TextBlock(
                    text="samples_unavailable: the artifact revision is not an active motion job."
                )
            ]
        )
    try:
        samples = [
            sample
            if isinstance(sample, MotionReviewSampleDescriptor)
            else MotionReviewSampleDescriptor.model_validate(sample)
            for sample in samples
        ]
    except ValidationError:
        return ToolResult(
            parts=[
                TextBlock(
                    text="samples_unavailable: one or more frame descriptors are invalid."
                )
            ]
        )
    if len({sample.sample_id for sample in samples}) != len(samples):
        return ToolResult(
            parts=[TextBlock(text="samples_unavailable: sample ids must be unique.")]
        )

    request_id = "review-" + secrets.token_hex(12)
    # Register the waiter before publishing so the browser cannot race the request.
    waiter = asyncio.create_task(
        wait_for_motion_samples(
            session_id,
            _request_event(job, artifact_id, artifact_revision, request_id, samples),
        )
    )
    await asyncio.sleep(0)
    published = await publish_motion_progress_update(
        state=state,
        session_id=session_id,
        agent_name=agent_name,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        phase="reviewing",
        status="running",
        audio_status=str(job.get("audio_status", "not_requested")),
        sample_request_id=request_id,
        selected_samples=samples,
    )
    if not published.get("success"):
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        return ToolResult(
            parts=[
                TextBlock(
                    text=f"samples_unavailable: {published.get('error', 'request could not be published')}."
                )
            ]
        )
    try:
        received = await asyncio.wait_for(
            waiter, timeout=DEFAULT_MOTION_REVIEW_TIMEOUT_SECONDS + 1
        )
    except (TimeoutError, MotionReviewServiceError):
        await publish_motion_progress_update(
            state=state,
            session_id=session_id,
            agent_name=agent_name,
            artifact_id=artifact_id,
            artifact_revision=artifact_revision,
            phase="reviewing",
            status="running",
            audio_status=str(job.get("audio_status", "not_requested")),
            selected_samples=samples,
        )
        return ToolResult(
            parts=[
                TextBlock(
                    text="samples_unavailable: the renderer did not return the requested frames in time. No visual inspection was performed."
                )
            ]
        )
    except asyncio.CancelledError:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
        raise

    await publish_motion_progress_update(
        state=state,
        session_id=session_id,
        agent_name=agent_name,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        phase="reviewing",
        status="running",
        audio_status=str(job.get("audio_status", "not_requested")),
        selected_samples=samples,
    )
    return _to_tool_result(received)


def _request_event(job, artifact_id, artifact_revision, request_id, samples):
    """Construct the exact event shape expected by the rendezvous before publish."""
    from app.agent.schemas.events import MotionProgressEvent

    return MotionProgressEvent.model_validate(
        {
            "agent": "pending",
            "job_id": job["job_id"],
            "sequence": int(job.get("sequence", 0)) + 1,
            "artifact_id": artifact_id,
            "artifact_revision": artifact_revision,
            "status": "running",
            "phase": "reviewing",
            "audio_status": job.get("audio_status", "not_requested"),
            "sample_request_id": request_id,
            "selected_samples": [sample.model_dump() for sample in samples],
        }
    )


def _to_tool_result(samples: list[MotionReviewSample]) -> ToolResult:
    parts: list[Any] = []
    for sample in samples:
        parts.append(
            TextBlock(
                text=(
                    f"Rendered frame for beat '{sample.beat_id}', frame {sample.frame_index + 1}, "
                    f"{sample.timestamp_ms} ms ({sample.role}). Inspect for composition, readability, "
                    "continuity, and whether the transition communicates the intended change."
                )
            )
        )
        parts.append(
            ImageDataBlock(
                data=base64.b64encode(sample.image_bytes).decode("ascii"),
                media_type=sample.mime_type,
            )
        )
    return ToolResult(parts=parts)
