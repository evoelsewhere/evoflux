"""Stable keyed local-source snapshots shared by all code indexes."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator, Set
from dataclasses import dataclass
from pathlib import Path

from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)

MAX_SOURCE_BYTES = 1_500_000
INDEX_FORMAT_VERSION = "9"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One source component keyed by canonical repository-relative path."""

    key: str
    content: bytes
    fingerprint: str


def index_format_tag(format_version: str = INDEX_FORMAT_VERSION) -> str:
    payload = f"evoflux-codeindex:{format_version}".encode()
    return hashlib.sha256(payload).hexdigest()[:8]


def fingerprint_source(
    content: bytes, format_version: str = INDEX_FORMAT_VERSION
) -> str:
    """Fingerprint content and the parser/index format in a fixed DB width."""
    return index_format_tag(format_version) + hashlib.sha256(content).hexdigest()[8:]


def _record(root: Path, relative: str, *, max_bytes: int) -> SourceRecord | None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return None
        content = path.read_bytes()
    except OSError:
        return None
    return SourceRecord(
        key=relative,
        content=content,
        fingerprint=fingerprint_source(content),
    )


def read_source_records(
    root: Path,
    relative_paths: Iterable[str],
    *,
    extensions: Set[str],
    max_bytes: int = MAX_SOURCE_BYTES,
) -> Iterator[SourceRecord]:
    """Read explicitly named, supported components that still exist."""
    rules = load_gitignore_rules(root)
    for raw in relative_paths:
        relative = raw.replace("\\", "/").strip("/")
        parts = Path(relative).parts
        if (
            not relative
            or ".." in parts
            or Path(relative).is_absolute()
            or Path(relative).suffix.lower() not in extensions
        ):
            continue
        if is_ignored_workspace_path(relative, is_dir=False, rules=rules):
            continue
        record = _record(root, relative, max_bytes=max_bytes)
        if record is not None:
            yield record


def walk_source_records(
    root: Path,
    *,
    extensions: Set[str],
    max_bytes: int = MAX_SOURCE_BYTES,
) -> Iterator[SourceRecord]:
    """Walk a repository into deterministic, stable keyed source records."""
    rules = load_gitignore_rules(root)
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not is_ignored_workspace_path(
                (current / directory).relative_to(root).as_posix(),
                is_dir=True,
                rules=rules,
            )
        )
        for filename in sorted(files):
            if (
                filename.startswith(".")
                or Path(filename).suffix.lower() not in extensions
            ):
                continue
            path = current / filename
            relative = path.relative_to(root).as_posix()
            if is_ignored_workspace_path(relative, is_dir=False, rules=rules):
                continue
            record = _record(root, relative, max_bytes=max_bytes)
            if record is not None:
                yield record


__all__ = [
    "INDEX_FORMAT_VERSION",
    "MAX_SOURCE_BYTES",
    "SourceRecord",
    "fingerprint_source",
    "index_format_tag",
    "read_source_records",
    "walk_source_records",
]
