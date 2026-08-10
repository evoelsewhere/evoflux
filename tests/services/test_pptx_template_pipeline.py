from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches
import pytest
from pydantic import ValidationError

from app.services.pptx_template_pipeline import (
    TemplateDeckProject,
    compose_pptx_template,
    inspect_pptx_template,
    load_template_manifest,
    template_catalog,
    validate_template_project,
)


def _source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "template.pptx"
    source.write_bytes(b"pptx-template-fixture")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return source, digest


def _manifest(tmp_path: Path, digest: str) -> Path:
    manifest = tmp_path / "template-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "sourceSha256": digest,
                "slideCount": 3,
                "records": [
                    {"id": "sh/1/2", "slide": 1, "kind": "textbox"},
                    {"id": "im/1/3", "slide": 1, "kind": "image"},
                    {"id": "tb/2/4", "slide": 2, "kind": "table"},
                    {"id": "ch/2/5", "slide": 2, "kind": "chart"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _project(digest: str) -> TemplateDeckProject:
    return TemplateDeckProject.model_validate(
        {
            "schema_version": 2,
            "title": "Inherited deck",
            "source_sha256": digest,
            "template_confirmed": True,
            "output_slides": [
                {
                    "output_slide": 1,
                    "source_slide": 1,
                    "narrative_role": "opening",
                    "edits": [
                        {
                            "operation": "replace_text",
                            "target_id": "sh/1/2",
                            "find": "Old",
                            "replace": "New",
                        },
                        {
                            "operation": "replace_image",
                            "target_id": "im/1/3",
                            "asset_path": "hero.png",
                        },
                    ],
                },
                {
                    "output_slide": 2,
                    "source_slide": 2,
                    "narrative_role": "evidence",
                    "edits": [
                        {
                            "operation": "set_table_cell",
                            "target_id": "tb/2/4",
                            "row": 1,
                            "column": 2,
                            "text": "$4.2M",
                        },
                        {
                            "operation": "set_chart_series",
                            "target_id": "ch/2/5",
                            "series_index": 0,
                            "values": [1, 2, 3],
                        },
                    ],
                },
            ],
            "omitted_source_slides": [3],
        }
    )


def test_template_catalog_declares_direct_openxml_preservation() -> None:
    catalog = template_catalog()
    assert catalog["workflow"] == "direct-openxml-pptx-template"
    assert catalog["style_behavior"]["uploaded_template_is_style_confirmation"]
    assert "replace_image" in catalog["supported_edits"]


def test_template_project_validates_complete_typed_mapping(tmp_path: Path) -> None:
    source, digest = _source(tmp_path)
    manifest = load_template_manifest(_manifest(tmp_path, digest))

    result = validate_template_project(_project(digest), manifest, source_pptx=source)

    assert result["valid"] is True
    assert result["edit_count"] == 4


def test_template_project_requires_sequential_output_slides() -> None:
    with pytest.raises(ValidationError, match="sequentially"):
        TemplateDeckProject.model_validate(
            {
                "schema_version": 2,
                "title": "Bad map",
                "source_sha256": "0" * 64,
                "template_confirmed": True,
                "output_slides": [
                    {
                        "output_slide": 2,
                        "source_slide": 1,
                        "narrative_role": "opening",
                    }
                ],
            }
        )


def test_template_project_rejects_changed_source(tmp_path: Path) -> None:
    source, digest = _source(tmp_path)
    manifest = load_template_manifest(_manifest(tmp_path, digest))
    project = _project(digest)
    source.write_bytes(b"changed")

    with pytest.raises(ValueError, match="changed after inspection"):
        validate_template_project(project, manifest, source_pptx=source)


@pytest.mark.asyncio
async def test_inspect_and_compose_preserve_source_shapes(tmp_path: Path) -> None:
    source = tmp_path / "source.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    textbox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    textbox.text = "Old title"
    presentation.save(source)

    inspected = await inspect_pptx_template(
        source, workspace_root=tmp_path, work_dir=tmp_path / "inspect"
    )
    manifest = load_template_manifest(inspected.manifest_path)
    target = next(
        record["id"] for record in manifest["records"] if record["kind"] == "textbox"
    )
    project_path = tmp_path / "project.json"
    project_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "title": "Edited",
                "source_sha256": manifest["sourceSha256"],
                "template_confirmed": True,
                "output_slides": [
                    {
                        "output_slide": 1,
                        "source_slide": 1,
                        "narrative_role": "opening",
                        "edits": [
                            {
                                "operation": "replace_text",
                                "target_id": target,
                                "find": "Old",
                                "replace": "New",
                            }
                        ],
                    }
                ],
                "omitted_source_slides": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output.pptx"

    result = await compose_pptx_template(
        source,
        project_path,
        inspected.manifest_path,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "compose",
    )

    assert result.passed is True
    reopened = Presentation(output)
    assert len(reopened.slides) == 1
    assert reopened.slides[0].shapes[0].text == "New title"
