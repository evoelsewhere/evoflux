from __future__ import annotations

import importlib
import json
from pathlib import Path

from PIL import Image
import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.schemas.chat import ImageDataBlock, ToolResult
from app.agent.tools.builtin import pptx_html as pptx_html_tool
from app.services.pptx_html_pipeline import HtmlDeckBuildResult, QaIssue, SlideRender

_pptx_html_module = importlib.import_module("app.agent.tools.builtin.pptx_html")


@pytest.fixture
def sandbox(tmp_path: Path):
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            session_id="00000000-0000-0000-0000-000000000001",
            denied_roots=[],
        )
    )
    try:
        yield tmp_path
    finally:
        _sandbox_ctx.reset(token)


def _write_project(root: Path) -> Path:
    path = root / "deck.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Tool deck",
                "style_preset": "clean-professional",
                "style_confirmed": True,
                "slides": [
                    {
                        "id": "one",
                        "title": "Tool slide",
                        "html": '<h1 data-pptx-native="text">Tool slide</h1>',
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _fake_result(root: Path, *, passed: bool = True) -> HtmlDeckBuildResult:
    preview = root / "slide.png"
    background = root / "background.png"
    Image.new("RGB", (32, 18), "white").save(preview)
    Image.new("RGB", (32, 18), "white").save(background)
    issues = [] if passed else [QaIssue("error", "overflow", "bad", 1)]
    return HtmlDeckBuildResult(
        output=None,
        render_dir=root,
        slides=[
            SlideRender(
                number=1,
                slide_id="one",
                preview_path=preview,
                background_path=background,
                native_text=[],
                issues=issues,
            )
        ],
        issues=issues,
    )


async def test_catalog_exposes_html_project_contract() -> None:
    result = await pptx_html_tool.arun(action="catalog")

    payload = json.loads(result)
    assert payload["canvas"] == {"width": 1600, "height": 900, "ratio": "16:9"}
    assert payload["native_export"]["markers"]["text"] == ('data-pptx-native="text"')
    assert payload["native_export"]["editable_mode"]["max"].startswith("default")
    assert payload["project_json_schema"]["properties"]["editable_mode"]["default"] == (
        "max"
    )
    assert "project_json_schema" in payload
    assert len(payload["style_system"]["styles"]) == 12
    assert len(payload["base_template_system"]["templates"]) == 21
    assert payload["style_selection_gate"]["silent_default"] is None
    assert payload["style_selection_gate"]["localization"].startswith("Ask in")
    required = payload["project_json_schema"]["required"]
    assert "style_preset" in required
    assert "style_confirmed" in required


async def test_catalog_can_focus_one_style_preset() -> None:
    result = await pptx_html_tool.arun(
        action="catalog", style_preset="creative-magazine"
    )

    payload = json.loads(result)
    assert payload["style_system"]["selected_style"]["id"] == "creative-magazine"
    assert "editorial-hero" in payload["style_system"]["layout_archetypes"]


async def test_catalog_can_focus_one_base_template() -> None:
    result = await pptx_html_tool.arun(
        action="catalog", base_template="architecture-layers"
    )

    payload = json.loads(result)
    selected = payload["base_template_system"]["selected_template"]
    assert selected["id"] == "architecture-layers"
    assert "rounded shapes" in selected["editable_features"]


async def test_validate_reads_a_workspace_project(sandbox: Path) -> None:
    _write_project(sandbox)

    result = await pptx_html_tool.arun(action="validate", project_path="deck.json")

    payload = json.loads(result)
    assert payload["slide_ids"] == ["one"]
    assert payload["style_confirmed"] is True


async def test_render_returns_visual_preview(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(sandbox)

    async def fake_render(*args, **kwargs):
        assert kwargs["session_id"] == "00000000-0000-0000-0000-000000000001"
        return _fake_result(sandbox)

    monkeypatch.setattr(_pptx_html_module, "render_html_deck", fake_render)

    result = await pptx_html_tool.arun(
        action="render", project_path="deck.json", slide_numbers=[1]
    )

    assert isinstance(result, ToolResult)
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)


async def test_compose_publishes_previewable_downloadable_artifact(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(sandbox)

    async def fake_build(*args, **kwargs):
        assert kwargs["session_id"] == "00000000-0000-0000-0000-000000000001"
        destination = Path(kwargs["output"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"pptx")
        result = _fake_result(sandbox)
        result.output = destination
        return result

    monkeypatch.setattr(_pptx_html_module, "build_html_presentation", fake_build)

    result = await pptx_html_tool.arun(
        action="compose", project_path="deck.json", output="deliverables/deck.pptx"
    )

    assert isinstance(result, ToolResult)
    assert result.attachments
    attachment = result.attachments[0]
    assert attachment["workspace_path"] == "deliverables/deck.pptx"
    assert "/office-preview/deliverables/deck.pptx" in attachment["preview_url"]
    assert attachment["download_url"].endswith("?download=1")


async def test_compose_fail_closed_does_not_publish_artifact(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(sandbox)

    async def fake_build(*args, **kwargs):
        return _fake_result(sandbox, passed=False)

    monkeypatch.setattr(_pptx_html_module, "build_html_presentation", fake_build)

    result = await pptx_html_tool.arun(
        action="compose", project_path="deck.json", output="deck.pptx"
    )

    assert isinstance(result, ToolResult)
    assert result.attachments is None
    assert any(isinstance(part, ImageDataBlock) for part in result.parts)
