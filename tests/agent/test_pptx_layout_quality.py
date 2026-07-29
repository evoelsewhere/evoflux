"""Regression tests for layout-first PPTX generation and QA."""

from __future__ import annotations

from pathlib import Path

import pytest
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from app.agent.builtin_skills.pptx.scripts import qa as pptx_qa
from app.agent.builtin_skills.pptx.scripts import stylekit


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
