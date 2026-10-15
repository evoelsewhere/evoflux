from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.schemas.events import (
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
