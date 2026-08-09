"""Deterministic keyed-source discovery for the repository code index."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable, Iterator, Mapping, Set
from dataclasses import dataclass
from pathlib import Path

from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)

MAX_SOURCE_BYTES = 1_500_000


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One source component keyed by its repository-relative path."""

    key: str
    content: bytes
    fingerprint: str
    processor: str = ""
    language_override: str | None = None
    byte_size: int = 0
    modified_ns: int = 0
    changed_ns: int = 0
    reused: bool = False


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Persisted file identity used to avoid reading unchanged source bytes."""

    fingerprint: str
    byte_size: int
    processor: str
    modified_ns: int
    changed_ns: int


def fingerprint_source(content: bytes, processor: str = "") -> str:
    """Hash source plus the pipeline format so code changes trigger reconciliation."""
    digest = hashlib.sha256()
    digest.update(b"evoflux-code-context\0")
    digest.update(processor.encode("utf-8", "replace"))
    digest.update(b"\0")
    digest.update(content)
    return digest.hexdigest()


def _record(
    root: Path,
    relative: str,
    *,
    max_bytes: int,
    processor: str = "",
    language_override: str | None = None,
    known: SourceMetadata | None = None,
    force_read: bool = False,
) -> SourceRecord | None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
        status = path.stat()
        if not path.is_file() or status.st_size > max_bytes:
            return None
        if (
            not force_read
            and known is not None
            and known.processor == processor
            and known.byte_size == status.st_size
            and known.modified_ns == status.st_mtime_ns
            and known.changed_ns == status.st_ctime_ns
        ):
            return SourceRecord(
                relative,
                b"",
                known.fingerprint,
                processor,
                language_override,
                status.st_size,
                status.st_mtime_ns,
                status.st_ctime_ns,
                True,
            )
        content = path.read_bytes()
        if len(content) > max_bytes:
            return None
    except (OSError, ValueError):
        return None
    return SourceRecord(
        relative,
        content,
        fingerprint_source(content, processor),
        processor,
        language_override,
        len(content),
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _scoped_rules(root: Path, directory: Path) -> list[tuple[str, bool]]:
    """Load one .gitignore and anchor its rules to the owning directory."""
    prefix = directory.relative_to(root).as_posix()
    if prefix == ".":
        prefix = ""
    output: list[tuple[str, bool]] = []
    for pattern, include in load_gitignore_rules(directory):
        anchored = pattern.startswith("/")
        body = pattern.lstrip("/")
        base = f"{prefix}/" if prefix else ""
        if anchored or "/" in body:
            output.append((f"{base}{body}", include))
        else:
            output.append((f"{base}{body}", include))
            output.append((f"{base}**/{body}", include))
    return output


def _rules_for_path(root: Path, relative: str) -> list[tuple[str, bool]]:
    rules: list[tuple[str, bool]] = []
    directory = root
    rules.extend(_scoped_rules(root, directory))
    for part in Path(relative).parts[:-1]:
        directory /= part
        rules.extend(_scoped_rules(root, directory))
    return rules


def read_source_records(
    root: Path,
    relative_paths: Iterable[str],
    *,
    extensions: Set[str],
    max_bytes: int = MAX_SOURCE_BYTES,
) -> Iterator[SourceRecord]:
    """Read explicitly named supported source components that still exist."""
    canonical = root.expanduser().resolve()
    for raw in relative_paths:
        relative = raw.replace("\\", "/").strip("/")
        path = Path(relative)
        if (
            not relative
            or path.is_absolute()
            or ".." in path.parts
            or path.suffix.lower() not in extensions
            or is_ignored_workspace_path(
                relative,
                is_dir=False,
                rules=_rules_for_path(canonical, relative),
            )
        ):
            continue
        record = _record(canonical, relative, max_bytes=max_bytes)
        if record is not None:
            yield record


def walk_source_records(
    root: Path,
    *,
    extensions: Set[str],
    max_bytes: int = MAX_SOURCE_BYTES,
    include: Callable[[str], bool] | None = None,
    processor_for: Callable[[str], tuple[str, str | None]] | None = None,
    known_sources: Mapping[str, SourceMetadata] | None = None,
    force_read: bool = False,
) -> Iterator[SourceRecord]:
    """Yield a sorted, gitignore-aware snapshot with stable component keys."""
    canonical = root.expanduser().resolve()
    inherited: dict[Path, list[tuple[str, bool]]] = {canonical: []}
    for current_root, dirs, files in os.walk(canonical):
        current = Path(current_root)
        rules = [*inherited.get(current, ()), *_scoped_rules(canonical, current)]
        for directory in dirs:
            inherited[current / directory] = rules
        dirs[:] = sorted(
            directory
            for directory in dirs
            if not is_ignored_workspace_path(
                (current / directory).relative_to(canonical).as_posix(),
                is_dir=True,
                rules=rules,
            )
        )
        for filename in sorted(files):
            path = current / filename
            if filename.startswith(".") or path.suffix.lower() not in extensions:
                continue
            relative = path.relative_to(canonical).as_posix()
            if include is not None and not include(relative):
                continue
            if is_ignored_workspace_path(relative, is_dir=False, rules=rules):
                continue
            processor, override = (
                processor_for(relative) if processor_for else ("", None)
            )
            record = _record(
                canonical,
                relative,
                max_bytes=max_bytes,
                processor=processor,
                language_override=override,
                known=known_sources.get(relative) if known_sources else None,
                force_read=force_read,
            )
            if record is not None:
                yield record


__all__ = [
    "MAX_SOURCE_BYTES",
    "SourceMetadata",
    "SourceRecord",
    "fingerprint_source",
    "read_source_records",
    "walk_source_records",
]
