"""Small format-neutral helpers shared by document engines."""

from __future__ import annotations

import hashlib
from pathlib import Path

_HASH_CHUNK_BYTES = 1024 * 1024


def file_sha256(path: Path) -> str:
    """Hash a file in bounded chunks so large OOXML packages stay streamable."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["file_sha256"]
