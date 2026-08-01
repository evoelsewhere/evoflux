"""High-fidelity editing of uploaded PowerPoint templates.

This pipeline is intentionally separate from the HTML-first deck builder. It
imports the user's PPTX, duplicates selected source slides, edits only resolved
objects, and exports the inherited master/layout structure through
``@oai/artifact-tool``. There is no HTML or fresh-slide fallback in this path.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_TEMPLATE_SLIDES = 80
MAX_EDITS_PER_SLIDE = 160
_TARGET_PREFIXES = ("sh/", "im/", "tb/", "ch/")


class TemplateObjectEdit(BaseModel):
    """One bounded edit against an object ID from the inspection manifest."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "set_text",
        "replace_text",
        "replace_image",
        "set_table_cell",
        "set_chart_series",
    ]
    target_id: str = Field(min_length=4, max_length=128)
    text: str | None = Field(default=None, max_length=20_000)
    find: str | None = Field(default=None, min_length=1, max_length=4_000)
    replace: str | None = Field(default=None, max_length=20_000)
    asset_path: str | None = Field(default=None, max_length=2_000)
    alt: str | None = Field(default=None, max_length=1_000)
    row: int | None = Field(default=None, ge=0, le=500)
    column: int | None = Field(default=None, ge=0, le=500)
    series_index: int | None = Field(default=None, ge=0, le=100)
    values: list[float] | None = Field(default=None, min_length=1, max_length=2_000)

    @field_validator("target_id")
    @classmethod
    def validate_target_id(cls, value: str) -> str:
        if not value.startswith(_TARGET_PREFIXES):
            raise ValueError(
                "target_id must be an inspect anchor beginning sh/, im/, tb/, or ch/"
            )
        return value

    @model_validator(mode="after")
    def validate_operation_fields(self) -> TemplateObjectEdit:
        if self.operation == "set_text":
            if self.text is None:
                raise ValueError("set_text requires text")
        elif self.operation == "replace_text":
            if self.find is None or self.replace is None:
                raise ValueError("replace_text requires find and replace")
        elif self.operation == "replace_image":
            if not self.asset_path:
                raise ValueError("replace_image requires asset_path")
        elif self.operation == "set_table_cell":
            if self.row is None or self.column is None or self.text is None:
                raise ValueError("set_table_cell requires row, column, and text")
        elif self.operation == "set_chart_series":
            if self.series_index is None or self.values is None:
                raise ValueError(
                    "set_chart_series requires series_index and non-empty values"
                )
        return self


class TemplateSlidePlan(BaseModel):
    """Maps one output slide to an inherited source slide."""

    model_config = ConfigDict(extra="forbid")

    output_slide: int = Field(ge=1, le=MAX_TEMPLATE_SLIDES)
    source_slide: int = Field(ge=1, le=MAX_TEMPLATE_SLIDES)
    narrative_role: str = Field(min_length=1, max_length=240)
    reuse_mode: Literal["duplicate-slide"] = "duplicate-slide"
    edits: list[TemplateObjectEdit] = Field(
        default_factory=list, max_length=MAX_EDITS_PER_SLIDE
    )
    speaker_notes: str | None = Field(default=None, max_length=40_000)


