"""Built-in tool for the declarative EvoOffice XLSX engine."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.services.xlsx_engine import (
    WorkbookSpec,
    build_workbook,
    inspect_workbook,
    validate_workbook,
    workbook_catalog,
)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


async def _xlsx_engine(
    action: Annotated[
        Literal["catalog", "compose", "inspect", "validate"],
        Field(description="Discover, create, inspect, or validate native XLSX files."),
    ],
    path: Annotated[
        str | None,
        Field(description="Workspace-relative .xlsx path for non-catalog actions."),
    ] = None,
    spec: Annotated[
        dict[str, Any] | None,
        Field(description="Declarative WorkbookSpec object for compose."),
    ] = None,
    render: Annotated[
        bool,
        Field(description="Render every worksheet and run visual QA."),
    ] = True,
) -> str:
    if action == "catalog":
        return _json({"schema_version": 1, **workbook_catalog()})
    if not path:
        raise ValueError(f"path is required for action={action!r}")
    sandbox = get_sandbox()

    if action == "compose":
        if spec is None:
            raise ValueError("spec is required for action='compose'")
        output = sandbox.validate_path(path, is_write=True)
        if output.suffix.lower() != ".xlsx":
            raise ValueError("compose path must end in .xlsx")
        render_dir = (
            sandbox.validate_path(
                f".evoflux/office-renders/{output.stem}-xlsx",
                is_write=True,
            )
            if render
            else None
        )
        result = build_workbook(
            WorkbookSpec.model_validate(spec),
            output,
            render_dir=render_dir,
        )
        return _json(result.to_dict())

    source = sandbox.validate_path(path, is_write=False)
    if source.suffix.lower() != ".xlsx" or not source.is_file():
        raise FileNotFoundError(f"Excel workbook does not exist: {source}")
    if action == "inspect":
        return _json(inspect_workbook(source))
    render_dir = (
        sandbox.validate_path(
            f".evoflux/office-renders/{source.stem}-xlsx",
            is_write=True,
        )
        if render
        else None
    )
    return _json(validate_workbook(source, render_dir=render_dir))


xlsx_engine = Tool(
    _xlsx_engine,
    name="xlsx_engine",
    deferred=True,
    deferred_summary=(
        "Create, inspect, render, and validate editable Excel workbooks from a "
        "declarative sheet-and-block specification."
    ),
    capabilities=("spreadsheet", "office", "filesystem-write"),
)


__all__ = ["xlsx_engine"]
