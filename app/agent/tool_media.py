"""Materialise multimodal tool output for the chat UI.

Providers need inline image bytes in ``ToolMessage.parts``.  The browser UI
must not receive those base64 blobs through SSE, so this module writes them to
the session upload directory and returns only lightweight attachment metadata.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import unquote_to_bytes

from loguru import logger

from app.agent.schemas.chat import ContentBlock, ImageDataBlock, ImageUrlBlock
from app.core.paths import uploads_dir

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
}


async def materialize_tool_attachments(
    parts: list[ContentBlock],
    *,
    session_id: str,
    tool_name: str,
) -> list[dict[str, str]]:
    """Return UI-safe attachment metadata for image-bearing tool parts.

    Raw data blocks are persisted under the app-managed session uploads
    directory.  Ordinary HTTP(S) image URLs are kept as URLs.  Failures are
    best-effort: the original parts still reach the LLM even if a preview
    cannot be created.
    """
    return await asyncio.to_thread(
        _materialize_tool_attachments_sync,
        parts,
        session_id,
        tool_name,
    )


def _materialize_tool_attachments_sync(
    parts: list[ContentBlock],
    session_id: str,
    tool_name: str,
) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    image_index = 0

    for part in parts:
        if not isinstance(part, (ImageDataBlock, ImageUrlBlock)):
            continue

        image_index += 1
        try:
            if isinstance(part, ImageDataBlock):
                attachment = _persist_bytes(
                    base64.b64decode(part.data, validate=True),
                    media_type=part.media_type,
                    session_id=session_id,
                    tool_name=tool_name,
                    index=image_index,
                )
            elif part.url.startswith("data:"):
                raw, media_type = _decode_data_url(part.url, part.media_type)
                attachment = _persist_bytes(
                    raw,
                    media_type=media_type,
                    session_id=session_id,
                    tool_name=tool_name,
                    index=image_index,
                )
            elif part.url.startswith(("https://", "http://", "/api/")):
                media_type = part.media_type or "image/*"
                attachment = {
                    "original_name": _display_name(tool_name, image_index, media_type),
                    "media_type": media_type,
                    "category": _category(media_type),
                    "url": part.url,
                }
            else:
                logger.warning(
                    "tool_media_url_unsupported tool={} scheme={}",
                    tool_name,
                    part.url.split(":", 1)[0],
                )
                continue
        except (ValueError, binascii.Error, OSError) as exc:
            logger.warning(
                "tool_media_materialize_failed tool={} index={} error={}",
                tool_name,
                image_index,
                type(exc).__name__,
            )
            continue

        attachments.append(attachment)

    return attachments


def _decode_data_url(url: str, fallback_media_type: str | None) -> tuple[bytes, str]:
    header, separator, payload = url.partition(",")
    if not separator:
        raise ValueError("Malformed data URL")
    media_type = header[5:].split(";", 1)[0] or fallback_media_type or "image/png"
    if ";base64" in header.lower():
        return base64.b64decode(payload, validate=True), media_type
    return unquote_to_bytes(payload), media_type


def _persist_bytes(
    raw: bytes,
    *,
    media_type: str,
    session_id: str,
    tool_name: str,
    index: int,
) -> dict[str, str]:
    normalized_media_type = media_type.split(";", 1)[0].strip().lower()
    extension = _extension(normalized_media_type)
    filename = f"tool-media-{uuid.uuid4().hex}{extension}"
    destination = uploads_dir(session_id) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return {
        "filename": filename,
        "original_name": _display_name(tool_name, index, normalized_media_type),
        "media_type": normalized_media_type,
        "category": _category(normalized_media_type),
        "url": f"/api/team/{session_id}/uploads/{filename}",
    }


def _extension(media_type: str) -> str:
    known = _EXTENSIONS.get(media_type)
    if known:
        return known
    guessed = mimetypes.guess_extension(media_type, strict=False) or ".bin"
    suffix = Path(f"file{guessed}").suffix
    return suffix if suffix and suffix[1:].isalnum() else ".bin"


def _category(media_type: str) -> str:
    return "image" if media_type.startswith("image/") else "document"


def _display_name(tool_name: str, index: int, media_type: str) -> str:
    label = tool_name.replace("_", " ").strip().title() or "Tool"
    extension = _extension(media_type)
    return f"{label} image {index}{extension}"
