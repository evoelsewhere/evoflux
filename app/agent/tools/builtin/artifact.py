"""Format-neutral Artifact Fabric tool backed by bundled plugin drivers."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.registry import Tool
from app.artifacts.service import get_artifact_service


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


def _output(path: str | None, *, suffix: str) -> Path:
    if not path:
        raise ValueError("output is required for action='publish'")
    sandbox = get_sandbox()
    resolved = sandbox.validate_path(path, is_write=True)
    try:
        resolved.relative_to(sandbox.workspace_root)
    except ValueError as exc:
        raise PermissionError(
            "artifact output must be inside the primary workspace"
        ) from exc
    if resolved.suffix.lower() != suffix:
        raise ValueError(f"output must end in {suffix}")
    return resolved


def _uuid(value: str | None, label: str) -> UUID:
    if not value:
        raise ValueError(f"{label} is required for this action")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _result_parts(
    value: dict[str, Any], *, preview_offset: int = 0, preview_limit: int = 6
) -> list[Any]:
    parts: list[Any] = [TextBlock(text=_json(value))]
    paths: list[Path] = []
    revision = value.get("revision")
    if isinstance(revision, dict):
        service = get_artifact_service()
        for preview in revision.get("previews", []):
            if not isinstance(preview, dict) or not preview.get("key"):
                continue
            try:
                paths.append(service.store.resolve_preview(str(preview["key"])))
            except (FileNotFoundError, ValueError):
                continue
    result = value.get("result")
    if isinstance(result, dict):
        paths.extend(
            Path(path) for path in result.get("previews", []) if isinstance(path, str)
        )
    unique_paths = list(dict.fromkeys(path for path in paths if path.is_file()))
    selected = unique_paths[preview_offset : preview_offset + preview_limit]
    if unique_paths:
        first = preview_offset + 1
        last = preview_offset + len(selected)
        if not selected:
            parts.append(
                TextBlock(
                    text=(
                        f"No preview images at offset {preview_offset}; "
                        f"the result contains {len(unique_paths)} previews."
                    )
                )
            )
            return parts
        parts.append(
            TextBlock(
                text=(
                    f"Preview images {first}-{last} of {len(unique_paths)}. "
                    "Call artifact(action='status', job_id=..., "
                    f"preview_offset={preview_offset + preview_limit}) to review "
                    "the next page."
                    if last < len(unique_paths)
                    else f"Preview images {first}-{last} of {len(unique_paths)}."
                )
            )
        )
    for preview in selected:
        parts.append(
            ImageDataBlock(
                data=base64.b64encode(preview.read_bytes()).decode("ascii"),
                media_type="image/png",
            )
        )
    return parts


def _attachment(output: Path, *, media_type: str) -> list[dict[str, str]]:
    sandbox = get_sandbox()
    if not sandbox.session_id:
        return []
    relative = output.relative_to(sandbox.workspace_root).as_posix()
    encoded = quote(relative, safe="/")
    media_url = f"/api/team/{sandbox.session_id}/media/{encoded}"
    preview_url = f"/api/team/{sandbox.session_id}/document-preview/{encoded}"
    return [
        {
            "filename": output.name,
            "original_name": output.name,
            "media_type": media_type,
            "category": "document",
            "url": media_url,
            "preview_url": preview_url,
            "download_url": f"{media_url}?download=1",
            "workspace_path": relative,
        }
    ]


async def _artifact(
    action: Annotated[
        Literal[
            "catalog", "inspect", "validate", "preview", "publish", "status", "cancel"
        ],
        Field(
            description=(
                "Discover a native format contract, inspect a source, validate a "
                "format-specific project, build an immutable preview revision, "
                "publish its exact bytes, query status, or cancel a live job."
            )
        ),
    ],
    format: Annotated[
        str | None,
        Field(
            description=(
                "Plugin-provided document format. Required for inspect, validate, "
                "and preview; use action='catalog' to discover current values."
            )
        ),
    ] = None,
    project_path: Annotated[
        str | None,
        Field(
            description="Workspace JSON project using the selected format's native schema."
        ),
    ] = None,
    source_path: Annotated[
        str | None,
        Field(description="Read-only source/template in the selected plugin format."),
    ] = None,
    manifest_path: Annotated[
        str | None,
        Field(description="Inspect manifest required by the PPTX template lane."),
    ] = None,
    inspect_job_id: Annotated[
        str | None,
        Field(
            description=(
                "Completed inspect job UUID whose durable manifest should be reused. "
                "Preferred over manifest_path for the PPTX template lane."
            )
        ),
    ] = None,
    output: Annotated[
        str | None,
        Field(
            description="Workspace destination for publish; its suffix must match the revision."
        ),
    ] = None,
    job_id: Annotated[
        str | None,
        Field(description="Durable job UUID for publish, status, or cancel."),
    ] = None,
    revision_id: Annotated[
        str | None,
        Field(
            description="Optional immutable revision UUID for publish; defaults to latest."
        ),
    ] = None,
    preview_offset: Annotated[
        int,
        Field(
            ge=0,
            le=10_000,
            description=(
                "Zero-based preview image offset for status, preview, inspect, or "
                "publish result blocks so every page or slide can be reviewed."
            ),
        ),
    ] = 0,
    preview_limit: Annotated[
        int,
        Field(
            ge=1,
            le=12,
            description="Number of preview images to return from preview_offset.",
        ),
    ] = 6,
) -> str | ToolResult:
    """Create and publish document artifacts through one durable lifecycle.

    Project content remains format-specific and is delegated to the active
    bundled plugin driver. Call preview before publish. Publish never rebuilds
    a document. ``preview_offset`` and ``preview_limit`` control only the image
    blocks returned to the caller; they never change a stored revision.
    """

    service = get_artifact_service()
    if action == "catalog":
        return _json(service.catalog(format))
    if action in {"status", "cancel"}:
        parsed_job = _uuid(job_id, "job_id")
        value = (
            await service.status(parsed_job)
            if action == "status"
            else await service.cancel(parsed_job)
        )
        return ToolResult(
            parts=_result_parts(
                value,
                preview_offset=preview_offset if action == "status" else 0,
                preview_limit=preview_limit if action == "status" else 6,
            )
        )
    if action == "publish":
        parsed_job = _uuid(job_id, "job_id")
        before = await service.status(parsed_job)
        artifact_format = str(before["format"])
        driver = service.registry.get(artifact_format)
        destination = _output(output, suffix=driver.extension)
        value = await service.publish(
            job_id=parsed_job,
            revision_id=_uuid(revision_id, "revision_id") if revision_id else None,
            destination=destination,
        )
        return ToolResult(
            parts=_result_parts(
                value,
                preview_offset=preview_offset,
                preview_limit=preview_limit,
            ),
            attachments=_attachment(
                destination,
                media_type=driver.media_type,
            ),
        )
    if format is None:
        raise ValueError("format is required for inspect, validate, and preview")
    source = (
        _read(source_path, suffix=f".{format}", label="source_path")
        if source_path
        else None
    )
    if action == "inspect" and source is None:
        raise ValueError("source_path is required for action='inspect'")
    project = (
        _read(project_path, suffix=".json", label="project_path")
        if action in {"validate", "preview"}
        else None
    )
    manifest = (
        _read(manifest_path, suffix=".json", label="manifest_path")
        if manifest_path
        else None
    )
    sandbox = get_sandbox()
    value = await service.execute(
        action=action,
        artifact_format=format,
        workspace_root=sandbox.workspace_root,
        project_path=project,
        source_path=source,
        manifest_path=manifest,
        inspect_job_id=(
            _uuid(inspect_job_id, "inspect_job_id") if inspect_job_id else None
        ),
        session_id=sandbox.session_id,
    )
    return ToolResult(
        parts=_result_parts(
            value,
            preview_offset=preview_offset,
            preview_limit=preview_limit,
        )
    )


artifact = Tool(
    _artifact,
    name="artifact",
    tiers=("work",),
    deferred=True,
    deferred_summary=(
        "Plugin-backed durable document lifecycle: format schemas, inspect/validate, "
        "immutable QA revisions, exact-byte publish, status, and cancel."
    ),
    search_aliases=(
        "document",
        "office",
        "word",
        "docx",
        "excel",
        "xlsx",
        "spreadsheet",
        "powerpoint",
        "pptx",
        "slides",
        "pdf",
        "report",
    ),
    capabilities=("document", "office", "filesystem-write"),
)


__all__ = ["artifact"]
