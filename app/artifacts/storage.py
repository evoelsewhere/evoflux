"""Content-addressed immutable storage for candidate document revisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from uuid import UUID

from app.core.config import settings

_COPY_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredBlob:
    key: str
    sha256: str
    byte_size: int
    path: Path


class ArtifactStore:
    """Own immutable blobs and revision-scoped preview evidence."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (
            root or Path(settings.EVOFLUX_DATA_DIR) / "artifact-fabric"
        ).resolve()
        self.blob_root = self.root / "blobs"
        self.revision_root = self.root / "revisions"

    @staticmethod
    def hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(_COPY_CHUNK_BYTES), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def put(self, source: Path) -> StoredBlob:
        if not source.is_file():
            raise FileNotFoundError(f"candidate artifact does not exist: {source}")
        digest, size = self.hash_file(source)
        key = f"sha256/{digest[:2]}/{digest}"
        destination = self.blob_root / digest[:2] / digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{digest}.", suffix=".tmp", dir=destination.parent
            )
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                shutil.copyfile(source, temp_path)
                copied_digest, copied_size = self.hash_file(temp_path)
                if copied_digest != digest or copied_size != size:
                    raise OSError(
                        "candidate changed while being copied into artifact CAS"
                    )
                os.replace(temp_path, destination)
            finally:
                temp_path.unlink(missing_ok=True)
        return StoredBlob(key=key, sha256=digest, byte_size=size, path=destination)

    def resolve_blob(self, key: str) -> Path:
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "sha256" or len(parts[2]) != 64:
            raise ValueError("invalid artifact blob key")
        path = (self.blob_root / parts[1] / parts[2]).resolve()
        path.relative_to(self.blob_root.resolve())
        if not path.is_file():
            raise FileNotFoundError(f"artifact blob is missing: {key}")
        return path

    def preserve_previews(
        self, revision_id: UUID, previews: list[Path]
    ) -> list[dict[str, str]]:
        destination_dir = self.revision_root / str(revision_id) / "previews"
        destination_dir.mkdir(parents=True, exist_ok=True)
        stored: list[dict[str, str]] = []
        for index, source in enumerate(previews, start=1):
            if not source.is_file():
                continue
            suffix = source.suffix.lower() or ".png"
            destination = destination_dir / f"preview-{index:03d}{suffix}"
            shutil.copyfile(source, destination)
            digest, size = self.hash_file(destination)
            stored.append(
                {
                    "key": f"revisions/{revision_id}/previews/{destination.name}",
                    "sha256": digest,
                    "byte_size": str(size),
                    "media_type": _preview_media_type(suffix),
                }
            )
        return stored

    def resolve_preview(self, key: str) -> Path:
        path = (self.root / key).resolve()
        path.relative_to(self.revision_root.resolve())
        if not path.is_file():
            raise FileNotFoundError(f"artifact preview is missing: {key}")
        return path

    def materialize(self, key: str, destination: Path, *, expected_sha256: str) -> Path:
        """Atomically publish the exact verified blob without rebuilding it."""

        source = self.resolve_blob(key)
        actual_digest, _ = self.hash_file(source)
        if actual_digest != expected_sha256:
            raise OSError("artifact CAS integrity check failed before publish")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            shutil.copyfile(source, temp_path)
            copied_digest, _ = self.hash_file(temp_path)
            if copied_digest != expected_sha256:
                raise OSError("published artifact hash differs from verified revision")
            os.replace(temp_path, destination)
        finally:
            temp_path.unlink(missing_ok=True)
        return destination


def _preview_media_type(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


__all__ = ["ArtifactStore", "StoredBlob"]
