"""Repository-local code-index settings."""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_EXCLUDED_PATTERNS: tuple[str, ...] = (
    "**/.*",
    "**/__pycache__",
    "**/node_modules",
    "**/target",
    "**/build/assets",
    "**/dist",
    "**/vendor/*.*/*",
    "**/vendor/*",
    "**/.code-index",
)


@dataclass(frozen=True, slots=True)
class LanguageOverride:
    ext: str
    lang: str


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = DEFAULT_EXCLUDED_PATTERNS
    language_overrides: tuple[LanguageOverride, ...] = ()
    max_file_size: int | None = None
    warnings: tuple[str, ...] = ()
    digest: str = "default"

    def language_for(self, path: str) -> str | None:
        extension = Path(path).suffix.casefold().lstrip(".")
        return next(
            (item.lang for item in self.language_overrides if item.ext == extension),
            None,
        )

    def includes(self, path: str) -> bool:
        normalized = path.replace("\\", "/").strip("/")
        if self.include_patterns and not any(
            _matches(normalized, pattern) for pattern in self.include_patterns
        ):
            return False
        return not any(
            _matches(normalized, pattern) for pattern in self.exclude_patterns
        )


def load_project_settings(root: Path) -> ProjectSettings:
    """Load ``.code-index/settings.yml`` without executing repository code."""
    path = root / ".code-index" / "settings.yml"
    if not path.is_file():
        return ProjectSettings()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read code-index settings: {exc}") from exc
    try:
        value = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid code-index settings: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Code-index settings must be a YAML mapping.")
    warnings: list[str] = []
    if value.get("chunkers"):
        warnings.append(
            "Custom executable chunkers are ignored: repository settings cannot "
            "execute Python during indexing."
        )
    includes = _strings(value.get("include_patterns"), "include_patterns")
    excludes_value = value.get("exclude_patterns")
    excludes = (
        _strings(excludes_value, "exclude_patterns")
        if excludes_value is not None
        else DEFAULT_EXCLUDED_PATTERNS
    )
    overrides_value = value.get("language_overrides")
    if overrides_value is not None and not isinstance(overrides_value, list):
        raise ValueError("language_overrides must be a list.")
    overrides: list[LanguageOverride] = []
    for item in overrides_value or []:
        if not isinstance(item, dict) or not item.get("ext") or not item.get("lang"):
            raise ValueError("Each language override requires 'ext' and 'lang'.")
        overrides.append(
            LanguageOverride(
                ext=str(item["ext"]).casefold().lstrip("."),
                lang=str(item["lang"]).casefold(),
            )
        )
    maximum = value.get("max_file_size")
    if maximum is not None and (
        isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1
    ):
        raise ValueError("max_file_size must be a positive integer or null.")
    return ProjectSettings(
        include_patterns=includes,
        exclude_patterns=excludes,
        language_overrides=tuple(overrides),
        max_file_size=maximum,
        warnings=tuple(warnings),
        digest=hashlib.sha256(raw).hexdigest(),
    )


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
    return tuple(item for item in value if item.strip())


def _matches(path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").strip("/")
    candidates = (normalized, normalized.removeprefix("**/"))
    if any(fnmatch.fnmatchcase(path, item) for item in candidates):
        return True
    parts = path.split("/")
    return any(
        fnmatch.fnmatchcase("/".join(parts[:index]), item.rstrip("/"))
        for item in candidates
        for index in range(1, len(parts) + 1)
    )


__all__ = ["LanguageOverride", "ProjectSettings", "load_project_settings"]
