from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import cast

from PIL import Image
import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pydantic import ValidationError

from app.services import pptx_html_pipeline as pipeline
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
                "editability": {
                    "eligibleObjects": 4,
                    "promotedObjects": 4,
                    "richTextRuns": 6,
                },
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
    assert "inlineRuns" in str(calls[0]["inspection_script"])
    assert result.to_dict()["editability"] == {
        "eligible_objects": 4,
        "promoted_objects": 4,
        "coverage_percent": 100.0,
        "rich_text_runs": 6,
    }


@pytest.mark.asyncio
async def test_render_html_deck_owns_the_canvas_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renderer must not keep its own copy of the geometry or the allowlist."""

    from app.services.desktop_presentation_bridge import desktop_presentation_bridge

    image = BytesIO()
    Image.new("RGB", (1600, 900), "white").save(image, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()
    calls: list[dict[str, object]] = []

    async def render(session_id: str, **kwargs):
        calls.append(kwargs)
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
    await render_html_deck(
        _project(),
        session_id="desktop-session",
        project_file=project_file,
        workspace_root=tmp_path,
        render_dir=tmp_path / "renders",
    )

    assert calls[0]["canvas"] == {
        "width": pipeline.CANVAS_WIDTH,
        "height": pipeline.CANVAS_HEIGHT,
        "exportPixelRatio": pipeline.EXPORT_PIXEL_RATIO,
        "previewPixelRatio": pipeline.PREVIEW_PIXEL_RATIO,
    }
    params = cast(dict[str, object], calls[0]["inspection_params"])
    assert params["fontAllowlist"] == sorted(pipeline.EXPORT_SAFE_FONTS)


@pytest.mark.asyncio
async def test_render_html_deck_keeps_slide_order_when_renders_finish_out_of_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slides render concurrently, so completion order must not reorder them."""

    import asyncio

    from app.services.desktop_presentation_bridge import desktop_presentation_bridge

    image = BytesIO()
    Image.new("RGB", (1600, 900), "white").save(image, format="PNG")
    png = "data:image/png;base64," + base64.b64encode(image.getvalue()).decode()

    async def render(session_id: str, **kwargs):
        # Later slides settle first.
        title = str(kwargs["document"])
        await asyncio.sleep(0.03 if "Slide one" in title else 0.0)
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
    project = HtmlDeckProject.model_validate(
        {
            "schema_version": 1,
            "title": "Ordered deck",
            "style_preset": "clean-professional",
            "style_confirmed": True,
            "slides": [
                {
                    "id": f"slide-{index}",
                    "title": title,
                    "html": f'<h1 data-pptx-native="text">{title}</h1>',
                    "speaker_notes": "note",
                    "sources": ["https://example.invalid/source"],
                }
                for index, title in enumerate(
                    ("Slide one", "Slide two", "Slide three"), start=1
                )
            ],
        }
    )
    project_file = tmp_path / "deck.json"
    project_file.write_text("{}", encoding="utf-8")

    result = await render_html_deck(
        project,
        session_id="desktop-session",
        project_file=project_file,
        workspace_root=tmp_path,
        render_dir=tmp_path / "renders",
    )

    assert [slide.number for slide in result.slides] == [1, 2, 3]
    assert [slide.slide_id for slide in result.slides] == [
        "slide-1",
        "slide-2",
        "slide-3",
    ]


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


def test_assemble_preserves_inline_text_runs_and_list_marker(tmp_path: Path) -> None:
    project = _project("<p><strong>Editable</strong> emphasis</p>")
    preview = tmp_path / "slide.png"
    background = tmp_path / "background.png"
    Image.new("RGB", (1600, 900), "white").save(preview)
    Image.new("RGB", (1600, 900), "white").save(background)
    render = SlideRender(
        number=1,
        slide_id="one",
        preview_path=preview,
        background_path=background,
        native_text=[
            {
                "text": "Editable emphasis",
                "listMarker": "•",
                "runs": [
                    {
                        "text": "Editable",
                        "fontFamily": "Aptos",
                        "fontSize": 24,
                        "fontWeight": "700",
                        "fontStyle": "normal",
                        "textDecoration": "underline",
                        "letterSpacing": "0px",
                        "color": "rgb(37, 99, 235)",
                    },
                    {
                        "text": " emphasis",
                        "fontFamily": "Aptos",
                        "fontSize": 24,
                        "fontWeight": "400",
                        "fontStyle": "italic",
                        "textDecoration": "none",
                        "letterSpacing": "0px",
                        "color": "rgb(23, 36, 45)",
                    },
                ],
                "x": 100,
                "y": 120,
                "width": 900,
                "height": 80,
                "fontFamily": "Aptos",
                "fontSize": 24,
                "fontWeight": "400",
                "fontStyle": "normal",
                "color": "rgb(23, 36, 45)",
                "textAlign": "left",
                "lineHeight": "30px",
                "order": 1,
            }
        ],
    )
    output = tmp_path / "rich-text.pptx"

    assemble_hybrid_pptx(project, [render], output)

    reopened = Presentation(output)
    runs = reopened.slides[0].shapes[1].text_frame.paragraphs[0].runs
    assert [run.text for run in runs] == ["• ", "Editable", " emphasis"]
    assert runs[1].font.bold is True
    assert runs[1].font.underline is True
    assert runs[1].font.color.rgb == RGBColor(37, 99, 235)
    assert runs[2].font.italic is True


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


