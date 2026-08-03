from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from app.services import xlsx_artifact_pipeline as pipeline
from app.services.office.runtime import file_sha256


def _new_project() -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Plan",
        "mode": "new",
        "template_confirmed": False,
        "sheets": [
            {
                "name": "Inputs",
                "create_if_missing": True,
                "operations": [
                    {
                        "operation": "write_range",
                        "range": "A1:B2",
                        "values": [["Label", "Value"], ["Revenue", 10]],
                    }
                ],
            }
        ],
    }


def test_workbook_project_requires_template_lineage() -> None:
    raw = _new_project()
    raw["mode"] = "template"
    with pytest.raises(ValueError, match="source_sha256"):
        pipeline.WorkbookProject.model_validate(raw)


def test_workbook_catalog_exposes_editable_operations() -> None:
    catalog = pipeline.workbook_catalog()
    assert catalog["workflow"] == "editable-artifact-tool-xlsx"
    assert "write_range" in catalog["operations"]
    assert "add_chart" in catalog["operations"]
    assert "autofit_columns" in catalog["operations"]
    assert "autofit_rows" in catalog["operations"]
    assert catalog["project_json_schema"]["properties"]["mode"]


def _project_with_operations(operations: list[dict[str, object]]) -> dict[str, object]:
    raw = _new_project()
    sheets = cast(list[dict[str, object]], raw["sheets"])
    sheets[0]["operations"] = operations
    return raw


def test_autofit_operations_are_accepted() -> None:
    raw = _project_with_operations(
        [
            {
                "operation": "write_range",
                "range": "A1:B2",
                "values": [["Label", "Value"], ["Revenue", 10]],
            },
            {"operation": "autofit_columns", "range": "A1:B2"},
            {"operation": "autofit_rows", "range": "A1:B2"},
        ]
    )

    project = pipeline.WorkbookProject.model_validate(raw)

    assert [item.operation for item in project.sheets[0].operations] == [
        "write_range",
        "autofit_columns",
        "autofit_rows",
    ]


def test_autofit_requires_a_bounded_range() -> None:
    raw = _project_with_operations([{"operation": "autofit_columns", "range": "A:B"}])

    with pytest.raises(ValueError, match="bounded A1 notation"):
        pipeline.WorkbookProject.model_validate(raw)


@pytest.mark.asyncio
async def test_compose_deletes_failed_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_path = tmp_path / "project.json"
    project_path.write_text(json.dumps(_new_project()), encoding="utf-8")
    output = tmp_path / "output.xlsx"

    async def fake_worker(*args: object, **kwargs: object) -> dict[str, object]:
        output.write_bytes(b"failed")
        return {
            "outputPath": str(output),
            "previewPaths": [],
            "issues": [{"severity": "error", "code": "formula-error"}],
        }

    monkeypatch.setattr(pipeline, "run_xlsx_worker", fake_worker)
    result = await pipeline.compose_xlsx_project(
        project_path,
        None,
        output,
        workspace_root=tmp_path,
        work_dir=tmp_path / "work",
    )

    assert result.passed is False
    assert result.output is None
    assert not output.exists()


def test_template_validation_detects_changed_source(tmp_path: Path) -> None:
    source = tmp_path / "template.xlsx"
    source.write_bytes(b"original")
    project = pipeline.WorkbookProject.model_validate(
        {
            "schema_version": 1,
            "title": "Edit",
            "mode": "template",
            "source_sha256": file_sha256(source),
            "template_confirmed": True,
            "sheets": [{"name": "Sheet1", "operations": []}],
        }
    )
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed after inspection"):
        pipeline.validate_workbook_project(project, source)
