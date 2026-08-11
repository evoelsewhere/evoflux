"""PPTX Artifact Fabric driver provided by the built-in Documents plugin."""

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
from app.agent.builtin_plugins.documents.rendering.runtime import file_sha256


class PptxArtifactDriver(ArtifactDriver):
    format = "pptx"
    extension = ".pptx"
    media_type = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    version = "evoflux-html-pptx-7"
    required_extra = "documents"

    def catalog(self) -> dict[str, Any]:
        from app.agent.builtin_plugins.documents.engines.pptx_html import (
            html_pptx_catalog,
        )
        from app.agent.builtin_plugins.documents.engines.pptx_template import (
            template_catalog,
        )

        return {
            "workflow": "evoflux-html-hybrid-and-template-pptx",
            "lanes": {
                "new": html_pptx_catalog(),
                "template": template_catalog(),
            },
        }

    async def inspect(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        from app.agent.builtin_plugins.documents.engines.pptx_template import (
            inspect_pptx_template,
        )

        source = _required(context.source_path, "source_path")
        result = await inspect_pptx_template(
            source,
            workspace_root=context.workspace_root,
            work_dir=context.work_dir,
        )
        return _template_result(result, source=source)

    async def validate(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        if context.source_path is None:
            from app.agent.builtin_plugins.documents.engines.pptx_html import (
                load_html_pptx_project,
                validate_html_pptx_project,
            )

            project = load_html_pptx_project(project_path)
            value = validate_html_pptx_project(project, project_path)
            engine = "evoflux-html-tailwind-hybrid"
        else:
            from app.agent.builtin_plugins.documents.engines.pptx_template import (
                load_template_manifest,
                load_template_project,
                validate_template_project,
            )

            manifest_path = _required(context.manifest_path, "manifest_path")
            project = load_template_project(project_path)
            manifest = load_template_manifest(manifest_path)
            value = validate_template_project(
                project, manifest, source_pptx=context.source_path
            )
            engine = "evoflux-direct-openxml:template"
        return ArtifactDriverResult(
            metadata=value,
            provenance={
                "project_sha256": file_sha256(project_path),
                "source_sha256": (
                    file_sha256(context.source_path) if context.source_path else None
                ),
                "engine": engine,
            },
        )

    async def build(self, context: ArtifactDriverContext) -> ArtifactDriverResult:
        project_path = _required(context.project_path, "project_path")
        candidate = context.work_dir / "candidate.pptx"
        if context.source_path is None:
            from app.agent.builtin_plugins.documents.engines.pptx_html import (
                compose_html_pptx_project,
            )

            result = await compose_html_pptx_project(
                project_path,
                candidate,
                workspace_root=context.workspace_root,
                work_dir=context.work_dir,
                session_id=context.session_id,
            )
            return _html_result(result, project_path=project_path)
        from app.agent.builtin_plugins.documents.engines.pptx_template import (
            compose_pptx_template,
        )

        manifest_path = _required(context.manifest_path, "manifest_path")
        result = await compose_pptx_template(
            context.source_path,
            project_path,
            manifest_path,
            candidate,
            workspace_root=context.workspace_root,
            work_dir=context.work_dir,
        )
        return _template_result(result, source=context.source_path)


def _html_result(result: Any, *, project_path: Path) -> ArtifactDriverResult:
    manifest = _read_manifest(getattr(result, "manifest_path", None))
    metadata = dict(getattr(result, "metadata", {}))
    metadata["layout_paths"] = [str(path) for path in result.layout_paths]
    return ArtifactDriverResult(
        candidate_path=result.output,
        previews=list(result.previews),
        issues=normalize_issues(list(result.issues)),
        manifest=manifest,
        metadata=metadata,
        provenance={
            "project_sha256": file_sha256(project_path),
            "engine": "evoflux-html-tailwind-hybrid",
        },
    )


def _template_result(result: Any, *, source: Path) -> ArtifactDriverResult:
    manifest = _read_manifest(getattr(result, "manifest_path", None))
    metadata = dict(getattr(result, "metadata", {}))
    metadata.update(
        {
            "slide_count": result.slide_count,
            "layout_paths": [str(path) for path in result.layout_paths],
        }
    )
    return ArtifactDriverResult(
        candidate_path=result.output,
        previews=list(result.previews),
        issues=normalize_issues(list(result.issues)),
        manifest=manifest,
        metadata=metadata,
        provenance={
            "source_sha256": file_sha256(source),
            "engine": "evoflux-direct-openxml:template",
        },
    )


def _read_manifest(path: Path | None) -> dict[str, Any]:
    if path and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _required(path: Path | None, label: str) -> Path:
    if path is None:
        raise ValueError(f"{label} is required")
    return path


__all__ = ["PptxArtifactDriver"]
