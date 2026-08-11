"""DOCX Artifact Fabric driver provided by the built-in Documents plugin."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.artifacts.domain import (
    ArtifactDriverContext,
    ArtifactDriverResult,
    normalize_issues,
)
from app.artifacts.drivers.base import ArtifactDriver
from app.agent.builtin_plugins.documents.rendering.runtime import file_sha256


class DocxArtifactDriver(ArtifactDriver):
    format = "docx"
    extension = ".docx"
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    version = "docx-ooxml-1"
    required_extra = "documents"

    def catalog(self) -> dict[str, Any]:
        from app.agent.builtin_plugins.documents.engines.docx import document_catalog

        return {
            **document_catalog(),
            "lanes": ["new", "template"],
            "candidate_policy": "compose once, QA every page, publish same bytes",
        }

    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        from app.agent.builtin_plugins.documents.engines.docx import inspect_docx

        source = _required(context.source_path, "source_path")
        result = await asyncio.to_thread(inspect_docx, source, context.work_dir)
        return _driver_result(result, source=source)

    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        from app.agent.builtin_plugins.documents.engines.docx import (
            load_document_project,
            validate_document_project,
        )

        project_path = _required(context.project_path, "project_path")
        project = await asyncio.to_thread(load_document_project, project_path)
        value = await asyncio.to_thread(
            validate_document_project, project, context.source_path
        )
        return ArtifactDriverResult(
            metadata=value,
            provenance=_provenance(context),
        )

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        from app.agent.builtin_plugins.documents.engines.docx import (
            compose_document_project,
        )

        project_path = _required(context.project_path, "project_path")
        candidate = context.work_dir / "candidate.docx"
        result = await asyncio.to_thread(
            compose_document_project,
            project_path,
            context.source_path,
            candidate,
            asset_root=project_path.parent,
            work_dir=context.work_dir,
        )
        return _driver_result(result, source=context.source_path)


def _driver_result(result: Any, *, source: Path | None) -> ArtifactDriverResult:
    manifest: dict[str, Any] = {}
    manifest_path = getattr(result, "manifest_path", None)
    if manifest_path and Path(manifest_path).is_file():
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    metadata = dict(getattr(result, "metadata", {}))
    metadata["action"] = result.action
    return ArtifactDriverResult(
        candidate_path=getattr(result, "output", None),
        previews=list(getattr(result, "previews", [])),
        issues=normalize_issues(list(getattr(result, "issues", []))),
        manifest=manifest,
        metadata=metadata,
        provenance={
            "source_sha256": file_sha256(source) if source else None,
            "engine": "python-docx+direct-ooxml",
        },
    )


def _provenance(context: ArtifactDriverContext) -> dict[str, Any]:
    return {
        "project_sha256": (
            file_sha256(context.project_path) if context.project_path else None
        ),
        "source_sha256": (
            file_sha256(context.source_path) if context.source_path else None
        ),
        "engine": "python-docx+direct-ooxml",
    }


def _required(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required")
    return path


__all__ = ["DocxArtifactDriver"]
