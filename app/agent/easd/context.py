"""Shared EasdContext dataclass for EASD tools.

Replaces the former direct ``team`` reference so EASD tools work
in both single-agent and multi-agent modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EasdContext:
    """Minimal context needed by EASD tools."""

    db_factory: Any
    session_id: str
