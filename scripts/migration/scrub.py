#!/usr/bin/env python3
"""Remove secrets and personal data from a traffic recording, in place.

Usage: scrub.py <file>

Replaces API-key patterns, bearer tokens, e-mail addresses and home-directory
paths. Exits 1 if a known secret pattern is still present after scrubbing, and
2 if the file cannot be read.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# (pattern, replacement); applied in order.
_SECRETS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        "<private-key>",
    ),
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}"), "<api-key>"),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
        "<api-key>",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<api-key>"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), "<api-key>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<api-key>"),
    (re.compile(r"(?i)\b(Bearer|Basic) [A-Za-z0-9._~+/=-]{8,}"), r"\1 <token>"),
    # `_token` may be percent-encoded in part (`%5Ftoken`, `_%74oken`).
    (
        re.compile(
            r"(?i)([?&](?:_|%5f)(?:t|%74)(?:o|%6f)(?:k|%6b)(?:e|%65)(?:n|%6e)=)"
            r"[^&\s\"']+"
        ),
        r"\1<token>",
    ),
)
_PII: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), "<email>"),
    # Windows homes, plain or JSON-escaped (C:\\Users\\name).
    (
        re.compile(r"([A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/))[^\\/\s\"']+"),
        r"\1<user>",
    ),
    (re.compile(r"(/(?:home|Users)/)[^/\\\s\"']+"), r"\1<user>"),
)


def scrub(text: str) -> str:
    for pattern, replacement in (*_SECRETS, *_PII):
        text = pattern.sub(replacement, text)
    return text


def surviving(text: str) -> list[str]:
    """Known secret patterns that still match ``text`` outside a ``<placeholder>``."""
    return [
        pattern.pattern[:40]
        for pattern, _ in _SECRETS
        if any("<" not in match.group(0) for match in pattern.finditer(text))
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"scrub: cannot read {path}: {error}", file=sys.stderr)
        return 2
    cleaned = scrub(text)
    path.write_text(cleaned, encoding="utf-8", newline="")
    left = surviving(cleaned)
    if left:
        print(f"scrub: secret patterns survive in {path}: {left}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