def _flat_render(tmp_path: Path, number: int, shade: str) -> SlideRender:
    preview = tmp_path / f"slide_{number:02d}.png"
    background = tmp_path / f"slide_{number:02d}.background.png"
    Image.new("RGB", (1600, 900), shade).save(preview)
    Image.new("RGB", (1600, 900), shade).save(background)
    return SlideRender(
        number=number,
        slide_id=f"slide-{number}",
        preview_path=preview,
        background_path=background,
        native_text=[],
        native_shapes=[],
        native_images=[],
    )


def test_verify_exported_deck_skips_when_libreoffice_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "renderer_available", lambda: False)

    issues, report = pipeline.verify_exported_deck(
        tmp_path / "deck.pptx",
        [_flat_render(tmp_path, 1, "white")],
        tmp_path / "round-trip",
    )

    assert issues == []
    assert report["status"] == "skipped"
    assert "EVOFLUX_SOFFICE_BIN" in report["reason"]


def test_verify_exported_deck_accepts_a_matching_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = _flat_render(tmp_path, 1, "#f7f5f0")
    page = tmp_path / "page-001.png"
    Image.new("RGB", (1280, 720), "#f7f5f0").save(page)
    monkeypatch.setattr(pipeline, "renderer_available", lambda: True)
    monkeypatch.setattr(pipeline, "render_pages", lambda *a, **k: ([page], []))

    issues, report = pipeline.verify_exported_deck(
        tmp_path / "deck.pptx", [render], tmp_path / "round-trip"
    )

    assert issues == []
    assert report["status"] == "completed"
    assert report["slides"][0]["difference"] == 0.0


def test_verify_exported_deck_flags_an_export_that_does_not_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    render = _flat_render(tmp_path, 1, "white")
    page = tmp_path / "page-001.png"
    Image.new("RGB", (1280, 720), "black").save(page)
    monkeypatch.setattr(pipeline, "renderer_available", lambda: True)
    monkeypatch.setattr(pipeline, "render_pages", lambda *a, **k: ([page], []))

    issues, report = pipeline.verify_exported_deck(
        tmp_path / "deck.pptx", [render], tmp_path / "round-trip"
    )

    assert [issue.code for issue in issues] == ["round_trip_drift"]
    # Reported rather than blocking: LibreOffice substitutes fonts of its own.
    assert issues[0].severity == "warning"
    assert issues[0].slide_number == 1
    assert report["slides"][0]["difference"] == 1.0


def test_verify_exported_deck_reports_a_page_count_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = tmp_path / "page-001.png"
    Image.new("RGB", (1280, 720), "#f7f5f0").save(page)
    monkeypatch.setattr(pipeline, "renderer_available", lambda: True)
    monkeypatch.setattr(pipeline, "render_pages", lambda *a, **k: ([page], []))

    issues, _ = pipeline.verify_exported_deck(
        tmp_path / "deck.pptx",
        [_flat_render(tmp_path, 1, "#f7f5f0"), _flat_render(tmp_path, 2, "#f7f5f0")],
        tmp_path / "round-trip",
    )

    assert "round_trip_page_count" in {issue.code for issue in issues}


def test_verify_exported_deck_warns_when_rasterising_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "renderer_available", lambda: True)
    monkeypatch.setattr(
        pipeline,
        "render_pages",
        lambda *a, **k: (
            [],
            [{"severity": "error", "code": "pptx-render-failed", "message": "boom"}],
        ),
    )

    issues, report = pipeline.verify_exported_deck(
        tmp_path / "deck.pptx",
        [_flat_render(tmp_path, 1, "white")],
        tmp_path / "round-trip",
    )

    assert [issue.code for issue in issues] == ["round_trip_render_failed"]
    assert report == {"status": "failed", "reason": "boom"}
