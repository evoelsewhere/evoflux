from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.schemas.events import (
    MotionProgressEvent,
    Scene3DNode,
    Scene3DSpec,
    VisualArtifactEvent,
    VisualArtifactSourceRef,
    validate_visual_artifact_source,
)


def valid_scene_node(index: int = 1) -> dict[str, object]:
    return {
        "id": f"node-{index}",
        "geometry": "box",
        "position": (0, 0, 0),
        "rotation": (0, 0, 0),
        "scale": (1, 1, 1),
        "color": "accent",
    }


def valid_event(**overrides: object) -> dict[str, object]:
    return {
        "agent": "assistant",
        "tool_call_id": "call-1",
        "artifact_id": "example",
        "kind": "dashboard",
        "title": "Example",
        "summary": "A useful dashboard",
        "source_html": "<main>Example</main>",
        "sources": [],
        "is_final": True,
        **overrides,
    }


def test_rejects_unknown_kind_wrong_payload_kind_and_source_over_200000_bytes() -> None:
    with pytest.raises(ValidationError):
        VisualArtifactEvent.model_validate({**valid_event(), "kind": "video"})
    with pytest.raises(ValidationError, match="source_html"):
        VisualArtifactEvent.model_validate(
            {
                **valid_event(),
                "kind": "scene3d",
                "scene": {"nodes": [valid_scene_node()]},
            }
        )
    with pytest.raises(ValidationError, match="duration_ms"):
        VisualArtifactEvent.model_validate(
            {**valid_event(), "kind": "motion", "duration_ms": None}
        )
    with pytest.raises(ValueError, match="200000 UTF-8 bytes"):
        validate_visual_artifact_source("é" * 100_001)


def test_scene_limits_nodes_rejects_urls_scripts_and_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        Scene3DSpec.model_validate({"nodes": [valid_scene_node(i) for i in range(101)]})
    with pytest.raises(ValidationError):
        Scene3DNode.model_validate(
            {**valid_scene_node(), "geometry": "https://example.test/model.glb"}
        )
    with pytest.raises(ValidationError):
        Scene3DNode.model_validate(
            {**valid_scene_node(), "script": "fetch('https://example.test')"}
        )
    with pytest.raises(ValidationError):
        Scene3DSpec.model_validate({"nodes": [valid_scene_node(), valid_scene_node()]})


def test_source_ref_requires_tool_call_and_query_summary() -> None:
    with pytest.raises(ValidationError):
        VisualArtifactSourceRef.model_validate({"tool_call_id": "call-1"})


def test_motion_duration_is_capped_at_120_seconds() -> None:
    with pytest.raises(ValidationError):
        VisualArtifactEvent.model_validate(
            {**valid_event(), "kind": "motion", "duration_ms": 120_001}
        )


def valid_motion_progress(**overrides: object) -> dict[str, object]:
    return {
        "agent": "lead",
        "job_id": "motion-" + "a" * 32,
        "sequence": 1,
        "artifact_id": "rainfall-story",
        "artifact_revision": 1,
        "status": "running",
        "phase": "storyboard",
        "beat": {"id": "collection", "index": 0, "total": 4, "title": "Collect"},
        "frames": {
            "scope": "review_samples",
            "completed": 1,
            "total": 4,
            "fps": 24,
            "last_completed_index": 0,
        },
        "iteration": {"current": 1, "budget": 3},
        "selected_samples": [
            {
                "sample_id": "collection-start",
                "beat_id": "collection",
                "frame_index": 0,
                "timestamp_ms": 0,
                "role": "key_state",
            }
        ],
        "audio_status": "pending",
        **overrides,
    }


def test_motion_progress_validates_bounded_descriptors_and_counters() -> None:
    event = MotionProgressEvent.model_validate(valid_motion_progress())
    assert event.type == "motion_progress"
    assert event.frames is not None and event.frames.completed == 1
    assert len(event.selected_samples) == 1

    invalid = [
        {"phase": "planning", "status": "complete"},
        {"frames": {"scope": "final_output", "completed": -1, "total": 4}},
        {"frames": {"scope": "final_output", "completed": 5, "total": 4}},
        {"image_base64": "AA=="},
        {"beat": {"id": "bad id", "index": 0, "total": 4, "title": "x"}},
        {
            "selected_samples": [
                {
                    "sample_id": "bad id",
                    "beat_id": "b",
                    "frame_index": 0,
                    "timestamp_ms": 0,
                    "role": "style",
                }
            ]
        },
        {
            "selected_samples": [
                {
                    "sample_id": f"sample-{index}",
                    "beat_id": "beat",
                    "frame_index": index,
                    "timestamp_ms": index,
                    "role": "style",
                }
                for index in range(13)
            ]
        },
    ]
    for patch in invalid:
        with pytest.raises(ValidationError):
            MotionProgressEvent.model_validate({**valid_motion_progress(), **patch})


def test_motion_progress_review_request_requires_bounded_samples() -> None:
    with pytest.raises(ValidationError, match="sample"):
        MotionProgressEvent.model_validate(
            valid_motion_progress(sample_request_id="review-1", selected_samples=[])
        )
