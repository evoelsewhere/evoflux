"""Editable-first XLSX authoring through ``@oai/artifact-tool``.

The pipeline supports both net-new workbooks and targeted edits to uploaded
XLSX templates.  Existing workbooks are imported before modification, values
and formulas are edited without touching formatting unless explicitly asked,
and every worksheet is rendered and formula-scanned before publication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.office.runtime import (
    DEFAULT_WORKER_TIMEOUT_SECONDS,
    NodeWorkerRuntime,
    file_sha256,
)

# Backward-compatible public name retained for callers outside this module.
xlsx_sha256 = file_sha256


_A1_RANGE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]*(?::[A-Z]{1,3}[1-9][0-9]*)?$")
_FORMULA_ERRORS = r"#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A|#NUM!|#NULL!"
MAX_SHEETS = 50
MAX_OPERATIONS = 1000


JsonScalar = str | int | float | bool | None


class RangeFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fill: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    font: dict[str, Any] | None = None
    borders: dict[str, Any] | None = None
    number_format: str | None = Field(default=None, max_length=120)
    horizontal_alignment: Literal["left", "center", "right", "general"] | None = None
    vertical_alignment: Literal["top", "center", "bottom"] | None = None
    wrap_text: bool | None = None
    column_width: float | None = Field(default=None, ge=2, le=120)
    row_height: float | None = Field(default=None, ge=8, le=300)


class WriteRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["write_range"] = "write_range"
    range: str
    values: list[list[JsonScalar]] | None = None
    formulas: list[list[str | None]] | None = None
    dates: list[list[str | None]] | None = None
    format: RangeFormat | None = None

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()

    @model_validator(mode="after")
    def validate_payload(self) -> WriteRange:
        supplied = sum(
            item is not None for item in (self.values, self.formulas, self.dates)
        )
        if supplied != 1:
            raise ValueError(
                "write_range requires exactly one of values, formulas, or dates"
            )
        if self.formulas is not None:
            for row in self.formulas:
                for formula in row:
                    if formula is not None and not formula.startswith("="):
                        raise ValueError("every formula must start with '='")
        return self


class StyleRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["style_range"] = "style_range"
    range: str
    format: RangeFormat

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()


class MergeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["merge", "unmerge"]
    range: str

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if ":" not in value or not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("merge range must be a multi-cell A1 range")
        return value.upper()


class ClearRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["clear"] = "clear"
    range: str
    apply_to: Literal["contents", "formats", "all"] = "contents"

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()


class FreezePanes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["freeze_panes"] = "freeze_panes"
    rows: int = Field(default=0, ge=0, le=100)
    columns: int = Field(default=0, ge=0, le=50)


class DataValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["data_validation"] = "data_validation"
    range: str
    values: list[str] = Field(min_length=1, max_length=200)

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()


class ConditionalFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["conditional_format"] = "conditional_format"
    range: str
    rule_type: Literal["cellIs", "colorScale", "dataBar", "containsText", "expression"]
    config: dict[str, Any]

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()


class AddTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add_table"] = "add_table"
    range: str
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
    has_headers: bool = True
    style: str | None = Field(default=None, max_length=100)

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if ":" not in value or not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("table range must be a multi-cell A1 range")
        return value.upper()


class AddChart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add_chart"] = "add_chart"
    chart_type: Literal[
        "bar", "line", "area", "pie", "doughnut", "scatter", "waterfall", "funnel"
    ]
    source_range: str
    start_cell: str
    end_cell: str
    title: str = Field(min_length=1, max_length=200)
    has_legend: bool = True
    y_number_format: str | None = Field(default=None, max_length=120)

    @field_validator("source_range", "start_cell", "end_cell")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("chart references must use bounded A1 notation")
        return value.upper()


class DeleteDrawings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["delete_drawings"] = "delete_drawings"


class AutofitRange(BaseModel):
    """Size columns or rows from their rendered content.

    Preferred over guessing ``column_width``: a numeric cell narrower than its
    formatted text renders as ``#####`` in Excel, which the fit check reports.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Literal["autofit_columns", "autofit_rows"]
    range: str

    @field_validator("range")
    @classmethod
    def validate_range(cls, value: str) -> str:
        if not _A1_RANGE.fullmatch(value.upper()):
            raise ValueError("range must use bounded A1 notation")
        return value.upper()


SheetOperation = (
    WriteRange
    | StyleRange
    | MergeRange
    | ClearRange
    | FreezePanes
    | DataValidation
    | ConditionalFormat
    | AddTable
    | AddChart
    | DeleteDrawings
    | AutofitRange
)


class WorksheetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=31)
    create_if_missing: bool = False
    show_grid_lines: bool | None = None
    operations: list[SheetOperation] = Field(
        default_factory=list, max_length=MAX_OPERATIONS
    )


class WorkbookProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=240)
    mode: Literal["new", "template"]
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    template_confirmed: bool = False
    sheets: list[WorksheetPlan] = Field(min_length=1, max_length=MAX_SHEETS)

    @model_validator(mode="after")
    def validate_mode(self) -> WorkbookProject:
        names = [sheet.name.casefold() for sheet in self.sheets]
        if len(names) != len(set(names)):
            raise ValueError("worksheet plan names must be unique")
        if self.mode == "template":
            if not self.template_confirmed or self.source_sha256 is None:
                raise ValueError(
                    "template mode requires template_confirmed=true and source_sha256"
                )
        elif self.source_sha256 is not None or self.template_confirmed:
            raise ValueError("new mode must not declare template lineage")
        return self