class TemplateDeckProject(BaseModel):
    """Validated plan for editing an uploaded PPTX without rebuilding it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=240)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_confirmed: Literal[True]
    output_slides: list[TemplateSlidePlan] = Field(
        min_length=1, max_length=MAX_TEMPLATE_SLIDES
    )
    omitted_source_slides: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slide_map(self) -> TemplateDeckProject:
        expected = list(range(1, len(self.output_slides) + 1))
        actual = [slide.output_slide for slide in self.output_slides]
        if actual != expected:
            raise ValueError("output_slides must be ordered sequentially from 1")
        if len(self.omitted_source_slides) != len(set(self.omitted_source_slides)):
            raise ValueError("omitted_source_slides must not contain duplicates")
        return self


@dataclass
class TemplatePipelineResult:
    action: str
    source_pptx: Path
    work_dir: Path
    manifest_path: Path | None = None
    output: Path | None = None
    previews: list[Path] = field(default_factory=list)
    layout_paths: list[Path] = field(default_factory=list)
    slide_count: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.get("severity") == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "source_pptx": str(self.source_pptx),
            "work_dir": str(self.work_dir),
            "manifest_path": (
                str(self.manifest_path) if self.manifest_path is not None else None
            ),
            "output": str(self.output) if self.output is not None else None,
            "slide_count": self.slide_count,
            "passed": self.passed,
            "issues": self.issues,
            "previews": [str(path) for path in self.previews],
            "layouts": [str(path) for path in self.layout_paths],
            **self.metadata,
        }


def pptx_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_template_project(path: Path) -> TemplateDeckProject:
    return TemplateDeckProject.model_validate_json(path.read_text(encoding="utf-8"))


def load_template_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise ValueError("template manifest must use schemaVersion 1")
    if not isinstance(value.get("records"), list):
        raise ValueError("template manifest is missing inspect records")
    return value


def validate_template_project(
    project: TemplateDeckProject,
    manifest: dict[str, Any],
    *,
    source_pptx: Path,
) -> dict[str, Any]:
    actual_hash = pptx_sha256(source_pptx)
    manifest_hash = str(manifest.get("sourceSha256", ""))
    if project.source_sha256 != actual_hash or manifest_hash != actual_hash:
        raise ValueError(
            "source PPTX changed after inspection; inspect it again before editing"
        )

    slide_count = int(manifest.get("slideCount", 0))
    records = {
        str(record.get("id")): record
        for record in manifest["records"]
        if isinstance(record, dict) and record.get("id")
    }
    referenced = {slide.source_slide for slide in project.output_slides}
    for slide in project.output_slides:
        if slide.source_slide > slide_count:
            raise ValueError(
                f"output slide {slide.output_slide} references missing source slide "
                f"{slide.source_slide}; source has {slide_count} slides"
            )
        for edit in slide.edits:
            record = records.get(edit.target_id)
            if record is None:
                raise ValueError(
                    f"edit target {edit.target_id!r} is not present in the manifest"
                )
            if int(record.get("slide", 0)) != slide.source_slide:
                raise ValueError(
                    f"edit target {edit.target_id!r} belongs to source slide "
                    f"{record.get('slide')}, not {slide.source_slide}"
                )
            expected_kind = {
                "replace_image": "image",
                "set_table_cell": "table",
                "set_chart_series": "chart",
            }.get(edit.operation)
            if expected_kind and record.get("kind") != expected_kind:
                raise ValueError(
                    f"{edit.operation} requires a {expected_kind} target; "
                    f"{edit.target_id!r} is {record.get('kind')}"
                )
            if edit.operation in {"set_text", "replace_text"} and record.get(
                "kind"
            ) not in {"textbox", "shape"}:
                raise ValueError(
                    f"{edit.operation} requires a textbox or shape target"
                )

    omitted = set(project.omitted_source_slides)
    expected_omitted = set(range(1, slide_count + 1)) - referenced
    if omitted != expected_omitted:
        raise ValueError(
            "omitted_source_slides must explicitly list every unused source slide"
        )
    return {
        "valid": True,
        "source_sha256": actual_hash,
        "source_slide_count": slide_count,
        "output_slide_count": len(project.output_slides),
        "edit_count": sum(len(slide.edits) for slide in project.output_slides),
        "preserve_only_slide_count": sum(
            1 for slide in project.output_slides if not slide.edits
        ),
    }


def template_catalog() -> dict[str, Any]:
    return {
        "workflow": "uploaded-pptx-template-following",
        "style_behavior": {
            "uploaded_template_is_style_confirmation": True,
            "ask_style_question": False,
            "ambiguous_upload": (
                "Ask whether the PPTX is a visual template or only a content source."
            ),
        },
        "invariants": [
            "Import the uploaded PPTX; never rebuild it as HTML.",
            "Duplicate source slides and preserve master, layout, theme, and geometry.",
            "Edit only inspect IDs declared in the validated slide map.",
            "Treat edits=[] as preserve-only; do not add overlays or new objects.",
            "Fail closed when artifact-tool is unavailable or fidelity checks fail.",
        ],
        "actions": {
            "inspect": "Render every source slide and emit stable object anchors.",
            "validate": "Check source hash, slide mapping, and type-safe edit targets.",
            "render": "Build and render an inherited preview deck without publishing it.",
            "compose": "Build, verify, and publish the editable inherited PPTX.",
        },
        "supported_edits": {
            "set_text": "Replace all text in an existing textbox/shape.",
            "replace_text": "Replace a substring while retaining surrounding runs.",
            "replace_image": "Swap source while preserving frame/crop/mask metadata.",
            "set_table_cell": "Update one native table cell by zero-based row/column.",
            "set_chart_series": "Update values in one native chart series.",
            "speaker_notes": "Set notes on the duplicated output slide.",
        },
        "project_json_schema": TemplateDeckProject.model_json_schema(),
    }


def _artifact_entrypoint(workspace_root: Path) -> Path:
    explicit = os.environ.get("EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())

    package_roots = [
        workspace_root / "node_modules" / "@oai" / "artifact-tool",
        Path(__file__).resolve().parents[2]
        / "node_modules"
        / "@oai"
        / "artifact-tool",
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
        / "@oai"
        / "artifact-tool",
    ]
    for package_root in package_roots:
        candidates.extend(
            [
                package_root / "dist" / "node" / "artifact_tool.mjs",
                package_root / "dist" / "artifact_tool.mjs",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "@oai/artifact-tool is required for uploaded PPTX templates. Set "
        "EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT to its built artifact_tool.mjs. "
        "The template path does not fall back to HTML or python-pptx."
    )


def _node_binary() -> str:
    explicit = os.environ.get("EVOFLUX_NODE_BIN")
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())
    found = shutil.which("node")
    if found:
        return found
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node"
    )
    if bundled.is_file():
        return str(bundled)
    raise RuntimeError(
        "Node.js is required for uploaded PPTX template editing. Set "
        "EVOFLUX_NODE_BIN to a Node 20+ executable."
    )


async def run_template_worker(
    action: Literal["inspect", "render", "compose"],
    request: dict[str, Any],
    *,
    workspace_root: Path,
    work_dir: Path,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    request_path = work_dir / f"{action}-request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    worker = Path(__file__).with_name("pptx_template_worker.mjs")
    env = os.environ.copy()
    env["EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT"] = str(
        _artifact_entrypoint(workspace_root)
    )
    process = await asyncio.create_subprocess_exec(
        _node_binary(),
        str(worker),
        action,
        str(request_path),
        cwd=str(workspace_root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(
            f"PPTX template {action} exceeded {timeout_seconds} seconds"
        ) from None
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"PPTX template worker failed ({action})")
    decoded = stdout.decode("utf-8", errors="replace")
    value: Any = None
    for line in reversed(decoded.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            value = candidate
            break
    if value is None:
        raise RuntimeError("PPTX template worker returned invalid JSON")
    if not isinstance(value, dict):
        raise RuntimeError("PPTX template worker returned a non-object response")
    return value


def _result_from_worker(
    action: str,
    source_pptx: Path,
    work_dir: Path,
    value: dict[str, Any],
) -> TemplatePipelineResult:
    return TemplatePipelineResult(
        action=action,
        source_pptx=source_pptx,
        work_dir=work_dir,
        manifest_path=(Path(value["manifestPath"]) if value.get("manifestPath") else None),
        output=Path(value["outputPath"]) if value.get("outputPath") else None,
        previews=[Path(path) for path in value.get("previewPaths", [])],
        layout_paths=[Path(path) for path in value.get("layoutPaths", [])],
        slide_count=int(value.get("slideCount", 0)),
        issues=list(value.get("issues", [])),
        metadata={
            key: item
            for key, item in value.items()
            if key
            not in {
                "manifestPath",
                "outputPath",
                "previewPaths",
                "layoutPaths",
                "slideCount",
                "issues",
            }
        },
    )


async def inspect_pptx_template(
    source_pptx: Path,
    *,
    workspace_root: Path,
    work_dir: Path,
) -> TemplatePipelineResult:
    value = await run_template_worker(
        "inspect",
        {"sourcePath": str(source_pptx), "workDir": str(work_dir)},
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    return _result_from_worker("inspect", source_pptx, work_dir, value)


async def render_pptx_template(
    source_pptx: Path,
    project_path: Path,
    manifest_path: Path,
    *,
    workspace_root: Path,
    work_dir: Path,
) -> TemplatePipelineResult:
    project = load_template_project(project_path)
    manifest = load_template_manifest(manifest_path)
    validate_template_project(project, manifest, source_pptx=source_pptx)
    value = await run_template_worker(
        "render",
        {
            "sourcePath": str(source_pptx),
            "projectPath": str(project_path),
            "manifestPath": str(manifest_path),
            "workDir": str(work_dir),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    return _result_from_worker("render", source_pptx, work_dir, value)


async def compose_pptx_template(
    source_pptx: Path,
    project_path: Path,
    manifest_path: Path,
    output: Path,
    *,
    workspace_root: Path,
    work_dir: Path,
) -> TemplatePipelineResult:
    project = load_template_project(project_path)
    manifest = load_template_manifest(manifest_path)
    validate_template_project(project, manifest, source_pptx=source_pptx)
    value = await run_template_worker(
        "compose",
        {
            "sourcePath": str(source_pptx),
            "projectPath": str(project_path),
            "manifestPath": str(manifest_path),
            "outputPath": str(output),
            "workDir": str(work_dir),
        },
        workspace_root=workspace_root,
        work_dir=work_dir,
    )
    result = _result_from_worker("compose", source_pptx, work_dir, value)
    if not result.passed and output.exists():
        output.unlink()
        result.output = None
    return result


__all__ = [
    "TemplateDeckProject",
    "TemplateObjectEdit",
    "TemplatePipelineResult",
    "TemplateSlidePlan",
    "compose_pptx_template",
    "inspect_pptx_template",
    "load_template_manifest",
    "load_template_project",
    "pptx_sha256",
    "render_pptx_template",
    "run_template_worker",
    "template_catalog",
    "validate_template_project",
]
