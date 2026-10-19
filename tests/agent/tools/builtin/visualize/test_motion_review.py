from __future__ import annotations

import base64
import importlib

import pytest

from app.agent.providers.capabilities import ModelCapabilities, ModelInputCapabilities
from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.state import AgentState
from app.agent.tools.builtin.visualize.motion_review import motion_review
from app.agent.tools.builtin.visualize.motion_progress import derive_motion_job_id
from app.agent.tools.builtin.visualize.motion_review import MotionReviewSample


def review_state(*, vision: bool) -> AgentState:
    state = AgentState(messages=[], system_prompt="")
    state.capabilities = ModelCapabilities(input=ModelInputCapabilities(vision=vision))
    state.metadata.update(
        {"session_id": "session-1", "run_id": "run-1", "agent_name": "lead"}
    )
    job_id = derive_motion_job_id("session-1", "run-1", "lead", "rainfall-story")
    state.metadata["_motion_progress_jobs"] = {
        "rainfall-story": {
            "job_id": job_id,
            "sequence": 2,
            "artifact_revision": 3,
            "terminal": False,
            "audio_status": "pending",
        }
    }
    return state


ARGS = {
    "artifact_id": "rainfall-story",
    "artifact_revision": 3,
    "samples": [
        {
            "sample_id": "intake-hit",
            "beat_id": "intake",
            "frame_index": 42,
            "timestamp_ms": 1400,
            "role": "impact",
        }
    ],
}


@pytest.mark.asyncio
async def test_text_only_model_gets_explicit_unavailable_without_waiting(monkeypatch):
    module = importlib.import_module("app.agent.tools.builtin.visualize.motion_review")

    async def unexpected_wait(*args, **kwargs):
        raise AssertionError("text-only model must not wait for samples")

    monkeypatch.setattr(module, "wait_for_motion_samples", unexpected_wait)
    result = await motion_review(
        **ARGS, _state=review_state(vision=False), session_id="session-1"
    )

    assert isinstance(result, ToolResult)
    assert isinstance(result.parts[0], TextBlock)
    assert "samples_unavailable" in result.parts[0].text
    assert "visual" in result.parts[0].text.lower()


@pytest.mark.asyncio
async def test_vision_model_receives_bounded_image_blocks_and_request_event(
    monkeypatch,
):
    module = importlib.import_module("app.agent.tools.builtin.visualize.motion_review")
    from app.services import memory_stream_store

    image = b"\xff\xd8\xff\xd9"
    received = MotionReviewSample(
        sample_id="intake-hit",
        beat_id="intake",
        frame_index=42,
        timestamp_ms=1400,
        role="impact",
        mime_type="image/jpeg",
        image_bytes=image,
    )
    events = []

    async def wait_samples(session_id, lifecycle_event, timeout_seconds=20.0):
        events.append(lifecycle_event)
        return [received]

    async def push_event(session_id, envelope):
        events.append(envelope.data)

    monkeypatch.setattr(module, "wait_for_motion_samples", wait_samples)
    monkeypatch.setattr(memory_stream_store, "push_event", push_event)
    state = review_state(vision=True)
    result = await motion_review(
        **ARGS, _state=state, session_id="session-1", agent_name="lead"
    )

    assert isinstance(result, ToolResult)
    image_parts = [part for part in result.parts if isinstance(part, ImageDataBlock)]
    assert len(image_parts) == 1
    assert image_parts[0].media_type == "image/jpeg"
    assert base64.b64decode(image_parts[0].data) == image
    request = next(
        item
        for item in events
        if isinstance(item, dict) and item.get("sample_request_id")
    )
    assert request["artifact_revision"] == 3
    assert request["selected_samples"][0]["sample_id"] == "intake-hit"
    assert state.metadata["_motion_progress_jobs"]["rainfall-story"]["sequence"] == 4
