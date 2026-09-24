"""Multimodal file handlers for the ``read`` tool.

Detects file type by extension and dispatches to the appropriate handler:

- **Image** (.png, .jpg, .jpeg, .gif, .webp, .bmp, .svg): base64-encode → ImageDataBlock
- **Document** (.pdf, .html): text/Markdown conversion → TextBlock
- **Office** (.docx, .xlsx, .pptx): view-only notice; no agent-side extraction
- **Text** (everything else): read as UTF-8/Latin-1 text (existing behaviour)

Each handler returns a :class:`~app.agent.schemas.chat.ToolResult` whose
``parts`` list is set directly on ``ToolMessage.parts``.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from loguru import logger

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.services.document_text import convert_with_timeout

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_IMAGE_BYTES = 10_485_760  # 10 MB — reasonable limit for vision APIs
_MAX_READ_BYTES = 5_242_880  # 5 MB — text read cap (matches existing read tool)

# ── Extension → category mapping ─────────────────────────────────────────────

_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".ico",
        ".tiff",
        ".tif",
    }
)

_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".html",
        ".htm",
    }
)

_VIEW_ONLY_OFFICE_EXTENSIONS: frozenset[str] = frozenset({".docx", ".xlsx", ".pptx"})

# Fallback MIME types for common image extensions when mimetypes module fails
_IMAGE_MIME_FALLBACK: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


# ── Public API ────────────────────────────────────────────────────────────────


def classify_file(path: Path) -> str:
    """Classify a file for the read tool's supported intake paths."""
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTENSIONS:
        return "image"
    if ext in _DOCUMENT_EXTENSIONS:
        return "document"
    if ext in _VIEW_ONLY_OFFICE_EXTENSIONS:
        return "office"
    return "text"


def handle_image(resolved: Path, rel: Path | str) -> ToolResult:
    """Read an image file and return a ToolResult with base64-encoded ImageDataBlock.

    Args:
        resolved: Absolute resolved path to the file.
        rel: Display-relative path (string or Path) used only in labels.

    Raises:
        ValueError: If the file exceeds the image size limit.
    """
    raw = resolved.read_bytes()
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image '{rel}' is {len(raw) // 1024} KB — "
            f"exceeds the {_MAX_IMAGE_BYTES // 1024} KB limit for vision input."
        )

    ext = resolved.suffix.lower()
    media_type = mimetypes.guess_type(str(resolved))[0] or _IMAGE_MIME_FALLBACK.get(
        ext, "application/octet-stream"
    )

    b64 = base64.b64encode(raw).decode("ascii")

    return ToolResult(
        parts=[
            TextBlock(text=f"[Image: {rel}]"),
            ImageDataBlock(data=b64, media_type=media_type),
        ],
    )


def handle_document(
    resolved: Path, rel: Path | str, *, vision: bool = False
) -> ToolResult:
    """Convert a PDF or HTML document to text.

    When *vision* is ``True`` and conversion fails for a PDF, falls back to
    sending the raw bytes as an ``ImageDataBlock``.

    Args:
        resolved: Absolute resolved path to the file.
        rel: Display-relative path (string or Path) used only in labels.
        vision: Whether the current model supports vision input.
    """
    raw = resolved.read_bytes()
    ext = resolved.suffix.lower()
    media_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"

    converted = convert_with_timeout(raw, media_type, resolved.name)

    if converted is not None:
        return ToolResult(
            parts=[TextBlock(text=f"[Document: {rel}]\n{converted}")],
        )

    # Conversion failed — for PDFs with a vision model, send raw bytes
    if ext == ".pdf" and vision and len(raw) <= _MAX_IMAGE_BYTES:
        logger.info(
            "document_conversion_failed_pdf_fallback path={} size={}", rel, len(raw)
        )
        b64 = base64.b64encode(raw).decode("ascii")
        return ToolResult(
            parts=[
                TextBlock(
                    text=f"[Document: {rel}] (PDF — raw, text extraction failed)"
                ),
                ImageDataBlock(data=b64, media_type="application/pdf"),
            ],
        )

    # All fallbacks exhausted
    return ToolResult(
        parts=[
            TextBlock(
                text=(
                    f"[Document: {rel}] ({media_type}, {len(raw):,} bytes)\n"
                    f"Unable to extract text. File may be corrupted or in an unsupported format."
                )
            ),
        ],
    )
