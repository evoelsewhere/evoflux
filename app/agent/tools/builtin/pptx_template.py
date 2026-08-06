"""Editable, high-fidelity authoring against an uploaded PPTX template."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.registry import Tool
from app.services.office.runtime import file_sha256
from app.services.pptx_template_pipeline import (
    TemplateDeckProject,
    TemplatePipelineResult,
    compose_pptx_template,
    inspect_pptx_template,
    load_template_manifest,
    load_template_project,
    render_pptx_template,
    template_catalog,
    validate_template_project,
)


_PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _read_path(path: str | None, *, suffix: str, label: str) -> Path:
    if not path:
        raise ValueError(f"{label} is required for this action")
    resolved = get_sandbox().validate_path(path, is_write=False)
    if resolved.suffix.lower() != suffix:
        raise ValueError(f"{label} must end in {suffix}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def _workspace_output(path: str | None) -> Path:
    if not path:
        raise ValueError("output is required for action='compose'")
    sandbox = get_sandbox()
    output = sandbox.validate_path(path, is_write=True)
    try:
        output.relative_to(sandbox.workspace_root)
    except ValueError as exc:
        raise PermissionError(
            "presentation output must be inside the primary workspace"
        ) from exc
    if output.suffix.lower() != ".pptx":
        raise ValueError("output must end in .pptx")
    return output


def _validate_assets(project: TemplateDeckProject, project_path: Path) -> None:
    sandbox = get_sandbox()
    for slide in project.output_slides:
        for edit in slide.edits:
            if edit.operation != "replace_image" or not edit.asset_path:
                continue
            candidate = Path(edit.asset_path)
            if not candidate.is_absolute():
                candidate = project_path.parent / candidate
            resolved = sandbox.validate_path(str(candidate), is_write=False)
            if not resolved.is_file():
                raise FileNotFoundError(f"replacement image does not exist: {resolved}")


def _work_dir(source: Path, purpose: str) -> Path:
    sandbox = get_sandbox()
    fingerprint = file_sha256(source)[:12]
    safe_stem = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in source.stem
    )[:60]
    return sandbox.validate_path(
        f".evoflux/pptx-template/{safe_stem}-{fingerprint}/{purpose}",
        is_write=True,
    )


def _result_parts(result: TemplatePipelineResult) -> list[Any]:
    parts: list[Any] = [TextBlock(text=_json(result.to_dict()))]
    for preview in result.previews[:4]:
        if preview.is_file():
            parts.append(
                ImageDataBlock(
                    data=base64.b64encode(preview.read_bytes()).decode("ascii"),
                    media_type="image/png",
                )
            )
    return parts


def _attachment(output: Path) -> list[dict[str, str]]:
    sandbox = get_sandbox()
    session_id = sandbox.session_id or ""
    if not session_id:
        return []
    relative = output.relative_to(sandbox.workspace_root).as_posix()
    encoded = quote(relative, safe="/")
    media_url = f"/api/team/{session_id}/media/{encoded}"
    return [
        {
            "filename": output.name,
            "original_name": output.name,
            "media_type": _PPTX_MEDIA_TYPE,
            "category": "document",
            "url": media_url,
            "preview_url": f"/api/team/{session_id}/office-preview/{encoded}",
            "download_url": f"{media_url}?download=1",
            "workspace_path": relative,
        }
    ]


async def _pptx_template(
    action: Annotated[
        Literal["catalog", "inspect", "validate", "render", "compose"],
        Field(
            description=(
                "catalog returns the contract; inspect inventories and renders an "
                "uploaded PPTX; validate checks a slide/edit map; render builds a "
                "non-published preview; compose exports the verified inherited PPTX."
            )
        ),
    ],
    source_pptx: Annotated[
        str | None,
        Field(
            description=(
                "Workspace- or upload-root PPTX path. Required except for catalog. "
                "The source is always read-only and is never overwritten."
            )
        ),
    ] = None,
    project_path: Annotated[
        str | None,
        Field(
            description=(
                "Template slide/edit map JSON. Required for validate, render, compose."
            )
        ),
    ] = None,
    manifest_path: Annotated[
        str | None,
        Field(
            description=(
                "template-manifest.json returned by inspect. Required for validate, "
                "render, and compose."
            )
        ),
    ] = None,
    output: Annotated[
        str | None,
        Field(description="Workspace-relative .pptx destination for compose."),
    ] = None,
) -> str | ToolResult:
    """Follow an uploaded PPTX template while keeping inherited objects editable.

    Use this only when the user explicitly says the uploaded PPTX is the visual
    template. That statement is the style confirmation, so do not ask the
    generic style question. If the upload's role is ambiguous, ask whether it
    is a visual template or merely a content source before calling this tool.
    """

    if action == "catalog":
        return _json(template_catalog())

    source = _read_path(source_pptx, suffix=".pptx", label="source_pptx")
    sandbox = get_sandbox()
    if action == "inspect":
        result = await inspect_pptx_template(
            source,
            workspace_root=sandbox.workspace_root,
            work_dir=_work_dir(source, "inspect"),
        )
        return ToolResult(parts=_result_parts(result))

    project_file = _read_path(project_path, suffix=".json", label="project_path")
    manifest_file = _read_path(manifest_path, suffix=".json", label="manifest_path")
    project = load_template_project(project_file)
    _validate_assets(project, project_file)

    if action == "validate":
        manifest = load_template_manifest(manifest_file)
        return _json(
            {
                **validate_template_project(project, manifest, source_pptx=source),
                "project_path": str(project_file),
                "manifest_path": str(manifest_file),
                "template_confirmed": project.template_confirmed,
            }
        )

    if action == "render":
        result = await render_pptx_template(
            source,
            project_file,
            manifest_file,
            workspace_root=sandbox.workspace_root,
            work_dir=_work_dir(source, "render"),
        )
        return ToolResult(parts=_result_parts(result))

    destination = _workspace_output(output)
    result = await compose_pptx_template(
        source,
        project_file,
        manifest_file,
        destination,
        workspace_root=sandbox.workspace_root,
        work_dir=_work_dir(source, f"compose-{destination.stem}"),
    )
    return ToolResult(
        parts=_result_parts(result),
        attachments=(
            _attachment(destination)
            if result.passed and destination.is_file()
            else None
        ),
    )


pptx_template = Tool(
    _pptx_template,
    name="pptx_template",
    tiers=("work",),
    deferred=True,
    deferred_summary=(
        "Inspect and edit an uploaded PPTX as the actual inherited template: "
        "duplicate source slides, preserve master/layout/theme, update resolved "
        "text, image, table, and chart objects, render QA, and fail closed."
    ),
    search_aliases=(
        "powerpoint",
        "ppt",
        "slide",
        "slides",
        "deck",
        "presentation",
        "branded",
    ),
    capabilities=("presentation", "office", "filesystem-write"),
)


__all__ = ["pptx_template"]
