from app.agent.hooks.response_style import response_style_directive


def test_visual_style_names_only_available_visual_tools() -> None:
    both = response_style_directive("visual", {"ui_block", "visual_artifact"})
    assert "ui_block" in both and "visual_artifact" in both
    unavailable = response_style_directive("visual", set())
    assert "visual_artifact" not in unavailable and "ui_block" not in unavailable
    rich_only = response_style_directive("visual", {"visual_artifact"})
    assert "visual_artifact" in rich_only and "ui_block" not in rich_only


def test_simple_style_yields_to_an_explicit_video_artifact_request() -> None:
    prompt = response_style_directive("simple", {"visual_artifact"})
    assert "visual_artifact" in prompt
    assert "explicit video request" in prompt


def test_visual_style_routes_requested_video_to_the_evoflux_workbench() -> None:
    prompt = response_style_directive("visual", {"visual_artifact"})
    assert "requests video or needs to understand a causal state change" in prompt
    assert "prompt length and topic words alone are not signals" in prompt
    assert "explicit video request" in prompt
    assert "Workbench" in prompt
    assert "view the result in EvoFlux" in prompt


def test_video_artifact_guidance_is_omitted_when_tool_is_unavailable() -> None:
    prompt = response_style_directive("visual", set())
    assert "visual_artifact" not in prompt
    assert "Workbench" not in prompt


def test_visual_motion_guidance_uses_stage_updates_not_per_frame_events() -> None:
    prompt = response_style_directive("visual", {"visual_artifact", "motion_progress"})
    assert "motion_progress" in prompt
    assert "not emit one update per frame" in prompt
    assert "renderer owns exact frame counts" in prompt