@dataclass
class XlsxPipelineResult:
    action: str
    work_dir: Path
    source_xlsx: Path | None = None
    output: Path | None = None
    manifest_path: Path | None = None
    previews: list[Path] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.get("severity") == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "work_dir": str(self.work_dir),
            "source_xlsx": str(self.source_xlsx) if self.source_xlsx else None,
            "output": str(self.output) if self.output else None,
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "previews": [str(path) for path in self.previews],
            "issues": self.issues,
            "passed": self.passed,
            **self.metadata,
        }


def load_workbook_project(path: Path) -> WorkbookProject:
    return WorkbookProject.model_validate_json(path.read_text(encoding="utf-8"))


def workbook_catalog() -> dict[str, Any]:
    return {
        "workflow": "editable-artifact-tool-xlsx",
        "invariants": [
            "Use @oai/artifact-tool for every workbook write and export.",
            "Render and inspect an uploaded workbook before template edits.",
            "Do not overwrite cell formatting when only values or formulas change.",
            "Keep inputs typed and derived values formula-driven.",
            "Scan formula errors and render every worksheet before publishing.",
            "Size columns with autofit_columns instead of guessing column_width.",
            "Never overwrite the uploaded source workbook.",
        ],
        "operations": [
            "write_range",
            "style_range",
            "merge",
            "unmerge",
            "clear",
            "freeze_panes",
            "data_validation",
            "conditional_format",
            "add_table",
            "add_chart",
            "delete_drawings",
            "autofit_columns",
            "autofit_rows",
        ],
        "project_json_schema": WorkbookProject.model_json_schema(),
    }


_WORKER = NodeWorkerRuntime(
    worker=Path(__file__).with_name("xlsx_artifact_worker.mjs"),
    label="XLSX",
    purpose="XLSX authoring",
)


async def run_xlsx_worker(
    action: Literal["inspect", "render", "compose"],
    request: dict[str, Any],
    *,
    workspace_root: Path,
    work_dir: Path,
    timeout_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return await _WORKER.run(
        action,
        request,
        workspace_root=workspace_root,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
    )


def _result(
    action: str, work_dir: Path, value: dict[str, Any], source: Path | None
) -> XlsxPipelineResult:
    excluded = {"outputPath", "manifestPath", "previewPaths", "issues"}
    return XlsxPipelineResult(
        action=action,
        work_dir=work_dir,
        source_xlsx=source,
        output=Path(value["outputPath"]) if value.get("outputPath") else None,
        manifest_path=Path(value["manifestPath"])
        if value.get("manifestPath")
        else None,
        previews=[Path(path) for path in value.get("previewPaths", [])],
        issues=list(value.get("issues", [])),
        metadata={key: item for key, item in value.items() if key not in excluded},
    )


def validate_workbook_project(
    project: WorkbookProject, source: Path | None = None
) -> dict[str, Any]:
    if project.mode == "template":
        if source is None:
            raise ValueError("template project requires source_xlsx")
        if file_sha256(source) != project.source_sha256:
            raise ValueError("source XLSX changed after inspection; inspect it again")
    elif source is not None:
        raise ValueError("new workbook project must not declare source_xlsx")
    return {
        "valid": True,
        "mode": project.mode,
        "sheet_count": len(project.sheets),
        "operation_count": sum(len(sheet.operations) for sheet in project.sheets),
        "formula_error_pattern": _FORMULA_ERRORS,
    }


async def inspect_xlsx(
    source: Path, *, workspace_root: Path, work_dir: Path
) -> XlsxPipelineResult:
    value = await run_xlsx_worker(
        "inspect",
        {
            "sourcePath": str(source),
            "workDir": str(work_dir),
            "sourceSha256": file_sha256(source),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    return _result("inspect", work_dir, value, source)


async def render_xlsx_project(
    project_path: Path, source: Path | None, *, workspace_root: Path, work_dir: Path
) -> XlsxPipelineResult:
    project = load_workbook_project(project_path)
    validate_workbook_project(project, source)
    value = await run_xlsx_worker(
        "render",
        {
            "projectPath": str(project_path),
            "sourcePath": str(source) if source else None,
            "workDir": str(work_dir),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    return _result("render", work_dir, value, source)


async def compose_xlsx_project(
    project_path: Path,
    source: Path | None,
    output: Path,
    *,
    workspace_root: Path,
    work_dir: Path,
) -> XlsxPipelineResult:
    project = load_workbook_project(project_path)
    validate_workbook_project(project, source)
    value = await run_xlsx_worker(
        "compose",
        {
            "projectPath": str(project_path),
            "sourcePath": str(source) if source else None,
            "outputPath": str(output),
            "workDir": str(work_dir),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    result = _result("compose", work_dir, value, source)
    if not result.passed and output.exists():
        output.unlink()
        result.output = None
    return result


__all__ = [
    "WorkbookProject",
    "XlsxPipelineResult",
    "compose_xlsx_project",
    "inspect_xlsx",
    "load_workbook_project",
    "render_xlsx_project",
    "run_xlsx_worker",
    "validate_workbook_project",
    "workbook_catalog",
    "xlsx_sha256",
]
