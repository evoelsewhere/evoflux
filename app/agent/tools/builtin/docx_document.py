"""Deferred DOCX tool for Word-native creation and template-safe edits."""

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
from app.services.docx_document_pipeline import (
    DocxPipelineResult,
    NewDocumentProject,
    compose_document_project,
    document_catalog,
    inspect_docx,
    load_document_project,
    render_document_project,
    validate_document_project,
)


_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


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
            "DOCX output must be inside the primary workspace"
        ) from exc
    if resolved.suffix.lower() != ".docx":
        raise ValueError("output must end in .docx")
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
        f".evoflux/docx-document/{stem}-{digest}/{purpose}", is_write=True
    )


def _validate_assets(project: Any, project_path: Path) -> None:
    if not isinstance(project, NewDocumentProject):
        return
    sandbox = get_sandbox()
    for block in project.blocks:
        if getattr(block, "type", None) != "image":
            continue
        candidate = Path(block.path)
        if not candidate.is_absolute():
            candidate = project_path.parent / candidate
        resolved = sandbox.validate_path(str(candidate), is_write=False)
        if not resolved.is_file():
            raise FileNotFoundError(f"document image does not exist: {resolved}")


def _parts(result: DocxPipelineResult) -> list[Any]:
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
            "media_type": _DOCX_MEDIA_TYPE,
            "category": "document",
            "url": media_url,
            "preview_url": f"/api/team/{sandbox.session_id}/office-preview/{encoded}",
            "download_url": f"{media_url}?download=1",
            "workspace_path": relative,
        }
    ]


async def _docx_document(
    action: Annotated[
        Literal["catalog", "inspect", "validate", "render", "compose"],
        Field(
            description="Discover the contract, inspect an uploaded template, validate a project, render every page, or compose an editable DOCX."
        ),
    ],
    project_path: Annotated[
        str | None,
        Field(
            description="Workspace JSON project path for validate, render, and compose."
        ),
    ] = None,
    source_docx: Annotated[
        str | None,
        Field(
            description="Read-only uploaded DOCX template. Required only for template mode and inspect."
        ),
    ] = None,
    output: Annotated[
        str | None,
        Field(description="Workspace-relative .docx destination for compose."),
    ] = None,
) -> str | ToolResult:
    """Create native Word documents or patch an uploaded DOCX in place.

    Template mode never rebuilds the document. It edits only declared stable
    paragraph, content-control, or table-cell locators in a copied package.
    """

    if action == "catalog":
        return _json(document_catalog())
    source = (
        _read(source_docx, suffix=".docx", label="source_docx") if source_docx else None
    )
    if action == "inspect":
        if source is None:
            raise ValueError("source_docx is required for action='inspect'")
        result = inspect_docx(source, _work_dir(source, None, "inspect"))
        return ToolResult(parts=_parts(result))

    project_file = _read(project_path, suffix=".json", label="project_path")
    project = load_document_project(project_file)
    _validate_assets(project, project_file)
    validation = validate_document_project(project, source)
    if action == "validate":
        return _json(
            {
                **validation,
                "project_path": str(project_file),
                "source_docx": str(source) if source else None,
            }
        )
    if action == "render":
        result = render_document_project(
            project_file,
            source,
            asset_root=project_file.parent,
            work_dir=_work_dir(source, project_file, "render"),
        )
        return ToolResult(parts=_parts(result))
    destination = _output(output)
    result = compose_document_project(
        project_file,
        source,
        destination,
        asset_root=project_file.parent,
        work_dir=_work_dir(source, project_file, "compose"),
    )
    return ToolResult(
        parts=_parts(result),
        attachments=_attachments(destination) if result.output else [],
    )


docx_document = Tool(
    _docx_document,
    name="docx_document",
    deferred=True,
    deferred_summary="Create, inspect, render, validate, and template-edit Word-native DOCX documents with package fidelity checks.",
    search_aliases=(
        "word",
        "report",
        "letter",
        "contract",
        "proposal",
        "resume",
        "cv",
        "memo",
    ),
    capabilities=("document", "office", "filesystem-write"),
)


__all__ = ["docx_document"]
