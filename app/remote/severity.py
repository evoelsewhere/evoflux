"""Advisory-only command severity for permission cards.

Display hint alone — never consulted by any gating decision.
``PermissionService`` (``app/agent/permission.py``) is the sole authority on
whether a request blocks; this module exists only so a phone operator sees
"rm -rf" and "read a file" rendered differently, never to decide anything.
"""

from __future__ import annotations

from typing import Literal

Severity = Literal["high", "elevated", "normal"]

__all__ = ["Severity", "derive_severity"]

#: Substrings that mark a command as destructive regardless of tool.
_DESTRUCTIVE_SUBSTRINGS = (
    "rm -rf",
    "rm -r -f",
    "git clean -fd",
    "git reset --hard",
    "git push --force",
    "git push -f",
    "drop table",
    "drop database",
    "truncate table",
)

#: Tools that run arbitrary code/commands — elevated even without a
#: destructive-pattern match.
_ELEVATED_TOOLS = frozenset({"shell", "bash", "python", "process", "rm"})


def derive_severity(*, tool: str, command: str) -> Severity:
    """Derive a display-only severity from a permission request's tool and
    command text. Never raises; unknown input degrades to "normal"."""
    lowered = command.lower()
    if any(pattern in lowered for pattern in _DESTRUCTIVE_SUBSTRINGS):
        return "high"
    if tool in _ELEVATED_TOOLS:
        return "elevated"
    return "normal"
