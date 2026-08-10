"""Native XLSX driver backed by EvoFlux's OpenXML engine."""

from __future__ import annotations

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
from app.services.xlsx_artifact_pipeline import (
    compose_xlsx_project,
    inspect_xlsx,
    load_workbook_project,
    validate_workbook_project,
    workbook_catalog,
)


class XlsxArtifactDriver(ArtifactDriver):
    format = "xlsx"
    extension = ".xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    version = "evoflux-openxml-xlsx-2"

    def catalog(self) -> dict[str, Any]:
        return {
            **workbook_catalog(),
            "lanes": ["new", "template"],
            "candidate_policy": "export once, scan formulas, render all sheets",
        }

    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        source = _required(context.source_path, "source_path")
        result = await inspect_xlsx(
            source,
            workspace_root=context.workspace_root,
            work_dir=context.work_dir,
        )
        return _driver_result(result, source=source)

    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        project = load_workbook_project(project_path)
        value = validate_workbook_project(project, context.source_path)
        return ArtifactDriverResult(
            metadata=value,
            provenance=_provenance(context),
        )

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        candidate = context.work_dir / "candidate.xlsx"
        result = await compose_xlsx_project(
            project_path,
            context.source_path,
            candidate,
            workspace_root=context.workspace_root,
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
            "engine": "evoflux-openxml",
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
        "engine": "evoflux-openxml",
    }


def _required(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required")
    return path


__all__ = ["XlsxArtifactDriver"]
