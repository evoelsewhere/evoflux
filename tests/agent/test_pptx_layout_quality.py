"""Regression tests for layout-first PPTX generation and QA."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from app.agent.builtin_skills.pptx.scripts import qa as pptx_qa
from app.agent.builtin_skills.pptx.scripts import stylekit
from app.agent.builtin_skills.pptx.scripts import icons as pptx_icons


def _slide(presentation):
    return presentation.slides.add_slide(presentation.slide_layouts[6])


def _textbox(slide, text: str, left: float, top: float, width: float, height: float):
    shape = slide.shapes.add_textbox(
        Inches(left),
        Inches(top),
        Inches(width),
        Inches(height),
    )
    shape.text = text
    shape.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
    return shape


def test_layout_plan_produces_safe_non_overlapping_regions() -> None:
    presentation = stylekit.new_wide_presentation()

    plan = stylekit.layout_plan(presentation, "split")

    text = plan.region("text")
    visual = plan.region("visual")
    assert plan.safe_canvas.contains(text)
    assert plan.safe_canvas.contains(visual)
    assert not text.intersects(visual)


def test_layout_guard_rejects_collisions() -> None:
    presentation = stylekit.new_wide_presentation()
    plan = stylekit.layout_plan(presentation, "hero")
    guard = stylekit.LayoutGuard(plan)
    canvas = plan.region("canvas")
    guard.reserve(
        "first",
        left=canvas.left,
        top=canvas.top,
        width=Inches(4),
        height=Inches(2),
    )

    with pytest.raises(stylekit.LayoutError, match="collides"):
        guard.reserve(
            "second",
            left=canvas.left + Inches(3),
            top=canvas.top + Inches(1),
            width=Inches(4),
            height=Inches(2),
        )


def test_title_and_kicker_fit_above_guarded_content() -> None:
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    plan = stylekit.layout_plan(presentation, "hero")
    guard = stylekit.LayoutGuard(plan)

    stylekit.add_title(
        slide,
        "One clear takeaway",
        kicker="Context",
        guard=guard,
    )
    guard.reserve_region(plan.region("canvas"))

    assert len(slide.shapes) == 2


def test_add_text_rejects_copy_that_cannot_fit() -> None:
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)

    with pytest.raises(stylekit.TextOverflowError, match="change layout"):
        stylekit.add_text(
            slide,
            "This sentence is intentionally far too long for the tiny text box.",
            left=Inches(1),
            top=Inches(2),
            width=Inches(1.5),
            height=Inches(0.35),
            font="Aptos",
            size=18,
            color="20303C",
        )


def test_quality_ledger_reports_all_text_issues_after_one_build() -> None:
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    ledger = stylekit.QualityLedger()

    stylekit.add_text(
        slide,
        "This body copy is too small.",
        left=Inches(1),
        top=Inches(2),
        width=Inches(3),
        height=Inches(0.5),
        font="Aptos",
        size=12,
        color="20303C",
        ledger=ledger,
    )
    stylekit.add_text(
        slide,
        "This sentence is intentionally far too long for the tiny text box.",
        left=Inches(1),
        top=Inches(3),
        width=Inches(1.5),
        height=Inches(0.35),
        font="Aptos",
        size=18,
        color="20303C",
        ledger=ledger,
    )

    assert len(slide.shapes) == 2
    assert len(ledger.errors) == 2
    with pytest.raises(stylekit.LayoutError, match="2 issue"):
        ledger.raise_if_errors()


def test_curated_icon_search_resolves_semantic_aliases() -> None:
    assert len(pptx_icons.list_icons()) == 47
    assert pptx_icons.resolve_icon("growth") == "trending-up"
    assert any(match.name == "chart-line" for match in pptx_icons.search_icons("analytics"))


def test_add_icon_embeds_themeable_svg_and_qa_metadata(tmp_path: Path) -> None:
    source = tmp_path / "icons.pptx"
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    picture = pptx_icons.add_icon(
        slide,
        "agent",
        left=Inches(1),
        top=Inches(2),
        size=Inches(0.7),
        color="2F6D68",
    )
    presentation.save(source)

    assert picture.name == "[icon:lucide:bot]"
    with zipfile.ZipFile(source) as package:
        svg_parts = [
            name
            for name in package.namelist()
            if name.startswith("ppt/media/") and name.endswith(".svg")
        ]
        assert len(svg_parts) == 1
        assert b'stroke="#2F6D68"' in package.read(svg_parts[0])

    report = pptx_qa.inspect_pptx(source)
    metrics = report["layout"]["metrics"][0]
    assert report["errors"] == []
    assert metrics["icon_count"] == 1
    assert metrics["icon_families"] == ["lucide"]


def test_icon_qa_flags_tiny_or_mixed_family_icons(tmp_path: Path) -> None:
    source = tmp_path / "mixed-icons.pptx"
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    pptx_icons.add_icon(
        slide,
        "rocket",
        left=Inches(1),
        top=Inches(2),
        size=Inches(0.2),
    )
    other = pptx_icons.add_icon(
        slide,
        "target",
        left=Inches(2),
        top=Inches(2),
        size=Inches(0.6),
    )
    other.name = "[icon:other:target]"
    presentation.save(source)

    report = pptx_qa.inspect_pptx(source)

    assert any("only 0.20in" in warning for warning in report["warnings"])
    assert any("families lucide, other" in warning for warning in report["warnings"])


def test_structural_qa_rejects_overlapping_text_items(tmp_path: Path) -> None:
    source = tmp_path / "overlap.pptx"
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    _textbox(slide, "First message", 1, 2, 5, 1.2)
    _textbox(slide, "Second message", 4, 2.3, 5, 1.2)
    presentation.save(source)

    report = pptx_qa.inspect_pptx(source)

    assert any("overlap by" in error for error in report["errors"])
    assert report["layout"]["metrics"][0]["overlaps"]


def test_structural_qa_rejects_excessive_rounded_cards(tmp_path: Path) -> None:
    source = tmp_path / "cards.pptx"
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    for index in range(4):
        slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(0.8 + index * 3.05),
            Inches(2),
            Inches(2.6),
            Inches(2.2),
        )
    presentation.save(source)

    report = pptx_qa.inspect_pptx(source)

    assert any("rounded rectangles" in error for error in report["errors"])


def test_template_baseline_suppresses_unchanged_design_debt(tmp_path: Path) -> None:
    source = tmp_path / "template.pptx"
    presentation = stylekit.new_wide_presentation()
    slide = _slide(presentation)
    for index in range(4):
        slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(0.8 + index * 3.05),
            Inches(2),
            Inches(2.6),
            Inches(2.2),
        )
    presentation.save(source)

    report = pptx_qa.inspect_pptx(source, reference=source)

    assert not any("rounded rectangles" in error for error in report["errors"])
    assert report["layout"]["findings"] == []
