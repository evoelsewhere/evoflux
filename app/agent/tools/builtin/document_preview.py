"""document_preview tool — render a workspace document the way the viewer does.

The host already owns a read-only rendering engine for Office and PDF files
(:mod:`app.services.document_preview`). It needs no office application and no
external renderer binary, but until now it was reachable only from the
workspace viewer in the interface, so an agent that produced a document had no
way to check what it looks like.

This tool exposes that engine in-process and reports what the rendering says:
each page with its labelled elements, their text, and their geometry as
percentages of the page box — which is what makes "this shape hangs off the
slide" an observation rather than a guess. Formats, size budgets, cache policy,
and the markup contract all come from the service, so the tool cannot drift
from the viewer.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from loguru import logger
from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import Tool
from app.services.document_preview import (
    DocumentPreviewError,
    DocumentPreviewUnsupportedError,
    render_document_preview,
)
from app.services.document_preview.inspection import (
    PreviewItem,
    PreviewSummary,
    summarize_document_preview,
)
from app.services.document_preview.service import (
    SUPPORTED_DOCUMENT_PREVIEW_EXTENSIONS,
)


def _supported_suffixes() -> str:
    return ", ".join(sorted(SUPPORTED_DOCUMENT_PREVIEW_EXTENSIONS))


def _format_geometry(item: PreviewItem, *, verbose: bool) -> list[str]:
    lines: list[str] = []
    for element in item.elements:
        text = f" :: {element.text}" if element.text else ""
        flagged = element.out_of_bounds()
        if not verbose and not flagged and not element.text:
            continue
        box = ""
        if element.left is not None and element.width is not None:
            box = (
                f" [{element.left:.1f},{element.top or 0:.1f} "
                f"{element.width:.1f}x{element.height or 0:.1f}%]"
            )
        marker = " OUTSIDE PAGE" if flagged else ""
        lines.append(f"    {element.label}{box}{marker}{text}")
    return lines


def _render_report(
    *,
    source: str,
    preview: Path,
    summary: PreviewSummary,
    verbose: bool,
) -> str:
    out_of_bounds = {
        item.label: [element.label for element in item.out_of_bounds()]
        for item in summary.items
        if item.out_of_bounds()
    }

    lines = [
        f"[Document preview: {source}]",
        f"Rendered by the host viewer engine: {preview} "
        f"({preview.stat().st_size:,} bytes)",
        f"Pages: {len(summary.items)}"
        + (" (truncated)" if summary.items_truncated else ""),
    ]

    if out_of_bounds:
        lines.append("")
        lines.append("Elements outside the page box:")
        for label, elements in out_of_bounds.items():
            lines.append(f"  {label}: {', '.join(elements)}")
    else:
        lines.append("Every laid-out element sits inside its page box.")

    for item in summary.items:
        lines.append("")
        lines.append(f"  {item.label} ({len(item.elements)} elements)")
        if item.elements_truncated:
            lines.append("    … more elements than the inspection budget allows")
        lines.extend(_format_geometry(item, verbose=verbose))

    lines.append("")
    lines.append(
        "Geometry is a percentage of the page box, so 0–100 is inside it. This "
        "is the host engine's layout, not the authoring application's: report "
        "it as a rendered-layout check, and do not claim you looked at pixels."
    )
    return "\n".join(lines)


async def _document_preview(
    path: Annotated[
        str,
        Field(
            description=(
                "Workspace path to the document to render. Supported formats "
                "are listed in the tool description."
            )
        ),
    ],
    verbose: Annotated[
        bool,
        Field(
            description=(
                "Include every element. Off by default, which reports elements "
                "carrying text plus anything outside the page box."
            )
        ),
    ] = False,
) -> str:
    """Render a document with the host viewer engine and report its layout."""

    sandbox = get_sandbox()
    resolved = sandbox.validate_path(path)
    rel = sandbox.display_path(resolved)

    if not resolved.exists():
        raise FileNotFoundError(f"Document not found: {rel}")
    if not resolved.is_file():
        raise IsADirectoryError(f"Path is not a file: {rel}")

    try:
        rendered = await asyncio.to_thread(render_document_preview, resolved)
    except DocumentPreviewUnsupportedError as exc:
        return (
            f"[Cannot preview: {rel}]\n{exc}\n"
            f"Supported formats: {_supported_suffixes()}."
        )
    except DocumentPreviewError as exc:
        return f"[Preview failed: {rel}]\n{exc}"

    # The cache root is configurable and may be relative to the process working
    # directory; the sandbox resolves relative paths against the workspace, so
    # anchor it once here before granting access or reporting it.
    preview = rendered.resolve()

    try:
        summary = await asyncio.to_thread(summarize_document_preview, preview)
    except OSError as exc:
        return f"[Preview rendered but could not be read: {rel}]\n{exc}"

    logger.debug(
        "document_preview_rendered source={} preview={} pages={}",
        resolved,
        preview,
        len(summary.items),
    )
    return _render_report(
        source=rel, preview=preview, summary=summary, verbose=verbose
    )


document_preview = Tool(
    _document_preview,
    name="document_preview",
    description=(
        "Render a workspace document with the host's read-only viewer engine "
        "and report its laid-out pages: each element's label, text, and "
        "position as a percentage of the page, with anything falling outside "
        f"the page flagged. Formats: {_supported_suffixes()}. Needs no office "
        "application and no external renderer. Use it to verify a document you "
        "produced, or to inspect the layout of one you were given."
    ),
    concurrency_safe=True,
    read_only=True,
    capabilities=("workspace_read",),
    observation_kind="source",
)
