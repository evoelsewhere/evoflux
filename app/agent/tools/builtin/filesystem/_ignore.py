"""Shared ignore helpers for filesystem tools."""

from __future__ import annotations

import re
from fnmatch import fnmatchcase, translate
from functools import lru_cache
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
    return _matches_gitignore_pattern(
        pattern,
        rel,
        is_dir=is_dir,
        parts=tuple(rel.split("/")),
    )


@lru_cache(maxsize=2_048)
def _normalized_pattern(pattern: str) -> tuple[bool, str, bool]:
    directory_only = pattern.endswith("/")
    normalized = pattern.strip("/") if directory_only else pattern.lstrip("/")
    return directory_only, normalized, "/" in normalized


def _matches_gitignore_pattern(
    pattern: str,
    rel: str,
    *,
    is_dir: bool,
    parts: tuple[str, ...],
) -> bool:
    directory_only, normalized, contains_slash = _normalized_pattern(pattern)
    if not normalized:
        return False

    if directory_only:
        return rel == normalized if is_dir else rel.startswith(f"{normalized}/")

    if contains_slash:
        return fnmatchcase(rel, normalized) or fnmatchcase(rel, f"{normalized}/*")

    return any(fnmatchcase(part, normalized) for part in parts)


def is_gitignored(rel: str, *, is_dir: bool, rules: list[tuple[str, bool]]) -> bool:
    return _is_gitignored_cached(rel, is_dir, tuple(rules))


@lru_cache(maxsize=32_768)
def _is_gitignored_cached(
    rel: str,
    is_dir: bool,
    rules: tuple[tuple[str, bool], ...],
) -> bool:
    combined = _combined_exclusion_pattern(rules, is_dir)
    if combined is not None:
        return combined.search(rel) is not None
    ignored = False
    parts = tuple(rel.split("/"))
    for pattern, include in rules:
        if _matches_gitignore_pattern(
            pattern,
            rel,
            is_dir=is_dir,
            parts=parts,
        ):
            ignored = not include
    return ignored


@lru_cache(maxsize=128)
def _combined_exclusion_pattern(
    rules: tuple[tuple[str, bool], ...], is_dir: bool
) -> re.Pattern[str] | None:
    """Compile exclusion-only rule sets into one match for large repositories."""
    if any(include for _pattern, include in rules):
        return None
    expressions: list[str] = []
    for pattern, _include in rules:
        directory_only, normalized, contains_slash = _normalized_pattern(pattern)
        if not normalized:
            continue
        if directory_only:
            expression = re.escape(normalized)
            expressions.append(
                rf"^(?:{expression})$" if is_dir else rf"^(?:{expression})/"
            )
            continue
        translated = translate(normalized)
        if not translated.startswith("(?s:") or not translated.endswith(")\\Z"):
            return None
        body = translated[4:-3]
        if contains_slash:
            expressions.append(rf"^(?:{body})(?:/.*)?$")
        else:
            expressions.append(rf"(?:^|/)(?:{body})(?:/|$)")
    return re.compile("|".join(expressions)) if expressions else re.compile(r"(?!x)x")


def is_ignored_workspace_path(
    rel: str,
    *,
    is_dir: bool,
    rules: list[tuple[str, bool]],
) -> bool:
    """Apply the shared generated/hidden/gitignore policy to a workspace path."""
    normalized = rel.replace("\\", "/").strip("/")
    if not normalized:
        return False
    parts = tuple(part for part in normalized.split("/") if part)
    directory_parts = parts if is_dir else parts[:-1]
    if any(
        part.startswith(".") or part in _SKIPPED_DIR_NAMES for part in directory_parts
    ):
        return True
    return is_gitignored(normalized, is_dir=is_dir, rules=rules)
