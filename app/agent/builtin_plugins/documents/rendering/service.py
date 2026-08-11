"""Portable document rendering without external applications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent.builtin_plugins.documents.rendering.internal import (
    render_docx_pages,
    render_pdf_pages,
    render_pptx_pages,
    render_xlsx_file,
)


def renderer_available() -> bool:
    """The internal renderer ships with the Python sidecar on every platform."""
    return True


def render_pages(
    source: Path,
    render_dir: Path,
    *,
    code_prefix: str,
    dpi: int = 144,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Render a supported document and return deterministic PNG evidence."""
    try:
        suffix = source.suffix.lower()
        if suffix == ".docx":
            pages = render_docx_pages(source, render_dir, dpi=dpi)
        elif suffix == ".pptx":
            pages = render_pptx_pages(source, render_dir)
        elif suffix == ".xlsx":
            pages = render_xlsx_file(source, render_dir)
        elif suffix == ".pdf":
            pages = render_pdf_pages(source, render_dir, dpi=dpi)
        else:
            raise ValueError(f"unsupported render format: {suffix or source.name}")
    except Exception as exc:  # noqa: BLE001 - rendering failures become QA issues
        return [], [
            {
                "severity": "error",
                "code": f"{code_prefix}-render-failed",
                "message": str(exc),
            }
        ]
    if not pages:
        return [], [
            {
                "severity": "error",
                "code": f"{code_prefix}-render-empty",
                "message": "internal renderer produced no pages",
            }
        ]
    return pages, []


__all__ = ["render_pages", "renderer_available"]
