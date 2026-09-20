"""Shared rolling edit budget for transports without provider-specific limits."""

from __future__ import annotations

import time
from collections import deque


class RollingEditBudget:
    """Bounded rolling edit allowance with per-key duplicate suppression."""

    def __init__(self, *, window_seconds: float = 15 * 60, max_edits: int = 4) -> None:
        if window_seconds <= 0 or max_edits < 1:
            raise ValueError(
                "window_seconds must be positive and max_edits must be >= 1"
            )
        self._window_seconds = window_seconds
        self._max_edits = max_edits
        self._edits: dict[str, deque[float]] = {}
        self._last: dict[str, str] = {}

    def allow_edit(
        self, *, connection_id: str, key: str, text: str, now: float | None = None
    ) -> bool:
        moment = time.monotonic() if now is None else now
        edits = self._edits.setdefault(connection_id, deque())
        while edits and edits[0] <= moment - self._window_seconds:
            edits.popleft()
        return self._last.get(key) != text and len(edits) < self._max_edits

    def record_edit(
        self, *, connection_id: str, key: str, text: str, now: float | None = None
    ) -> None:
        moment = time.monotonic() if now is None else now
        self._edits.setdefault(connection_id, deque()).append(moment)
        self._last[key] = text

    def forget(self, key: str) -> None:
        self._last.pop(key, None)

    def delivery_mode(
        self,
        *,
        connection_id: str,
        key: str,
        text: str,
        now: float | None = None,
    ) -> str:
        """Return ``edit``, ``new``, or ``skip`` for a live status update."""
        if self._last.get(key) == text:
            return "skip"
        if self.allow_edit(connection_id=connection_id, key=key, text=text, now=now):
            self.record_edit(connection_id=connection_id, key=key, text=text, now=now)
            return "edit"
        self._last[key] = text
        return "new"

    def completion_allowed(self) -> bool:
        return True


__all__ = ["RollingEditBudget"]
