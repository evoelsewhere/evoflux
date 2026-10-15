"""Rich, bounded dashboard/motion/3D artifact tool."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field, ValidationError

from app.agent.schemas.chat import ToolMessage
from app.agent.schemas.events import (
    Scene3DSpec,
    VisualArtifactEvent,
    VisualArtifactSourceRef,
)
from app.agent.tools import tool
from app.agent.tools.registry import InjectedArg


@tool(
    name="visual_artifact",
    tiers=("work", "coding"),
    concurrency_safe=False,
    description=(
        "Create a rich EvoFlux Workbench visual only when the user's task benefits from "
        "a custom dashboard, a controllable motion explainer, or spatial 3D "
        "inspection. Judge the task and likely next action, not keywords. Choose motion "
        "for an explicit video request or when understanding depends on seeing state "
        "changes or why one stage enables the next, even if a static flowchart could "
        "list the steps. Use static forms for lookup, comparison, or print. Prompt length "
        "does not make a task a video: keep static facts, summaries, and comparisons "
        "in prose, ui_block, or a dashboard as appropriate. Condense long sources "
        "into a few factual scene beats instead of animating every detail. Use "
        "ui_block for compact native controls and prose for simple answers. "
        "Dashboard data must come from successful tool results in this run; "
        "include their tool_call_id and a short query_summary, and never claim "
        "live freshness without source evidence. Dashboard and motion use "
        "source_html (at most 200000 UTF-8 bytes); motion needs a short "
        "scene-by-scene story, a complete composition drawn on one fixed-size canvas "
        "marked data-evoflux-motion-canvas, duration_ms, play/pause/restart/seek commands, "
        "and accurate playback reports including ended. For deterministic export, "
        "call window.evofluxArtifact.registerFrameRenderer(drawAt), where pure "
        "drawAt(timeMs) redraws the whole canvas from that absolute time; "
        "use 1280x720 for Balanced "
        "or 1920x1080 for High output, scaled with CSS; avoid Date.now(), "
        "requestAnimationFrame state, timers, and unseeded randomness in that renderer. "
        "Export is user initiated and encodes frames locally when WebCodecs is available; "
        "older artifacts can use the browser's real-time recorder. Scene3d uses only "
        "validated box, sphere, cylinder, and torus primitives. Pass a stable "
        "artifact_id to update the same artifact in place."
    ),
)
async def visual_artifact(
    artifact_id: Annotated[
        str, Field(description="Stable snake_case artifact identity")
    ],
    kind: Annotated[
        Literal["dashboard", "motion", "scene3d"],
        Field(description="Rich artifact kind"),
    ],
    title: Annotated[str, Field(min_length=1, max_length=120)],
    summary: Annotated[str, Field(max_length=500)],
    source_html: Annotated[
        str | None,
        Field(description="Self-contained artifact HTML; no external dependencies"),
    ] = None,
    scene: Annotated[
        Scene3DSpec | None, Field(description="Declarative primitive scene for scene3d")
    ] = None,
    sources: Annotated[
        list[VisualArtifactSourceRef],
        Field(max_length=12, description="Verified dashboard tool call references"),
    ] = Field(default_factory=list),
    duration_ms: Annotated[int | None, Field(ge=1, le=120_000)] = None,
    _injected: Annotated[dict[str, Any] | None, InjectedArg()] = None,
    _state: Annotated[Any | None, InjectedArg()] = None,
    agent_name: Annotated[str, InjectedArg()] = "",
    tool_call_id: Annotated[str, InjectedArg()] = "",
    session_id: Annotated[str, InjectedArg()] = "",
) -> dict[str, Any]:
    """Validate, emit one complete artifact event, and persist via tool args."""
    injected = _injected or {}
    if injected:
        agent_name = str(injected.get("agent_name") or agent_name)
        tool_call_id = str(injected.get("tool_call_id") or tool_call_id)
        session_id = str(injected.get("session_id") or session_id)

    state = _state or injected.get("_state")
    messages = getattr(state, "messages", [])
    normalized_sources: list[VisualArtifactSourceRef] = []
    for source_raw in sources:
        try:
            source = VisualArtifactSourceRef.model_validate(source_raw)
        except ValidationError as exc:
            return {"success": False, "error": str(exc)}
        normalized_sources.append(source)
        matched = next(
            (
                message
                for message in messages
                if isinstance(message, ToolMessage)
                and message.tool_call_id == source.tool_call_id
            ),
            None,
        )
        if matched is None or not _tool_result_succeeded(matched.content):
            return {
                "success": False,
                "error": f"Dashboard source tool call '{source.tool_call_id}' was not found as a successful tool result in active history.",
            }
    # Keep this check explicit: source references must never point at this
    # artifact call itself, even in malformed or synthetic histories.
    source_ids = {
        message.tool_call_id for message in messages if isinstance(message, ToolMessage)
    }
    if tool_call_id in source_ids and any(
        item.tool_call_id == tool_call_id for item in normalized_sources
    ):
        return {
            "success": False,
            "error": "A dashboard cannot cite its own tool call as a source.",
        }

    try:
        event = VisualArtifactEvent.model_validate(
            {
                "agent": agent_name,
                "tool_call_id": tool_call_id,
                "artifact_id": artifact_id,
                "artifact_revision": _active_artifact_revision(state, artifact_id),
                "kind": kind,
                "title": title,
                "summary": summary,
                "source_html": source_html,
                "scene": scene,
                "sources": normalized_sources,
                "duration_ms": duration_ms,
            }
        )
    except ValidationError as exc:
        return {"success": False, "error": str(exc)}

    pushed = False
    if session_id:
        try:
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(session_id, StreamEnvelope.from_event(event))
            pushed = True
        except Exception:  # noqa: BLE001 - keep tool result truthful on stream errors
            logger.opt(exception=True).warning(
                "visual_artifact_push_failed session_id={}", session_id
            )
    else:
        logger.warning("visual_artifact_push_skipped reason=missing_session_id")

    return {
        "success": True,
        "artifact_id": event.artifact_id,
        "artifact_revision": event.artifact_revision,
        "kind": event.kind,
        "message": f"Rendered {event.kind} artifact '{event.title}'",
        "pushed": pushed,
    }


def _tool_result_succeeded(content: str) -> bool:
    """Treat explicit structured failures and error text as unsuccessful."""
    if not content.strip():
        return False
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return not content.lstrip().lower().startswith(("error:", "failed:"))
    if isinstance(value, dict):
        return value.get("success") is not False and not value.get("error")
    return True


def _active_artifact_revision(state: Any, artifact_id: str) -> int | None:
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    jobs = metadata.get("_motion_progress_jobs")
    current = jobs.get(artifact_id) if isinstance(jobs, dict) else None
    revision = current.get("artifact_revision") if isinstance(current, dict) else None
    return revision if isinstance(revision, int) and revision >= 1 else None
