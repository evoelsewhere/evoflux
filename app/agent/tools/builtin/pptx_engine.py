"""Built-in tool for the declarative EvoOffice PPTX engine."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import Field

from app.agent.builtin_skills.pptx.scripts import template as template_editor
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.services.pptx_engine import (
    PPTX_CAPABILITIES,
    PresentationSpec,
    build_presentation,
    layout_catalog,
    validate_presentation,
)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _validated_spec(raw: dict[str, Any]) -> PresentationSpec:
    sandbox = get_sandbox()
    normalized = PresentationSpec.model_validate(raw).model_dump()
    for slide in normalized["slides"]:
        for block in slide["slots"].values():
            if block.get("type") != "image":
                continue
            block["path"] = str(sandbox.validate_path(block["path"], is_write=False))
    return PresentationSpec.model_validate(normalized)


async def _pptx_engine(
    action: Annotated[
        Literal["catalog", "compose", "inspect", "validate"],
        Field(
            description=(
                "catalog lists layouts/capabilities; compose builds a new editable "
                "deck from spec; inspect inventories a supplied deck; validate runs "
                "structural and visual QA."
            )
        ),
    ],
    path: Annotated[
        str | None,
        Field(
            description=(
                "Workspace-relative .pptx path. Required for compose, inspect, and "
                "validate. Compose creates or replaces this file."
            )
        ),
    ] = None,
    spec: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Declarative PresentationSpec object for compose. Call catalog first "
                "to discover layout names and slot contracts."
            )
        ),
    ] = None,
    render: Annotated[
        bool,
        Field(
            description=(
                "Render every slide and run visual overflow checks for compose or "
                "validate. Defaults to true."
            )
        ),
    ] = True,
    allow_shape_only: Annotated[
        bool,
        Field(
            description=(
                "Allow decks of five or more slides without native charts, tables, "
                "or non-icon pictures. Defaults to false."
            )
        ),
    ] = False,
) -> str:
    """Create, inspect, or validate editable PowerPoint decks through EvoOffice.

    Prefer this deterministic tool over writing a python-pptx coordinate script.
    Existing template edits should first use inspect and then the PPTX skill's
    package-preserving mutation workflow.
    """

    if action == "catalog":
        return _json(
            {
                "schema_version": 1,
                "layouts": layout_catalog(),
                "block_types": [
                    "text",
                    "bullets",
                    "image",
                    "chart",
                    "table",
                    "process",
                    "icon",
                    "metric",
                    "quote",
                ],
                "capabilities": PPTX_CAPABILITIES,
            }
        )

    if not path:
        raise ValueError(f"path is required for action={action!r}")
    sandbox = get_sandbox()

    if action == "compose":
        if spec is None:
            raise ValueError("spec is required for action='compose'")
        output = sandbox.validate_path(path, is_write=True)
        if output.suffix.lower() != ".pptx":
            raise ValueError("compose path must end in .pptx")
        presentation_spec = _validated_spec(spec)
        presentation_spec.allow_shape_only = allow_shape_only
        render_dir = None
        if render:
            render_dir = sandbox.validate_path(
                f".evoflux/office-renders/{output.stem}", is_write=True
            )
        result = build_presentation(
            presentation_spec,
            output,
            asset_root=sandbox.workspace_root,
            render_dir=render_dir,
        )
        return _json(result.to_dict())

    source = sandbox.validate_path(path, is_write=False)
    if source.suffix.lower() != ".pptx":
        raise ValueError(f"{action} path must end in .pptx")
    if not source.is_file():
        raise FileNotFoundError(f"PowerPoint file does not exist: {source}")

    if action == "inspect":
        return _json(
            {
                "manifest": template_editor.inspect(source),
                "quality": validate_presentation(
                    source,
                    allow_shape_only=allow_shape_only,
                ),
                "capabilities": PPTX_CAPABILITIES,
            }
        )

    render_dir = None
    if render:
        render_dir = sandbox.validate_path(
            f".evoflux/office-renders/{source.stem}", is_write=True
        )
    return _json(
        validate_presentation(
            source,
            render_dir=render_dir,
            allow_shape_only=allow_shape_only,
        )
    )


pptx_engine = Tool(
    _pptx_engine,
    name="pptx_engine",
    deferred=True,
    deferred_summary=(
        "Create, inspect, render, and validate editable PowerPoint decks from a "
        "declarative layout-and-slot specification."
    ),
    capabilities=("presentation", "office", "filesystem-write"),
)


__all__ = ["pptx_engine"]
