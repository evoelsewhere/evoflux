"""Shared ignore helpers for filesystem tools."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

_SKIPPED_DIR_NAMES = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
    }
)


def load_gitignore_rules(root: Path) -> list[tuple[str, bool]]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    rules: list[tuple[str, bool]] = []
    for line in lines:
        pattern = line.strip()
        if not pattern or pattern.startswith("#"):
            continue
        include = pattern.startswith("!")
        if include:
            pattern = pattern[1:].strip()
        if pattern:
            rules.append((pattern, include))
    return rules


def matches_gitignore_pattern(pattern: str, rel: str, *, is_dir: bool) -> bool:
    directory_only = pattern.endswith("/")
    pattern = pattern.strip("/") if directory_only else pattern.lstrip("/")
    if not pattern:
        return False

    if directory_only:
        return rel == pattern if is_dir else rel.startswith(f"{pattern}/")

    if "/" in pattern:
        return fnmatchcase(rel, pattern) or fnmatchcase(rel, f"{pattern}/*")

    parts = rel.split("/")
    return any(fnmatchcase(part, pattern) for part in parts)


def is_gitignored(rel: str, *, is_dir: bool, rules: list[tuple[str, bool]]) -> bool:
    ignored = False
    for pattern, include in rules:
        if matches_gitignore_pattern(pattern, rel, is_dir=is_dir):
            ignored = not include
    return ignored
