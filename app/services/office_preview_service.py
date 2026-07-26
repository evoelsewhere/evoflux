"""High-fidelity, cached HTML previews for OpenXML workspace documents."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from loguru import logger

from app.core.config import settings

SUPPORTED_OFFICE_PREVIEW_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})
MAX_OFFICE_PREVIEW_BYTES = 100 * 1024 * 1024
OFFICE_PREVIEW_CSP = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "connect-src 'none'; "
    "font-src data:; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "img-src data: blob:; "
    "media-src data: blob:; "
    "object-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'"
)

_CACHE_SCHEMA_VERSION = "officecli-html-v1"
_render_lock = threading.Lock()


class OfficePreviewError(RuntimeError):
    """Base class for office preview failures."""


class OfficePreviewUnavailableError(OfficePreviewError):
    """Raised when the bundled renderer cannot be located."""


class OfficePreviewUnsupportedError(OfficePreviewError):
    """Raised when the requested file cannot be rendered safely."""


def _officecli_binary() -> str:
    binary = shutil.which("officecli")
    if binary:
        return binary
    dev_name = "officecli.exe" if sys.platform == "win32" else "officecli"
    dev_binary = (
        Path(__file__).resolve().parents[2]
        / "desktop"
        / "sidecar-bundle"
        / "bin"
        / dev_name
    )
    if dev_binary.is_file():
        return str(dev_binary)
    raise OfficePreviewUnavailableError(
        "Office preview renderer is unavailable in this installation."
    )


def _cache_path(source: Path) -> Path:
    stat = source.stat()
    fingerprint = "\0".join(
        (
            _CACHE_SCHEMA_VERSION,
            str(source.resolve()),
            str(stat.st_size),
            str(stat.st_mtime_ns),
        )
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    return Path(settings.EVOFLUX_CACHE_DIR) / "office-previews" / f"{digest}.html"


def _inject_preview_policy(html: str) -> str:
    """Add an in-document CSP so it survives fetch → iframe ``srcDoc``."""
    policy = (
        f'<meta http-equiv="Content-Security-Policy" content="{OFFICE_PREVIEW_CSP}">'
        '<meta name="referrer" content="no-referrer">'
    )
    marker = "<head>"
    if marker in html:
        return html.replace(marker, marker + policy, 1)
    return policy + html


def render_office_preview(source: Path) -> Path:
    """Render ``source`` to a cached, self-contained HTML document."""
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_OFFICE_PREVIEW_EXTENSIONS:
        raise OfficePreviewUnsupportedError(
            f"{suffix or 'This file type'} is not supported for Office preview."
        )
    if source.stat().st_size > MAX_OFFICE_PREVIEW_BYTES:
        raise OfficePreviewUnsupportedError(
            f"Office preview is limited to {MAX_OFFICE_PREVIEW_BYTES // (1024 * 1024)} MB."
        )

    output = _cache_path(source)
    if output.is_file():
        return output

    with _render_lock:
        if output.is_file():
            return output
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        binary = _officecli_binary()
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            completed = subprocess.run(
                [binary, "view", str(source), "html", "-o", str(temporary)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            temporary.unlink(missing_ok=True)
            raise OfficePreviewError(
                f"Could not start the Office renderer: {exc}"
            ) from exc
        if completed.returncode != 0 or not temporary.is_file():
            temporary.unlink(missing_ok=True)
            detail = (
                completed.stderr or completed.stdout or "Unknown renderer error"
            ).strip()
            logger.warning(
                "office_preview_render_failed file={} returncode={} detail={}",
                source.name,
                completed.returncode,
                detail[:500],
            )
            raise OfficePreviewError(f"Could not render this document: {detail}")

        try:
            rendered = temporary.read_text(encoding="utf-8")
            temporary.write_text(_inject_preview_policy(rendered), encoding="utf-8")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    return output
