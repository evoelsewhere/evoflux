"""HTML-first editable presentation authoring tool.

The tool exposes a bounded project format to the agent, delegates visual
composition and inspection to the EvoFlux Desktop WebView, and produces a hybrid
PPTX. Common text, shapes, lines, and images become native objects while only
unsupported visual effects stay in the pixel-stable layer.
"""

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
from app.services.pptx_html_pipeline import (
    HtmlDeckProject,
    build_html_presentation,
    html_catalog,
    load_html_deck_project,
    render_html_deck,
)

_PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _project_path(path: str | None) -> tuple[Path, HtmlDeckProject]:
    if not path:
        raise ValueError("project_path is required for this action")
    sandbox = get_sandbox()
    source = sandbox.validate_path(path, is_write=False)
    if source.suffix.lower() != ".json":
        raise ValueError("project_path must end in .json")
    if not source.is_file():
        raise FileNotFoundError(f"HTML deck project does not exist: {source}")
    return source, load_html_deck_project(source)


def _primary_workspace_output(path: str) -> Path:
    sandbox = get_sandbox()
    output = sandbox.validate_path(path, is_write=True)
    try:
        output.relative_to(sandbox.workspace_root)
    except ValueError as exc:
        raise PermissionError(
            "presentation output must be inside the primary workspace so it can "
            "be previewed and downloaded"
        ) from exc
    if output.suffix.lower() != ".pptx":
        raise ValueError("output must end in .pptx")
    return output


def _render_result_parts(result: Any, *, include_images: bool) -> list[Any]:
    parts: list[Any] = [TextBlock(text=_json(result.to_dict()))]
    if include_images:
        for slide in result.slides[:4]:
            parts.append(
                ImageDataBlock(
                    data=base64.b64encode(slide.preview_path.read_bytes()).decode(
                        "ascii"
                    ),
                    media_type="image/png",
                )
            )
    return parts


def _pptx_attachment(output: Path) -> list[dict[str, str]]:
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


async def _pptx_html(
    action: Annotated[
        Literal["catalog", "validate", "render", "compose"],
        Field(
            description=(
                "catalog returns the project contract; validate parses a project; "
                "render runs Desktop WebView visual QA and returns slide previews; compose "
                "runs full QA and writes the hybrid PowerPoint file."
            )
        ),
    ],
    project_path: Annotated[
        str | None,
        Field(
            description=(
                "Workspace-relative JSON project path. Required except for catalog."
            )
        ),
    ] = None,
    output: Annotated[
        str | None,
        Field(
            description=(
                "Workspace-relative .pptx destination. Required only for compose."
            )
        ),
    ] = None,
    slide_numbers: Annotated[
        list[int] | None,
        Field(
            description=(
                "Optional 1-based slide numbers for render. Use one representative "
                "slide during the sample approval gate."
            )
        ),
    ] = None,
    style_preset: Annotated[
        str | None,
        Field(
            description=(
                "For catalog only: return detailed guidance and layout archetypes "
                "for one built-in style preset. Omit to list every style."
            )
        ),
    ] = None,
    base_template: Annotated[
        str | None,
        Field(
            description=(
                "For catalog only: return the content contract and editable "
                "features for one built-in base template."
            )
        ),
    ] = None,
) -> str | ToolResult:
    """Author and verify HTML-first hybrid PowerPoint presentations.

    This workflow does not require an image-generation model. The source of
    truth is a controlled 1600×900 HTML/CSS project. The desktop WebView supplies the
    visual surface and QA geometry; the default editable_mode="max" restores
    semantic text, cards, rules, and images as editable PowerPoint objects.
    Twenty-one validated base templates cover common narrative and scientific
    research slide families. A project must contain a user-confirmed style;
    there is no silent visual fallback.
    """

    if action == "catalog":
        return _json(
            {
                **html_catalog(style_preset, base_template),
                "project_json_schema": HtmlDeckProject.model_json_schema(),
            }
        )

    if style_preset is not None or base_template is not None:
        raise ValueError(
            "style_preset and base_template are only accepted with action='catalog'"
        )

    source, project = _project_path(project_path)
    if action == "validate":
        return _json(
            {
                "valid": True,
                "project_path": str(source),
                "title": project.title,
                "style_preset": project.style_preset,
                "style_confirmed": project.style_confirmed,
                "slide_count": len(project.slides),
                "slide_ids": [slide.id for slide in project.slides],
            }
        )

    sandbox = get_sandbox()
    session_id = sandbox.session_id
    if not session_id:
        raise RuntimeError("PPTX rendering requires an active EvoFlux Desktop task")
    if action == "render":
        render_dir = sandbox.validate_path(
            f".evoflux/pptx-html/{source.stem}", is_write=True
        )
        result = await render_html_deck(
            project,
            session_id=session_id,
            project_file=source,
            workspace_root=sandbox.workspace_root,
            render_dir=render_dir,
            slide_numbers=slide_numbers,
        )
        return ToolResult(
            parts=_render_result_parts(result, include_images=True),
        )

    if not output:
        raise ValueError("output is required for action='compose'")
    destination = _primary_workspace_output(output)
    render_dir = sandbox.validate_path(
        f".evoflux/pptx-html/{destination.stem}", is_write=True
    )
    result = await build_html_presentation(
        project,
        session_id=session_id,
        project_file=source,
        workspace_root=sandbox.workspace_root,
        render_dir=render_dir,
        output=destination,
    )
    return ToolResult(
        parts=_render_result_parts(result, include_images=not result.passed),
        attachments=_pptx_attachment(destination) if result.passed else None,
    )


pptx_html = Tool(
    _pptx_html,
    name="pptx_html",
    deferred=True,
    deferred_summary=(
        "Create visually rich, highly editable PowerPoint decks without an "
        "image model using controlled HTML/CSS → Desktop WebView QA → native-object "
        "hybrid PPTX composition."
    ),
    search_aliases=(
        "powerpoint",
        "ppt",
        "slide",
        "slides",
        "deck",
        "presentation",
        "pitch",
        "keynote",
    ),
    capabilities=("presentation", "office", "filesystem-write"),
)


__all__ = ["pptx_html"]
