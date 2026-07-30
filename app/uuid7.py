"""Typed UUIDv7 compatibility helper for Python 3.12+."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from uuid_extensions import uuid7 as _uuid7


def uuid7() -> UUID:
    """Return a UUIDv7 with a stable type across stdlib/backport versions."""
    return cast(UUID, _uuid7())
