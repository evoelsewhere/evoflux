"""Publish bounded, replayable lifecycle updates for a generated motion artifact."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field, ValidationError

from app.agent.schemas.events import (
    MotionBeatProgress,
    MotionIterationProgress,
    MotionReviewSampleDescriptor,
    MotionProgressEvent,
)
from app.agent.tools import tool
from app.agent.tools.registry import InjectedArg


def derive_motion_job_id(
    session_id: str, run_id: str, agent_name: str, artifact_id: str
) -> str:
    identity = f"{session_id}\0{run_id}\0{agent_name}\0{artifact_id}".encode("utf-8")
    return "motion-" + hashlib.sha256(identity).hexdigest()[:32]


async def publish_motion_progress_update(
    *,
    state: Any,
    session_id: str,
    agent_name: str,
    artifact_id: str,
    artifact_revision: int,
    phase: str,
    status: str = "running",
    beat: MotionBeatProgress | None = None,
    iteration: MotionIterationProgress | None = None,
    audio_status: str = "not_requested",
    sample_request_id: str | None = None,
    selected_samples: list[MotionReviewSampleDescriptor] | None = None,
) -> dict[str, Any]:
    """Publish one runtime-owned sequence for an active motion job."""
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return {
            "success": False,
            "error": "Motion progress requires an active agent run.",
        }
    active_session = metadata.get("session_id")
    run_id = metadata.get("run_id")
    if (
        not isinstance(active_session, str)
        or not active_session
        or session_id != active_session
        or not isinstance(run_id, str)
        or not run_id
    ):
        return {
            "success": False,
            "error": "Motion progress is not bound to the active session and turn.",
        }
    active_agent = agent_name or metadata.get("agent_name")
    if not isinstance(active_agent, str) or not active_agent:
        return {
            "success": False,
            "error": "Motion progress requires an active agent identity.",
        }

    job_id = derive_motion_job_id(active_session, run_id, active_agent, artifact_id)
    jobs = metadata.setdefault("_motion_progress_jobs", {})
    if not isinstance(jobs, dict):
        return {"success": False, "error": "Motion job state is unavailable."}
    previous = jobs.get(artifact_id)
    if isinstance(previous, dict):
        previous_revision = previous.get("artifact_revision", 0)
        if (
            not isinstance(previous_revision, int)
            or artifact_revision < previous_revision
        ):
            return {
                "success": False,
                "error": "Artifact revision cannot move backwards.",
            }
        if previous.get("terminal") is True:
            return {
                "success": False,
                "error": "This motion job has already reached a terminal state.",
            }
        if previous.get("job_id") != job_id:
            return {
                "success": False,
                "error": "Motion job identity changed during the active turn.",
            }
        sequence = int(previous.get("sequence", 0)) + 1
    else:
        sequence = 1

    try:
        event = MotionProgressEvent.model_validate(
            {
                "agent": active_agent,
                "job_id": job_id,
                "sequence": sequence,
                "artifact_id": artifact_id,
                "artifact_revision": artifact_revision,
                "status": status,
                "phase": phase,
                "beat": beat,
                "iteration": iteration,
                "audio_status": audio_status,
                "sample_request_id": sample_request_id,
                "selected_samples": selected_samples or [],
            }
        )
    except ValidationError as exc:
        return {"success": False, "error": str(exc)}

    try:
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        await stream_store.push_event(active_session, StreamEnvelope.from_event(event))
    except Exception:  # noqa: BLE001 - lifecycle should not fail the whole agent turn
        logger.opt(exception=True).warning(
            "motion_progress_push_failed session_id={} job_id={}",
            active_session,
            job_id,
        )
        return {"success": False, "error": "Could not publish motion progress."}

    jobs[artifact_id] = {
        "job_id": job_id,
        "sequence": sequence,
        "artifact_revision": artifact_revision,
        "terminal": status != "running",
        "audio_status": audio_status,
    }
    return {
        "success": True,
        "job_id": job_id,
        "sequence": sequence,
        "artifact_revision": artifact_revision,
        "message": f"Motion job updated: {phase}",
    }


@tool(
    name="motion_progress",
    tiers=("work", "coding"),
    concurrency_safe=False,
    description=(
        "Report a meaningful stage of a motion explainer job: planning, storyboard, "
        "style samples, composing, sample rendering/review, revision, final render, "
        "encoding, or audio. Update the same artifact_id and increase its revision "
        "only when replacing the artifact. Call at stage boundaries, not per frame. "
        "Describe the current beat and revision/iteration when relevant. Do not "
        "invent encoded frame counts or claim soundtrack inclusion; the local "
        "renderer reports exact frames and verified audio status."
    ),
)
async def motion_progress(
    artifact_id: Annotated[
        str, Field(description="Stable snake_case id for the motion artifact")
    ],
    artifact_revision: Annotated[
        int, Field(ge=1, description="Revision number for this artifact")
    ],
    phase: Annotated[
        Literal[
            "planning",
            "storyboard",
            "style_samples",
            "composing",
            "rendering_samples",
            "reviewing",
            "revising",
            "final_render",
            "encoding",
            "audio",
        ],
        Field(
            description="Current lifecycle stage; report only meaningful transitions"
        ),
    ],
    status: Annotated[
        Literal["running", "complete", "cancelled", "failed", "interrupted"],
        Field(description="Lifecycle state for this motion job"),
    ] = "running",
    beat: Annotated[
        MotionBeatProgress | None,
        Field(description="Current storyboard beat, when a storyboard exists"),
    ] = None,
    iteration: Annotated[
        MotionIterationProgress | None,
        Field(description="Current bounded sample/revision iteration"),
    ] = None,
    audio_status: Annotated[
        Literal["not_requested", "unavailable", "pending", "rendering"],
        Field(
            description="Audio intent/stage; only the local exporter can confirm included"
        ),
    ] = "not_requested",
    _state: Annotated[Any | None, InjectedArg()] = None,
    agent_name: Annotated[str, InjectedArg()] = "",
    session_id: Annotated[str, InjectedArg()] = "",
) -> dict[str, Any]:
    """Validate caller identity, assign runtime job sequence, and publish."""
    return await publish_motion_progress_update(
        state=_state,
        session_id=session_id,
        agent_name=agent_name,
        artifact_id=artifact_id,
        artifact_revision=artifact_revision,
        phase=phase,
        status=status,
        beat=beat,
        iteration=iteration,
        audio_status=audio_status,
    )
