from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.pptx_template_pipeline import (
    TemplateDeckProject,
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
                "schemaVersion": 1,
                "sourceSha256": digest,
                "slideCount": 3,
                "records": [
                    {"id": "sh/title", "slide": 1, "kind": "textbox"},
                    {"id": "im/hero", "slide": 1, "kind": "image"},
                    {"id": "tb/data", "slide": 2, "kind": "table"},
                    {"id": "ch/trend", "slide": 2, "kind": "chart"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _project(digest: str) -> TemplateDeckProject:
    return TemplateDeckProject.model_validate(
        {
            "schema_version": 1,
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
                            "target_id": "sh/title",
                            "find": "Old",
                            "replace": "New",
                        },
                        {
                            "operation": "replace_image",
                            "target_id": "im/hero",
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
                            "target_id": "tb/data",
                            "row": 1,
                            "column": 2,
                            "text": "$4.2M",
                        },
                        {
                            "operation": "set_chart_series",
                            "target_id": "ch/trend",
                            "series_index": 0,
                            "values": [1, 2, 3],
                        },
                    ],
                },
            ],
            "omitted_source_slides": [3],
        }
    )


def test_template_catalog_declares_uploaded_template_style_behavior() -> None:
    catalog = template_catalog()

    assert catalog["style_behavior"]["uploaded_template_is_style_confirmation"]
    assert catalog["style_behavior"]["ask_style_question"] is False
    assert "replace_image" in catalog["supported_edits"]
    assert "project_json_schema" in catalog


def test_template_project_validates_complete_typed_mapping(tmp_path: Path) -> None:
    source, digest = _source(tmp_path)
    manifest = load_template_manifest(_manifest(tmp_path, digest))

    result = validate_template_project(
        _project(digest), manifest, source_pptx=source
    )

    assert result["valid"] is True
    assert result["source_slide_count"] == 3
    assert result["output_slide_count"] == 2
    assert result["edit_count"] == 4


def test_template_project_requires_sequential_output_slides() -> None:
    with pytest.raises(ValidationError, match="sequentially"):
        TemplateDeckProject.model_validate(
            {
                "schema_version": 1,
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


def test_template_project_requires_explicit_omissions(tmp_path: Path) -> None:
    source, digest = _source(tmp_path)
    manifest = load_template_manifest(_manifest(tmp_path, digest))
    payload = _project(digest).model_dump()
    payload["omitted_source_slides"] = []

    with pytest.raises(ValueError, match="every unused source slide"):
        validate_template_project(
            TemplateDeckProject.model_validate(payload),
            manifest,
            source_pptx=source,
        )


def test_template_project_rejects_wrong_target_type(tmp_path: Path) -> None:
    source, digest = _source(tmp_path)
    manifest = load_template_manifest(_manifest(tmp_path, digest))
    payload = _project(digest).model_dump()
    payload["output_slides"][0]["edits"][1]["target_id"] = "sh/title"

    with pytest.raises(ValueError, match="requires a image target"):
        validate_template_project(
            TemplateDeckProject.model_validate(payload),
            manifest,
            source_pptx=source,
        )
