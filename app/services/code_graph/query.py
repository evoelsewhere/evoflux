"""Identifier token expansion used by indexed human-facing symbol search."""

from __future__ import annotations

import re

# ``[^\W\d]`` is the Unicode-aware equivalent of "letter or underscore".
# Code identifiers are not ASCII-only (Python, Java, Kotlin, Swift, and most
# modern languages accept Unicode identifiers), so restricting this expansion
# to ``A-Z`` silently made those symbols undiscoverable through FTS.
_WORD_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)


def _identifier_parts(value: str) -> tuple[str, ...]:
    parts: list[str] = []
    for segment in value.split("_"):
        if not segment:
            continue
        current: list[str] = []
        for index, char in enumerate(segment):
            previous = segment[index - 1] if index else ""
            following = segment[index + 1] if index + 1 < len(segment) else ""
            boundary = bool(
                current
                and char.isupper()
                and (
                    previous.islower()
                    or previous.isdigit()
                    or (previous.isupper() and following.islower())
                )
            )
            if boundary:
                parts.append("".join(current))
                current = []
            current.append(char)
        if current:
            parts.append("".join(current))
    return tuple(parts)


def identifier_search_text(*values: str | None) -> str:
    """Return FTS-friendly full identifiers plus camel/snake components."""
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        for raw in _WORD_RE.findall(value):
            for token in (raw, *_identifier_parts(raw)):
                normalized = token.casefold()
                if len(normalized) >= 2 and normalized not in seen:
                    seen.add(normalized)
                    tokens.append(normalized)
    return " ".join(tokens)
