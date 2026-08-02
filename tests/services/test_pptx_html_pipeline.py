from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
from pptx import Presentation
from pydantic import ValidationError

from app.services.pptx_html_pipeline import (
    HtmlDeckProject,
    QaIssue,
    SlideRender,
    assemble_hybrid_pptx,
    render_html_deck,
    validate_html_fragment,
)
from app.services.pptx_html_styles import (
    LAYOUT_ARCHETYPES,
    STYLE_PRESETS,
    style_catalog,
)
from app.services.pptx_html_templates import (
    BASE_TEMPLATES,
    render_base_template,
    template_catalog,
)


def _project(
    html: str = '<h1 data-pptx-native="text">A clear title</h1>',
) -> HtmlDeckProject:
    return HtmlDeckProject.model_validate(
        {
            "schema_version": 1,
            "title": "Test deck",
            "style_preset": "clean-professional",
            "style_confirmed": True,
            "slides": [
                {
                    "id": "one",
                    "title": "A clear title",
                    "html": html,
                    "speaker_notes": "Presenter note",
                    "sources": ["https://example.invalid/source"],
                }
            ],
        }
    )


@pytest.mark.parametrize(
    "fragment",
    [
        "<script>alert(1)</script>",
        '<img src="https://example.com/x.png">',
        '<div onclick="alert(1)">x</div>',
        '<div style="background:url(file:///etc/passwd)">x</div>',
        '<iframe src="asset://frame.html"></iframe>',
    ],
)
def test_html_security_rejects_executable_or_external_content(fragment: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        _project(fragment)


def test_html_security_accepts_workspace_assets_and_inline_svg() -> None:
    validate_html_fragment(
        '<img src="asset://assets/chart.svg"><svg><use href="#mark"></use></svg>'
    )


def test_style_library_has_twelve_complete_visual_systems() -> None:
    assert len(STYLE_PRESETS) == 12
    assert {"mckinsey", "creative-magazine", "handdrawn-technical"} <= set(
        STYLE_PRESETS
    )
    for preset in STYLE_PRESETS.values():
        assert preset.archetypes
        assert set(preset.archetypes) <= set(LAYOUT_ARCHETYPES)
        assert preset.css.strip()


def test_style_catalog_returns_only_selected_style_details() -> None:
    catalog = style_catalog("mckinsey")

    assert catalog["selected_style"]["id"] == "mckinsey"
    assert "typographic-statement" in catalog["layout_archetypes"]
    assert "styles" not in catalog


def test_project_rejects_an_unknown_style_preset() -> None:
    with pytest.raises(ValidationError, match="unknown style_preset"):
        HtmlDeckProject.model_validate(
            {
                "schema_version": 1,
                "title": "Bad style",
                "style_preset": "made-up",
                "style_confirmed": True,
                "slides": [{"id": "one", "title": "One", "html": "<p>One</p>"}],
            }
        )


def test_project_requires_explicit_user_confirmed_style() -> None:
    base = {
        "schema_version": 1,
        "title": "No silent style",
        "slides": [{"id": "one", "title": "One", "html": "<p>One</p>"}],
    }
    with pytest.raises(ValidationError, match="style_preset"):
        HtmlDeckProject.model_validate(base)
    with pytest.raises(ValidationError, match="style_confirmed"):
        HtmlDeckProject.model_validate({**base, "style_preset": "scientific-defense"})


def test_project_defaults_to_maximum_editability() -> None:
    project = _project("<h1>Editable without an explicit marker</h1>")

    assert project.editable_mode == "max"


@pytest.mark.asyncio
async def test_render_html_deck_uses_desktop_webview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.desktop_presentation_bridge import desktop_presentation_bridge

    image = BytesIO()
    Image.new("RGB", (1600, 900), "white").save(image, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()
    calls: list[dict[str, object]] = []

    async def render(session_id: str, **kwargs):
        calls.append({"session_id": session_id, **kwargs})
        return {
            "inspection": {
                "issues": [],
                "nativeText": [],
                "nativeShapes": [],
                "nativeImages": [],
            },
            "preview": png,
            "background": png,
            "nativeImages": [],
        }

    monkeypatch.setattr(desktop_presentation_bridge, "render", render)
    project_file = tmp_path / "deck.json"
    project_file.write_text("{}", encoding="utf-8")
    result = await render_html_deck(
        _project(),
        session_id="desktop-session",
        project_file=project_file,
        workspace_root=tmp_path,
        render_dir=tmp_path / "renders",
    )

    assert result.passed
    assert result.slides[0].preview_path.read_bytes().startswith(b"\x89PNG")
    assert calls[0]["session_id"] == "desktop-session"
    assert "A clear title" in str(calls[0]["document"])
    assert "getBoundingClientRect" in str(calls[0]["inspection_script"])


def test_base_template_library_covers_complete_slide_families() -> None:
    assert len(BASE_TEMPLATES) == 21
    assert {
        "cover-split",
        "metric-story",
        "process-flow",
        "architecture-layers",
        "bar-chart",
        "data-table",
        "image-story",
        "closing-actions",
        "research-paper-overview",
        "research-problem-chain",
        "research-contribution-grid",
        "research-architecture-annotated",
        "research-mechanism",
        "research-equation-explainer",
        "research-results-summary",
    } <= set(BASE_TEMPLATES)
    assert all(template.editable_features for template in BASE_TEMPLATES.values())


def test_template_slide_renders_without_raw_html() -> None:
    project = HtmlDeckProject.model_validate(
        {
            "schema_version": 1,
            "title": "Template deck",
            "style_preset": "clean-professional",
            "style_confirmed": True,
            "slides": [
                {
                    "id": "metric",
                    "title": "Three measures explain the result",
                    "template": "metric-story",
                    "content": {
                        "metrics": [
                            {"label": "One", "value": "10", "detail": "First"},
                            {"label": "Two", "value": "20", "detail": "Second"},
                        ],
                        "insight": "One implication",
                    },
                }
            ],
        }
    )

    assert project.slides[0].html is None
    assert project.slides[0].template == "metric-story"
    rendered = render_base_template(
        "metric-story", project.slides[0].title, project.slides[0].content
    )
    assert 'data-pptx-shape="roundRect"' in rendered


def test_template_slide_rejects_ambiguous_or_invalid_content() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        HtmlDeckProject.model_validate(
            {
                "schema_version": 1,
                "title": "Ambiguous",
                "style_preset": "clean-professional",
                "style_confirmed": True,
                "slides": [
                    {
                        "id": "one",
                        "title": "One",
                        "html": "<p>One</p>",
                        "template": "quote",
                        "content": {"quote": "One", "attribution": "Two"},
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="unsupported template content"):
        HtmlDeckProject.model_validate(
            {
                "schema_version": 1,
                "title": "Invalid",
                "style_preset": "clean-professional",
                "style_confirmed": True,
                "slides": [
                    {
                        "id": "one",
                        "title": "One",
                        "template": "quote",
                        "content": {
                            "quote": "One",
                            "attribution": "Two",
                            "unknown": "No",
                        },
                    }
                ],
            }
        )


def test_template_catalog_can_focus_one_contract() -> None:
    catalog = template_catalog("bar-chart")

    assert catalog["selected_template"]["id"] == "bar-chart"
    assert "series" in catalog["selected_template"]["content_schema"]["required"]


def test_scientific_template_catalog_exposes_style_affinity() -> None:
    catalog = template_catalog("research-mechanism")

    selected = catalog["selected_template"]
    assert selected["style_affinity"][0] == "scientific-defense"
    assert "lines" in selected["editable_features"]

    full_catalog = template_catalog()
    assert full_catalog["families"]["general"] == 14
    assert full_catalog["families"]["scientific_research"]["count"] == 7


def test_scientific_templates_balance_titles_and_promote_marker_text() -> None:
    rendered = render_base_template(
        "research-contribution-grid",
        "A deliberately long research title that must wrap predictably in PowerPoint",
        {
            "contributions": [
                {"title": "One", "claim": "Claim", "evidence": "Evidence"},
                {"title": "Two", "claim": "Claim", "evidence": "Evidence"},
                {"title": "Three", "claim": "Claim", "evidence": "Evidence"},
            ],
            "takeaway": "Synthesis",
        },
    )

    assert "<br>" in rendered
    assert "<p>1</p>" in rendered
    assert "<p>→</p>" in rendered


def test_assemble_hybrid_pptx_restores_native_text_and_notes(tmp_path: Path) -> None:
    project = _project()
    preview = tmp_path / "slide.png"
    background = tmp_path / "background.png"
    Image.new("RGB", (1600, 900), "#f7f5f0").save(preview)
    Image.new("RGB", (1600, 900), "#f7f5f0").save(background)
    render = SlideRender(
        number=1,
        slide_id="one",
        preview_path=preview,
        background_path=background,
        native_text=[
            {
                "text": "A clear title",
                "role": "title",
                "x": 100,
                "y": 120,
                "width": 900,
                "height": 100,
                "fontFamily": '"Aptos Display", Arial',
                "fontSize": 56,
                "fontWeight": "700",
                "fontStyle": "normal",
                "color": "rgb(23, 36, 45)",
                "textAlign": "left",
                "paddingLeft": 0,
                "paddingRight": 0,
                "paddingTop": 0,
                "paddingBottom": 0,
            }
        ],
        issues=[QaIssue("warning", "example", "retained warning", 1)],
    )
    output = tmp_path / "deck.pptx"

    assemble_hybrid_pptx(project, [render], output)

    reopened = Presentation(output)
    assert len(reopened.slides) == 1
    slide = reopened.slides[0]
    assert len(slide.shapes) == 2
    assert slide.shapes[1].text == "A clear title"
    assert slide.shapes[1].text_frame.paragraphs[0].runs[0].font.bold is True
    notes = slide.notes_slide.notes_text_frame.text
    assert "Presenter note" in notes
    assert "[Sources]" in notes
    assert "https://example.invalid/source" in notes


def test_assemble_restores_editable_shapes_and_images(tmp_path: Path) -> None:
    project = _project("<div data-box><p>Editable card</p></div>")
    preview = tmp_path / "slide.png"
    background = tmp_path / "background.png"
    editable_image = tmp_path / "editable-image.png"
    Image.new("RGB", (1600, 900), "#f7f5f0").save(preview)
    Image.new("RGB", (1600, 900), "#f7f5f0").save(background)
    Image.new("RGBA", (240, 160), "#e97335").save(editable_image)
    render = SlideRender(
        number=1,
        slide_id="one",
        preview_path=preview,
        background_path=background,
        native_text=[],
        native_shapes=[
            {
                "type": "shape",
                "shapeType": "roundRect",
                "x": 100,
                "y": 140,
                "width": 440,
                "height": 220,
                "fill": "rgb(255, 255, 255)",
                "borderColor": "rgb(21, 94, 99)",
                "borderWidth": 2,
                "order": 1,
            }
        ],
        native_images=[
            {
                "path": str(editable_image),
                "x": 620,
                "y": 160,
                "width": 240,
                "height": 160,
                "order": 2,
            }
        ],
    )
    output = tmp_path / "editable-objects.pptx"

    assemble_hybrid_pptx(project, [render], output)

    reopened = Presentation(output)
    slide = reopened.slides[0]
    assert len(slide.shapes) == 3
    assert slide.shapes[1].name.startswith("[evoflux-html][role:shape]")
    assert slide.shapes[2].name.startswith("[evoflux-html][role:image]")


def test_assemble_requires_every_slide_render(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="all slides"):
        assemble_hybrid_pptx(_project(), [], tmp_path / "deck.pptx")
