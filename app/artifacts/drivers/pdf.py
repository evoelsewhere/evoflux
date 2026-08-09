"""First-class PDF driver."""

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
from app.services.office.runtime import file_sha256
from app.services.pdf_artifact_pipeline import (
    compose_pdf_project,
    inspect_pdf,
    load_pdf_project,
    pdf_catalog,
    validate_pdf_project,
)


class PdfArtifactDriver(ArtifactDriver):
    format = "pdf"
    extension = ".pdf"
    media_type = "application/pdf"
    version = "reportlab-pypdf-pdfium-1"

    def catalog(self) -> dict[str, Any]:
        return {
            **pdf_catalog(),
            "candidate_policy": "structural parse and render every page before acceptance",
        }

    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        source = _required(context.source_path, "source_path")
        result = await asyncio.to_thread(inspect_pdf, source, context.work_dir)
        return _result(result, source=source)

    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        project = await asyncio.to_thread(load_pdf_project, project_path)
        value = await asyncio.to_thread(
            validate_pdf_project, project, context.source_path
        )
        return ArtifactDriverResult(
            metadata=value,
            provenance={
                "project_sha256": file_sha256(project_path),
                "source_sha256": (
                    file_sha256(context.source_path) if context.source_path else None
                ),
                "engine": "reportlab+pypdf+pdfplumber+pypdfium2",
            },
        )

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        result = await asyncio.to_thread(
            compose_pdf_project,
            project_path,
            context.source_path,
            context.work_dir / "candidate.pdf",
            work_dir=context.work_dir,
        )
        return _result(result, source=context.source_path)


def _result(result: Any, *, source: Path | None) -> ArtifactDriverResult:
    manifest: dict[str, Any] = {}
    if result.manifest_path and result.manifest_path.is_file():
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    return ArtifactDriverResult(
        candidate_path=result.output,
        previews=list(result.previews),
        issues=normalize_issues(list(result.issues)),
        manifest=manifest,
        metadata=dict(result.metadata),
        provenance={
            "source_sha256": file_sha256(source) if source else None,
            "engine": "reportlab+pypdf+pdfplumber+pypdfium2",
        },
    )


def _required(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required")
    return path


__all__ = ["PdfArtifactDriver"]
