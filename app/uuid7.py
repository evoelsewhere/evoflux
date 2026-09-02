"""Typed UUIDv7 compatibility helper for Python 3.12+."""

from __future__ import annotations

import sys
from typing import cast
from uuid import UUID

if sys.version_info >= (3, 12):
    from uuid import uuid7 as _uuid7  # type: ignore[attr-defined]
else:
    try:
        from uuid_extensions import uuid7 as _uuid7  # type: ignore[no-redef]
    except ModuleNotFoundError:
        import random
        import time

        def _uuid7() -> UUID:  # type: ignore[misc]
            """Minimal UUIDv7 fallback using time + random bits."""
            ts_ms = int(time.time() * 1000)
            time_bytes = ts_ms.to_bytes(6, "big")
            rand = random.getrandbits(62)
            raw = time_bytes + rand.to_bytes(8, "big")
            # Set version=7 and variant=10
            b = bytearray(raw)
            b[6] = (b[6] & 0x0F) | 0x70
            b[8] = (b[8] & 0x3F) | 0x80
            return UUID(bytes=bytes(b))


def uuid7() -> UUID:
    """Return a UUIDv7 with a stable type across stdlib/backport versions."""
    return cast(UUID, _uuid7())
