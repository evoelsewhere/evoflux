from __future__ import annotations

from pathlib import Path
import zipfile

import pytest
from pptx import Presentation

from app.agent.builtin_skills.pptx.scripts import stylekit
from app.services.pptx_engine import (
    LAYOUT_DEFAULT_PROFILES,
    LAYOUT_SLOTS,
    PresentationSpec,
    build_presentation,
    layout_catalog,
)


def _spec() -> dict:
    return {
        "title": "EvoOffice engine verification",
        "slides": [
            {
                "title": "EvoOffice compiles editable slides",
                "layout": "cover",
                "slots": {
                    "primary": {
                        "type": "text",
                        "text": "A validated artifact compiler replaces one-off coordinate scripts.",
                        "max_lines": 4,
                    },
                    "visual": {
                        "type": "icon",
                        "name": "presentation",
                        "alt_text": "Presentation document",
                    },
                },
            },
            {
                "title": "Native evidence stays editable",
                "layout": "chart-focus",
                "slots": {
                    "chart": {
                        "type": "chart",
                        "kind": "line",
                        "categories": ["Plan", "Build", "QA", "Ship"],
                        "series": {"Confidence": [35, 58, 84, 96]},
                        "title": "Confidence after each deterministic gate",
                        "show_data_labels": True,
                        "number_format": "0%",
                        "alt_text": "Confidence rises through four delivery gates.",
                    },
                    "insight": {
                        "type": "text",
                        "text": "The chart, labels, series and embedded workbook remain editable in PowerPoint.",
                        "bold": True,
                        "max_lines": 6,
                    },
                },
            },
            {
                "title": "The capability contract is explicit",
                "layout": "table-focus",
                "slots": {
                    "table": {
                        "type": "table",
                        "headers": ["Feature", "Create", "Preserve"],
                        "rows": [
                            ["Charts", "Native", "Yes"],
                            ["SmartArt", "Template", "Byte-stable"],
                            ["Media", "Template", "Relationships"],
                        ],
                        "column_weights": [1.4, 1, 1.2],
                        "alt_text": "PPTX feature capability matrix.",
                    },
                    "note": {
                        "type": "bullets",
                        "items": [
                            "Supported objects are created natively.",
                            "Unsupported objects are preserved, never flattened.",
                        ],
                    },
                },
                "profile": "executive-dense",
            },
            {
                "title": "Every build closes the quality loop",
                "layout": "process",
                "slots": {
                    "process": {
                        "type": "process",
                        "steps": ["Plan", "Compose", "Render", "Inspect", "Repair"],
                        "alt_text": "Five-step presentation quality loop.",
                    },
                    "note": {
                        "type": "text",
                        "text": "Delivery stops when structural or visual checks fail.",
                        "align": "center",
                        "bold": True,
                        "max_lines": 2,
                    },
                },
            },
        ],
    }


def test_layout_catalog_exposes_safe_slot_contracts() -> None:
    catalog = layout_catalog()

    assert len(catalog) == 18
    assert {item["name"] for item in catalog} == set(LAYOUT_SLOTS)
    assert all(item["slots"] for item in catalog)


@pytest.mark.parametrize("layout_name", list(LAYOUT_SLOTS))
def test_every_engine_layout_has_non_overlapping_safe_regions(
    layout_name: stylekit.LayoutName,
) -> None:
    presentation = stylekit.new_wide_presentation()
    profile = LAYOUT_DEFAULT_PROFILES.get(layout_name, "editorial")

    plan = stylekit.layout_plan(presentation, layout_name, profile=profile)
    regions = list(plan.content.values())

    assert set(plan.content) == set(LAYOUT_SLOTS[layout_name])
    assert all(plan.safe_canvas.contains(region) for region in regions)
    assert all(
        not left.intersects(right)
        for index, left in enumerate(regions)
        for right in regions[index + 1 :]
    )


def test_presentation_spec_rejects_unknown_layout_slot() -> None:
    raw = _spec()
    raw["slides"][0]["slots"]["missing"] = {
        "type": "text",
        "text": "Not a real slot",
    }

    with pytest.raises(ValueError, match="does not contain slots: missing"):
        PresentationSpec.model_validate(raw)


def test_build_presentation_creates_native_office_objects(tmp_path: Path) -> None:
    output = tmp_path / "engine.pptx"

    result = build_presentation(_spec(), output, asset_root=tmp_path)

    assert output.is_file()
    assert result.passed
    assert result.report["errors"] == []
    assert result.report["slides"] == 4
    summary = result.report["layout"]["office_feature_summary"]
    assert summary["native_charts"] == 1
    assert summary["native_tables"] == 1
    assert summary["groups"] == 1
    presentation = Presentation(output)
    assert len(presentation.slides) == 4
    assert presentation.core_properties.subject == "Generated by EvoOffice PPTX Engine"
    with zipfile.ZipFile(output) as package:
        chart_xml = package.read("ppt/charts/chart1.xml")
    assert b'<c:axId val="-' not in chart_xml
    assert b'<c:crossAx val="-' not in chart_xml


def test_build_presentation_rejects_copy_that_cannot_fit(tmp_path: Path) -> None:
    raw = _spec()
    raw["slides"] = [
        {
            "title": "Overflow is rejected before delivery",
            "layout": "three-column",
            "slots": {
                "column-1": {
                    "type": "text",
                    "text": "word " * 600,
                    "size": 20,
                }
            },
        }
    ]

    with pytest.raises(ValueError, match="at most 1800"):
        PresentationSpec.model_validate(raw)
