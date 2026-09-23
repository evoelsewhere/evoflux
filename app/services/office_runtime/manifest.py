"""Pinned description of the downloadable LibreOffice rendering runtime.

The runtime is a trimmed LibreOffice build that the EvoFlux team packages and
publishes (see ``scripts/build_libreoffice_runtime.py``). The sidecar only
installs an archive whose SHA-256 and size match the pinned asset *and* whose
asset record carries a valid ed25519 signature from a pinned public key, so a
compromised mirror or release page cannot substitute a different binary.

``PINNED_ASSETS`` and ``TRUSTED_KEYS`` stay empty until a signed bundle is
published; the viewer then reports the runtime as unavailable and keeps using
the built-in HTML renderers. ``EVOFLUX_OFFICE_RUNTIME_MANIFEST`` may point at a
JSON file with the same shape (``{"keys": {...}, "assets": {...}}``) to test a
locally built bundle; it still has to pass the same signature checks.
"""

from __future__ import annotations

import base64
import binascii
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
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024

#: key id -> PEM-encoded ed25519 public key. Populated by the release process.
TRUSTED_KEYS: dict[str, str] = {}

#: platform key -> asset record (same shape as the override manifest).
PINNED_ASSETS: dict[str, dict[str, Any]] = {}


class RuntimeManifestError(ValueError):
    """A manifest entry is malformed or its signature does not verify."""


@dataclass(frozen=True, slots=True)
class RuntimeAsset:
    """One verified, installable runtime archive for a single platform."""

    platform: str
    version: str
    url: str
    sha256: str
    size: int
    key_id: str
    signature: bytes
    executable: str

    def signed_record(self) -> bytes:
        return signed_record(
            platform=self.platform,
            version=self.version,
            sha256=self.sha256,
            size=self.size,
            key_id=self.key_id,
            executable=self.executable,
        )


def signed_record(
    *,
    platform: str,
    version: str,
    sha256: str,
    size: int,
    key_id: str,
    executable: str,
) -> bytes:
    """Canonical bytes covered by an asset signature.

    The URL is deliberately excluded: an asset may move between mirrors, but
    its content (hash and size) and identity may not change.
    """
    return json.dumps(
        {
            "id": RUNTIME_ID,
            "platform": platform,
            "version": version,
            "sha256": sha256,
            "size": size,
            "keyId": key_id,
            "executable": executable,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


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


def _verify_signature(asset: RuntimeAsset, keys: dict[str, str]) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pem = keys.get(asset.key_id)
    if not pem:
        raise RuntimeManifestError(f"Unknown signing key: {asset.key_id}")
    try:
        key = load_pem_public_key(pem.encode("ascii"))
    except ValueError as exc:
        raise RuntimeManifestError("Signing key is not a valid PEM key") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise RuntimeManifestError("Signing key is not an ed25519 key")
    try:
        key.verify(asset.signature, asset.signed_record())
    except InvalidSignature as exc:
        raise RuntimeManifestError("Runtime asset signature does not verify") from exc


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
    keys: dict[str, str],
    *,
    allow_file_urls: bool = False,
) -> RuntimeAsset:
    """Validate one manifest record and verify its signature."""
    try:
        version = str(record["version"])
        url = str(record["url"])
        sha256 = str(record["sha256"]).lower()
        size = int(record["size"])
        key_id = str(record["keyId"])
        signature = base64.b64decode(str(record["signature"]), validate=True)
        executable = _safe_executable(str(record["executable"]))
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise RuntimeManifestError(f"Malformed runtime asset: {exc}") from exc
    if not _VERSION.fullmatch(version):
        raise RuntimeManifestError("Runtime version is not a safe identifier")
    if not _SHA256.fullmatch(sha256):
        raise RuntimeManifestError("Runtime sha256 must be 64 hex characters")
    if not 0 < size <= _MAX_ARCHIVE_BYTES:
        raise RuntimeManifestError("Runtime archive size is out of range")
    if not _KEY_ID.fullmatch(key_id):
        raise RuntimeManifestError("Runtime key id is not a safe identifier")
    scheme = urlparse(url).scheme
    if scheme != "https" and not (allow_file_urls and scheme == "file"):
        raise RuntimeManifestError("Runtime archives are only fetched over HTTPS")
    asset = RuntimeAsset(
        platform=platform_name,
        version=version,
        url=url,
        sha256=sha256,
        size=size,
        key_id=key_id,
        signature=signature,
        executable=executable,
    )
    _verify_signature(asset, keys)
    return asset


def current_asset() -> RuntimeAsset | None:
    """Return the verified asset for this platform, or ``None`` if unavailable."""
    key = platform_key()
    if key is None:
        return None
    override = _load_override()
    if override is not None:
        keys = {**TRUSTED_KEYS, **dict(override.get("keys") or {})}
        record = dict(override.get("assets") or {}).get(key)
        allow_file_urls = True
    else:
        keys = TRUSTED_KEYS
        record = PINNED_ASSETS.get(key)
        allow_file_urls = False
    if not record:
        return None
    try:
        return parse_asset(key, record, keys, allow_file_urls=allow_file_urls)
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
    "TRUSTED_KEYS",
    "RuntimeAsset",
    "RuntimeManifestError",
    "current_asset",
    "parse_asset",
    "platform_key",
    "signed_record",
]
