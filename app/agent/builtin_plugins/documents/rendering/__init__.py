"""Document QA and preview rendering owned by the Documents plugin."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent.builtin_plugins.documents.rendering.internal import (
        render_docx_pages,
        render_pdf_pages,
        render_pptx_pages,
        render_xlsx_file,
        render_xlsx_workbook,
    )
    from app.agent.builtin_plugins.documents.rendering.runtime import file_sha256
    from app.agent.builtin_plugins.documents.rendering.service import (
        render_pages,
        renderer_available,
    )

_EXPORT_MODULES = {
    "file_sha256": "runtime",
    "render_docx_pages": "internal",
    "render_pages": "service",
    "render_pdf_pages": "internal",
    "render_pptx_pages": "internal",
    "render_xlsx_file": "internal",
    "render_xlsx_workbook": "internal",
    "renderer_available": "service",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "file_sha256",
    "render_docx_pages",
    "render_pages",
    "render_pdf_pages",
    "render_pptx_pages",
    "render_xlsx_file",
    "render_xlsx_workbook",
    "renderer_available",
]
