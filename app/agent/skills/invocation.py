"""The ``$skill-name`` user-invocation syntax.

A mention is ``$`` followed by a valid Skill name, not preceded by a word
character or another ``$`` and followed by whitespace, punctuation or the end
of the text. Mentions count anywhere in the message except in quoted context
lines (``> ...``) and fenced code blocks. The frontend composer uses the same
rule (``web/src/components/InputBar.skills.ts``).
"""

from __future__ import annotations

import re


MENTION_RE = re.compile(
    r"(?<![A-Za-z0-9_$])\$([a-z0-9]+(?:-[a-z0-9]+)*)(?=$|[\s.,!?;:)\]}'\"])"
)
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def skill_mentions(text: str) -> list[str]:
    """Return mentioned names in first-seen order, without duplicates."""

    names: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        for match in MENTION_RE.finditer(line):
            name = match.group(1)
            if name not in names:
                names.append(name)
    return names


__all__ = ["MENTION_RE", "skill_mentions"]
