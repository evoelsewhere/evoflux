"""Public error and response policy contract for document previews."""

from __future__ import annotations


DOCUMENT_PREVIEW_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "connect-src 'none'; "
    "font-src data:; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "img-src data: blob:; "
    "media-src data: blob:; "
    "object-src 'none'; "
    "script-src 'none'; "
    "style-src 'unsafe-inline'"
)


class DocumentPreviewError(RuntimeError):
    """The host viewer could not render an otherwise supported document."""


class DocumentPreviewUnsupportedError(DocumentPreviewError):
    """The requested file cannot be opened by the host viewer."""


__all__ = [
    "DOCUMENT_PREVIEW_CSP",
    "DocumentPreviewError",
    "DocumentPreviewUnsupportedError",
]
