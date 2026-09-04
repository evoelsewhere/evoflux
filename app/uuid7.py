"""Typed UUIDv7 compatibility helper.

Resolution order, best source first:

1. ``uuid.uuid7`` from the standard library — available on Python 3.14+.
2. The ``uuid_extensions`` backport, when installed.
3. A local RFC 9562 implementation, so neither of the above being present
   is fatal.

Every branch is guarded: importing this module must not be the thing that
takes the application down.
"""

from __future__ import annotations

import secrets
import time
from typing import Callable, cast
from uuid import UUID


def _local_uuid7() -> UUID:
    """Generate a UUIDv7 per RFC 9562 §5.7.

    Layout is 48 bits of Unix time in milliseconds, a 4-bit version, 12 bits
    of randomness, a 2-bit variant, and 62 more random bits — 128 bits, so
    exactly 16 bytes. Randomness comes from ``secrets`` because these values
    become database identifiers.
    """
    timestamp_ms = int(time.time() * 1000) & 0xFFFF_FFFF_FFFF
    raw = bytearray(timestamp_ms.to_bytes(6, "big") + secrets.token_bytes(10))
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7
    raw[8] = (raw[8] & 0x3F) | 0x80  # variant 0b10
    return UUID(bytes=bytes(raw))


def _resolve_uuid7() -> Callable[[], UUID]:
    """Pick the best available UUIDv7 source."""
    try:
        # Standard library, Python 3.14 and later.
        from uuid import uuid7 as stdlib_uuid7  # type: ignore[attr-defined]

        return cast("Callable[[], UUID]", stdlib_uuid7)
    except ImportError:
        pass
    try:
        from uuid_extensions import uuid7 as backport_uuid7

        return cast("Callable[[], UUID]", backport_uuid7)
    except ImportError:
        return _local_uuid7


_uuid7 = _resolve_uuid7()


def uuid7() -> UUID:
    """Return a UUIDv7 with a stable type across stdlib/backport versions."""
    return cast(UUID, _uuid7())
