"""Normalize JSON bodies so Python and Rust responses can be compared."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    re.ASCII,
)
# The value is volatile but its format is contract (the UI parses a naive time
# as local and a "Z" time as UTC), so the token keeps the format class:
# <ts:naive>, <ts:utc-z>, <ts:offset>, with ",frac" when there are fractional
# seconds, ",space" when the date and time are separated by a space, and
# <ts:date> for a date alone.
_TIMESTAMP = re.compile(
    r"(?<![\d-])(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:(?P<sep>[T ])\d{2}:\d{2}:\d{2}(?P<frac>\.\d+)?"
    r"(?P<zone>Z|[+-]\d{2}:?\d{2})?)?(?![\d:])",
    re.ASCII,
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
    within this call) and ISO-8601 timestamps as ``<ts:CLASS>`` (see ``_TIMESTAMP``)."""
    uuids: dict[str, int] = {}

    def uuid_sub(match: re.Match[str]) -> str:
        key = match.group(0).lower()
        return f"<uuid:{uuids.setdefault(key, len(uuids) + 1)}>"

    def scrub(text: str) -> str:
        return _TIMESTAMP.sub(_timestamp_token, _UUID.sub(uuid_sub, text))

    def walk(value: Any, path: str) -> Any:
        if isinstance(value, dict):
            # Visit keys in sorted order so <uuid:N> numbering does not depend on
            # serializer field order, which is not part of the contract.
            walked = {k: walk(value[k], f"{path}.{k}") for k in sorted(value)}
            return {k: walked[k] for k in value}
        if isinstance(value, list):
            items = [walk(v, f"{path}.*") for v in value]
            if _matches(path, rules.sort_paths):
                items.sort(key=repr)
            return items
        if isinstance(value, str):
            return scrub(value)
        return value

    return walk(obj, "$")


def _timestamp_token(match: re.Match[str]) -> str:
    if match.group("sep") is None:
        return "<ts:date>"
    zone = match.group("zone")
    parts = ["naive" if zone is None else "utc-z" if zone == "Z" else "offset"]
    if match.group("frac"):
        parts.append("frac")
    if match.group("sep") == " ":
        parts.append("space")
    return f"<ts:{','.join(parts)}>"


def _matches(path: str, patterns: frozenset[str]) -> bool:
    segments = path.split(".")
    for pattern in patterns:
        want = pattern.split(".")
        if len(want) == len(segments) and all(
            w == "*" or w == s for w, s in zip(want, segments, strict=True)
        ):
            return True
    return False
