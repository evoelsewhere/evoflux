from app.agent.hooks.response_style import response_style_directive


def test_visual_style_names_only_available_visual_tools() -> None:
    both = response_style_directive("visual", {"ui_block", "visual_artifact"})
    assert "ui_block" in both and "visual_artifact" in both
    unavailable = response_style_directive("visual", set())
    assert "visual_artifact" not in unavailable and "ui_block" not in unavailable
    rich_only = response_style_directive("visual", {"visual_artifact"})
    assert "visual_artifact" in rich_only and "ui_block" not in rich_only


def test_simple_style_does_not_recommend_visual_tools() -> None:
    assert "visual_artifact" not in response_style_directive(
        "simple", {"visual_artifact"}
    )
