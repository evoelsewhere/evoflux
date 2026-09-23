"""Pinned description of the downloadable LibreOffice rendering runtime.

The runtime is a trimmed LibreOffice build that the EvoFlux team packages and
publishes (see ``scripts/build_libreoffice_runtime.py``). The sidecar only
installs an archive whose SHA-256 and size match the asset pinned in this
file, so a compromised mirror or release page cannot substitute a different
binary: the pin ships inside the (signed) application itself.

``PINNED_ASSETS`` stays empty until a bundle is published; the viewer then
reports the runtime as unavailable and keeps using the built-in HTML
renderers. ``EVOFLUX_OFFICE_RUNTIME_MANIFEST`` may point at a JSON file with
the same shape (``{"assets": {...}}``) to test a locally built bundle; it
still has to pass the same checksum checks.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from loguru import logger

RUNTIME_ID = "libreoffice"
RUNTIME_ROOT = "soffice"
MANIFEST_OVERRIDE_ENV = "EVOFLUX_OFFICE_RUNTIME_MANIFEST"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024

#: platform key -> asset record (same shape as the override manifest).
PINNED_ASSETS: dict[str, dict[str, Any]] = {}


class RuntimeManifestError(ValueError):
    """A manifest entry is malformed."""


@dataclass(frozen=True, slots=True)
class RuntimeAsset:
    """One verified, installable runtime archive for a single platform."""

    platform: str
    version: str
    url: str
    sha256: str
    size: int
    executable: str
    #: Disk space the extracted runtime takes. Display-only: a wrong value can
    #: only misstate the size, never change what installs.
    installed_size: int | None = None


def platform_key() -> str | None:
    """Return the runtime platform key for this machine, if one is supported."""
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    system = {"win32": "win32", "darwin": "darwin", "linux": "linux"}.get(sys.platform)
    if arch is None or system is None:
        return None
    return f"{system}-{arch}"


def _load_override() -> dict[str, Any] | None:
    raw = os.environ.get(MANIFEST_OVERRIDE_ENV, "").strip()
    if not raw:
        return None
    try:
        data = json.loads(Path(raw).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("office_runtime_manifest_override_unreadable error={}", exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def _safe_executable(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    parts = path.parts
    if (
        not parts
        or parts[0] != RUNTIME_ROOT
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise RuntimeManifestError("Runtime executable must live under soffice/")
    return path.as_posix()


def parse_asset(
    platform_name: str,
    record: dict[str, Any],
    *,
    allow_file_urls: bool = False,
) -> RuntimeAsset:
    """Validate one manifest record."""
    try:
        version = str(record["version"])
        url = str(record["url"])
        sha256 = str(record["sha256"]).lower()
        size = int(record["size"])
        executable = _safe_executable(str(record["executable"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeManifestError(f"Malformed runtime asset: {exc}") from exc
    if not _VERSION.fullmatch(version):
        raise RuntimeManifestError("Runtime version is not a safe identifier")
    if not _SHA256.fullmatch(sha256):
        raise RuntimeManifestError("Runtime sha256 must be 64 hex characters")
    if not 0 < size <= _MAX_ARCHIVE_BYTES:
        raise RuntimeManifestError("Runtime archive size is out of range")
    scheme = urlparse(url).scheme
    if scheme != "https" and not (allow_file_urls and scheme == "file"):
        raise RuntimeManifestError("Runtime archives are only fetched over HTTPS")
    try:
        installed_size = int(record["installedSize"])
    except (KeyError, TypeError, ValueError):
        installed_size = None
    if installed_size is not None and not 0 < installed_size <= 16 * _MAX_ARCHIVE_BYTES:
        installed_size = None
    return RuntimeAsset(
        platform=platform_name,
        version=version,
        url=url,
        sha256=sha256,
        size=size,
        executable=executable,
        installed_size=installed_size,
    )


def current_asset() -> RuntimeAsset | None:
    """Return the verified asset for this platform, or ``None`` if unavailable."""
    key = platform_key()
    if key is None:
        return None
    override = _load_override()
    if override is not None:
        record = dict(override.get("assets") or {}).get(key)
        allow_file_urls = True
    else:
        record = PINNED_ASSETS.get(key)
        allow_file_urls = False
    if not record:
        return None
    try:
        return parse_asset(key, record, allow_file_urls=allow_file_urls)
    except RuntimeManifestError as exc:
        logger.warning(
            "office_runtime_manifest_rejected platform={} error={}", key, exc
        )
        return None


__all__ = [
    "MANIFEST_OVERRIDE_ENV",
    "PINNED_ASSETS",
    "RUNTIME_ID",
    "RUNTIME_ROOT",
    "RuntimeAsset",
    "RuntimeManifestError",
    "current_asset",
    "parse_asset",
    "platform_key",
]
