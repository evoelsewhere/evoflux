"""Stable cache paths for repository-local ported index state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class RepositoryIndexPaths:
    root: Path
    directory: Path
    target_db: Path


def paths_for_repository(root: Path) -> RepositoryIndexPaths:
    canonical = root.expanduser().resolve()
    digest = hashlib.sha256(str(canonical).encode("utf-8", "surrogatepass")).hexdigest()
    directory = Path(settings.EVOFLUX_CACHE_DIR) / "code-index" / digest[:24]
    return RepositoryIndexPaths(
        root=canonical,
        directory=directory,
        target_db=directory / "code-context.sqlite3",
    )


__all__ = ["RepositoryIndexPaths", "paths_for_repository"]
