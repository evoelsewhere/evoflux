"""Deferred XLSX tool backed exclusively by ``@oai/artifact-tool``."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.registry import Tool
from app.services.xlsx_artifact_pipeline import (
    XlsxPipelineResult,
    compose_xlsx_project,
    inspect_xlsx,
    load_workbook_project,
    render_xlsx_project,
    validate_workbook_project,
    workbook_catalog,
)


_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _read(path: str | None, *, suffix: str, label: str) -> Path:
    if not path:
        raise ValueError(f"{label} is required for this action")
    resolved = get_sandbox().validate_path(path, is_write=False)
    if resolved.suffix.lower() != suffix or not resolved.is_file():
        raise FileNotFoundError(
            f"{label} must be an existing {suffix} file: {resolved}"
        )
    return resolved


def _output(path: str | None) -> Path:
    if not path:
        raise ValueError("output is required for action='compose'")
    sandbox = get_sandbox()
    resolved = sandbox.validate_path(path, is_write=True)
    try:
        resolved.relative_to(sandbox.workspace_root)
    except ValueError as exc:
        raise PermissionError(
            "XLSX output must be inside the primary workspace"
        ) from exc
    if resolved.suffix.lower() != ".xlsx":
        raise ValueError("output must end in .xlsx")
    return resolved


def _work_dir(source: Path | None, project: Path | None, purpose: str) -> Path:
    sandbox = get_sandbox()
    seed = source or project
    assert seed is not None
    digest = hashlib.sha256(seed.read_bytes()).hexdigest()[:12]
    stem = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in seed.stem
    )[:60]
    return sandbox.validate_path(
        f".evoflux/xlsx-artifact/{stem}-{digest}/{purpose}", is_write=True
    )


def _parts(result: XlsxPipelineResult) -> list[Any]:
    parts: list[Any] = [TextBlock(text=_json(result.to_dict()))]
    for preview in result.previews[:6]:
        if preview.is_file():
            parts.append(
                ImageDataBlock(
                    data=base64.b64encode(preview.read_bytes()).decode("ascii"),
                    media_type="image/png",
                )
            )
    return parts


def _attachments(output: Path) -> list[dict[str, str]]:
    sandbox = get_sandbox()
    if not sandbox.session_id:
        return []
    relative = output.relative_to(sandbox.workspace_root).as_posix()
    encoded = quote(relative, safe="/")
    media_url = f"/api/team/{sandbox.session_id}/media/{encoded}"
    return [
        {
            "filename": output.name,
            "original_name": output.name,
            "media_type": _XLSX_MEDIA_TYPE,
            "category": "document",
            "url": media_url,
            "preview_url": f"/api/team/{sandbox.session_id}/office-preview/{encoded}",
            "download_url": f"{media_url}?download=1",
            "workspace_path": relative,
        }
    ]


async def _xlsx_artifact(
    action: Annotated[
        Literal["catalog", "inspect", "validate", "render", "compose"],
        Field(
            description="Discover the contract, inspect a template, validate a project, render all sheets, or compose an editable XLSX."
        ),
    ],
    project_path: Annotated[
        str | None,
        Field(
            description="Workspace JSON project path for validate, render, and compose."
        ),
    ] = None,
    source_xlsx: Annotated[
        str | None,
        Field(
            description="Read-only uploaded XLSX template path. Required only for template mode and inspect."
        ),
    ] = None,
    output: Annotated[
        str | None,
        Field(description="Workspace-relative .xlsx destination for compose."),
    ] = None,
) -> str | ToolResult:
    """Create or edit native spreadsheets with full cell/formula editability.

    When an XLSX is provided as a template, inspect it first and preserve its
    existing styles unless an explicit style operation is present.
    """

    if action == "catalog":
        return _json(workbook_catalog())
    sandbox = get_sandbox()
    source = (
        _read(source_xlsx, suffix=".xlsx", label="source_xlsx") if source_xlsx else None
    )
    if action == "inspect":
        if source is None:
            raise ValueError("source_xlsx is required for action='inspect'")
        result = await inspect_xlsx(
            source,
            workspace_root=sandbox.workspace_root,
            work_dir=_work_dir(source, None, "inspect"),
        )
        return ToolResult(parts=_parts(result))

    project_file = _read(project_path, suffix=".json", label="project_path")
    project = load_workbook_project(project_file)
    validation = validate_workbook_project(project, source)
    if action == "validate":
        return _json(
            {
                **validation,
                "project_path": str(project_file),
                "source_xlsx": str(source) if source else None,
            }
        )
    if action == "render":
        result = await render_xlsx_project(
            project_file,
            source,
            workspace_root=sandbox.workspace_root,
            work_dir=_work_dir(source, project_file, "render"),
        )
        return ToolResult(parts=_parts(result))
    destination = _output(output)
    result = await compose_xlsx_project(
        project_file,
        source,
        destination,
        workspace_root=sandbox.workspace_root,
        work_dir=_work_dir(source, project_file, "compose"),
    )
    return ToolResult(
        parts=_parts(result),
        attachments=_attachments(destination) if result.output else [],
    )


xlsx_artifact = Tool(
    _xlsx_artifact,
    name="xlsx_artifact",
    deferred=True,
    deferred_summary="Create, inspect, render, validate, and template-edit formula-driven XLSX workbooks with @oai/artifact-tool.",
    capabilities=("spreadsheet", "office", "filesystem-write"),
)


__all__ = ["xlsx_artifact"]
