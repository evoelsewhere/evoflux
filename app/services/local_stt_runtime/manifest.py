"""Pinned, platform-specific assets for the optional local STT runtime.

Release assets are populated only after the matching CI build succeeds. Until
then the feature is unavailable and configured remote providers keep working.
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

RUNTIME_ID = "local-stt"
MODEL_ID = "faster-whisper-small-multilingual"
MODEL_REVISION = "2ec96c5472da50d38d40c0cfe0602af2e94b4c8a"
MANIFEST_OVERRIDE_ENV = "EVOFLUX_LOCAL_STT_MANIFEST"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024

# These stay empty until the release workflow has built and verified every
# artifact. Never insert guessed URLs, sizes, or hashes here.
PINNED_RUNTIME_ASSETS: dict[str, dict[str, Any]] = {}
PINNED_MODEL_ASSET: dict[str, Any] = {}


class RuntimeManifestError(ValueError):
    """A manifest entry is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class RuntimeAsset:
    kind: str
    platform: str
    version: str
    url: str
    sha256: str
    size: int
    root: str
    installed_size: int | None = None


def platform_key() -> str | None:
    machine = platform.machine().lower()
    arch = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine)
    system = {"win32": "win32", "darwin": "darwin", "linux": "linux"}.get(
        sys.platform
    )
    if arch is None or system is None:
        return None
    key = f"{system}-{arch}"
    return key if key in {"win32-x64", "darwin-x64", "darwin-arm64", "linux-x64"} else None


def _safe_root(value: str, kind: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    expected = "runtime" if kind == "runtime" else "model"
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] != expected
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise RuntimeManifestError(f"Asset root must stay under {expected}/")
    return path.as_posix()


def parse_asset(
    kind: str,
    platform_name: str,
    record: dict[str, Any],
    *,
    allow_file_urls: bool = False,
) -> RuntimeAsset:
    if kind not in {"runtime", "model"}:
        raise RuntimeManifestError("Unknown local STT asset kind")
    try:
        version = str(record["version"])
        url = str(record["url"])
        sha256 = str(record["sha256"]).lower()
        size = int(record["size"])
        root = _safe_root(str(record["root"]), kind)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeManifestError(f"Malformed local STT asset: {exc}") from exc
    if not _VERSION.fullmatch(version):
        raise RuntimeManifestError("Local STT version is not a safe identifier")
    if not _SHA256.fullmatch(sha256):
        raise RuntimeManifestError("Local STT SHA-256 must be 64 hex characters")
    if not 0 < size <= _MAX_ASSET_BYTES:
        raise RuntimeManifestError("Local STT archive size is out of range")
    scheme = urlparse(url).scheme
    parsed = urlparse(url)
    if scheme != "https" and not (allow_file_urls and scheme == "file"):
        raise RuntimeManifestError("Local STT assets are fetched over HTTPS")
    if scheme == "https" and (not parsed.hostname or parsed.username or parsed.password):
        raise RuntimeManifestError("Local STT HTTPS assets require a public host without embedded credentials")
    if parsed.fragment:
        raise RuntimeManifestError("Local STT asset URLs cannot contain fragments")
    try:
        installed_size = int(record["installedSize"])
    except (KeyError, TypeError, ValueError):
        installed_size = None
    if installed_size is not None and not 0 < installed_size <= 8 * _MAX_ASSET_BYTES:
        installed_size = None
    return RuntimeAsset(
        kind=kind,
        platform=platform_name,
        version=version,
        url=url,
        sha256=sha256,
        size=size,
        root=root,
        installed_size=installed_size,
    )


def _override() -> dict[str, Any] | None:
    raw = os.environ.get(MANIFEST_OVERRIDE_ENV, "").strip()
    if not raw:
        return None
    try:
        value = json.loads(Path(raw).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("local_stt_manifest_override_unreadable error={}", exc)
        return None
    return value if isinstance(value, dict) else None


def current_assets() -> tuple[RuntimeAsset, RuntimeAsset] | None:
    key = platform_key()
    if key is None:
        return None
    override = _override()
    if override is not None:
        runtime_record = dict(override.get("runtime_assets") or {}).get(key)
        model_record = override.get("model_asset")
        allow_file_urls = True
    else:
        runtime_record = PINNED_RUNTIME_ASSETS.get(key)
        model_record = PINNED_MODEL_ASSET or None
        allow_file_urls = False
    if not isinstance(runtime_record, dict) or not isinstance(model_record, dict):
        return None
    try:
        return (
            parse_asset("runtime", key, runtime_record, allow_file_urls=allow_file_urls),
            parse_asset("model", "all", model_record, allow_file_urls=allow_file_urls),
        )
    except RuntimeManifestError as exc:
        logger.warning("local_stt_manifest_rejected platform={} error={}", key, exc)
        return None


__all__ = [
    "MANIFEST_OVERRIDE_ENV",
    "MODEL_ID",
    "MODEL_REVISION",
    "PINNED_MODEL_ASSET",
    "PINNED_RUNTIME_ASSETS",
    "RUNTIME_ID",
    "RuntimeAsset",
    "RuntimeManifestError",
    "current_assets",
    "parse_asset",
    "platform_key",
]
