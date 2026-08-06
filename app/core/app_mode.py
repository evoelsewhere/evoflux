"""Canonical application-mode contract.

All external strings are normalised at an input boundary and all internal
mode decisions use :class:`AppMode`.  Keeping this tiny module independent of
the API, database, and agent runtime prevents those layers from inventing
their own mode fallbacks.
"""

from __future__ import annotations

from enum import StrEnum


class AppMode(StrEnum):
    WORK = "work"
    CODING = "coding"


_LEGACY_MODES = {"normal": AppMode.WORK, "forge": AppMode.WORK}


def parse_app_mode(value: str | AppMode) -> AppMode:
    """Return the canonical application mode or raise ``ValueError``.

    Legacy Work names are accepted only here so persistence and runtime code
    never need their own compatibility branches.
    """

    if isinstance(value, AppMode):
        return value
    normalized = value.strip().lower()
    if normalized in _LEGACY_MODES:
        return _LEGACY_MODES[normalized]
    try:
        return AppMode(normalized)
    except ValueError as exc:
        raise ValueError("mode must be 'work' or 'coding'") from exc


def normalize_app_mode(value: str | AppMode) -> str:
    """Compatibility helper for string-backed API and database fields."""

    return parse_app_mode(value).value
