"""Built-in tool for the declarative EvoOffice DOCX engine."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import Field

from app.agent.builtin_skills.docx.scripts import template as template_editor
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.services.docx_engine import (
    DocumentSpec,
    build_document,
    document_catalog,
    validate_document,
)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _validated_spec(raw: dict[str, Any]) -> DocumentSpec:
    sandbox = get_sandbox()
    normalized = DocumentSpec.model_validate(raw).model_dump()
    for block in normalized["blocks"]:
        if block.get("type") == "image":
            block["path"] = str(sandbox.validate_path(block["path"], is_write=False))
    return DocumentSpec.model_validate(normalized)


async def _docx_engine(
    action: Annotated[
        Literal["catalog", "compose", "inspect", "validate"],
        Field(description="Discover, create, inspect, or validate native DOCX files."),
    ],
    path: Annotated[
        str | None,
        Field(description="Workspace-relative .docx path for non-catalog actions."),
    ] = None,
    spec: Annotated[
        dict[str, Any] | None,
        Field(description="Declarative DocumentSpec object for compose."),
    ] = None,
    render: Annotated[
        bool,
        Field(description="Render every page and run visual QA."),
    ] = True,
) -> str:
    if action == "catalog":
        return _json({"schema_version": 1, **document_catalog()})
    if not path:
        raise ValueError(f"path is required for action={action!r}")
    sandbox = get_sandbox()

    if action == "compose":
        if spec is None:
            raise ValueError("spec is required for action='compose'")
        output = sandbox.validate_path(path, is_write=True)
        if output.suffix.lower() != ".docx":
            raise ValueError("compose path must end in .docx")
        render_dir = (
            sandbox.validate_path(
                f".evoflux/office-renders/{output.stem}-docx",
                is_write=True,
            )
            if render
            else None
        )
        result = build_document(
            _validated_spec(spec),
            output,
            asset_root=sandbox.workspace_root,
            render_dir=render_dir,
        )
        return _json(result.to_dict())

    source = sandbox.validate_path(path, is_write=False)
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise FileNotFoundError(f"Word document does not exist: {source}")
    if action == "inspect":
        return _json(
            {
                "manifest": template_editor.inspect(source),
                "quality": validate_document(source),
                "capabilities": document_catalog()["capabilities"],
            }
        )
    render_dir = (
        sandbox.validate_path(
            f".evoflux/office-renders/{source.stem}-docx",
            is_write=True,
        )
        if render
        else None
    )
    return _json(validate_document(source, render_dir=render_dir))


docx_engine = Tool(
    _docx_engine,
    name="docx_engine",
    deferred=True,
    deferred_summary=(
        "Create, inspect, render, and validate editable Word documents from a "
        "declarative semantic-block specification."
    ),
    capabilities=("document", "office", "filesystem-write"),
)


__all__ = ["docx_engine"]
