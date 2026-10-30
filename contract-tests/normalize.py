"""Normalize JSON bodies so Python and Rust responses can be compared."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)


@dataclass(frozen=True)
class NormalizeRules:
    """``sort_paths`` names JSON paths (``$.items``, ``$.a.b``) whose lists are
    sorted. Every other list keeps its order, because order is part of the
    contract. ``*`` matches any object key or list index at that position."""

    sort_paths: frozenset[str] = field(default_factory=frozenset)


DEFAULT = NormalizeRules()


def normalize(obj: Any, rules: NormalizeRules = DEFAULT) -> Any:
    """Return ``obj`` with UUIDs as ``<uuid:N>`` (numbered by first appearance
    within this call) and ISO-8601 timestamps as ``<ts>``."""
    uuids: dict[str, int] = {}

    def uuid_sub(match: re.Match[str]) -> str:
        key = match.group(0).lower()
        return f"<uuid:{uuids.setdefault(key, len(uuids) + 1)}>"

    def scrub(text: str) -> str:
        return _TIMESTAMP.sub("<ts>", _UUID.sub(uuid_sub, text))

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in value.items()}
        if isinstance(value, list):
            items = [walk(v, f"{path}.*") for v in value]
            if _matches(path, rules.sort_paths):
                items.sort(key=repr)
            return items
        if isinstance(value, str):
            return scrub(value)
        return value

    return walk(obj, "$")


def _matches(path: str, patterns: frozenset[str]) -> bool:
    segments = path.split(".")
    for pattern in patterns:
        want = pattern.split(".")
        if len(want) == len(segments) and all(
            w == "*" or w == s for w, s in zip(want, segments, strict=True)
        ):
            return True
    return False
