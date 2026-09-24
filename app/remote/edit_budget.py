"""Shared per-connection edit budget for live-mode status-card updates
(AC-57).

Live-mode edits are coalesced to at most one per ``LIVE_EDIT_INTERVAL``
per turn, skipped entirely when the rendered text is unchanged, and drawn
from one shared allowance per connection across every concurrently live
turn — so contention under ``notify_scope=all`` degrades cadence rather
than producing a burst of 429s. Pure bookkeeping: callers pass their own
``now`` in tests (``time.monotonic()`` by default) rather than sleeping.

A turn's final done/error card is never checked against this budget — see
outbound.py's ``_finalize_turn``, which always enqueues its edit directly.
Liveliness is best-effort; completion is not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

__all__ = ["EditBudget", "LIVE_EDIT_INTERVAL"]

LIVE_EDIT_INTERVAL = 2.0


@dataclass
class EditBudget:
    #: connection_id -> monotonic time that connection may next spend an edit.
    _next_allowed_at: dict[str, float] = field(default_factory=dict)
    #: key (one per live turn) -> last text actually delivered for it.
    _last_text: dict[str, str] = field(default_factory=dict)

    def should_edit(
        self, *, connection_id: str, key: str, text: str, now: float | None = None
    ) -> bool:
        """Whether a live-mode edit for *key* should be sent now: the text
        actually changed since the last delivered edit for this key, and
        this connection's shared budget currently allows an edit."""
        if self._last_text.get(key) == text:
            return False
        moment = time.monotonic() if now is None else now
        return moment >= self._next_allowed_at.get(connection_id, 0.0)

    def record_edit(
        self, *, connection_id: str, key: str, text: str, now: float | None = None
    ) -> None:
        """Call once an edit for *key* has actually been enqueued."""
        moment = time.monotonic() if now is None else now
        self._next_allowed_at[connection_id] = moment + LIVE_EDIT_INTERVAL
        self._last_text[key] = text

    def note_rate_limited(
        self, *, connection_id: str, retry_after: float, now: float | None = None
    ) -> None:
        """Degrade this connection's cadence after a Telegram 429 —
        pushes the next allowed edit out by *retry_after* seconds, never
        shorter than the normal cadence would already have produced."""
        moment = time.monotonic() if now is None else now
        candidate = moment + max(retry_after, LIVE_EDIT_INTERVAL)
        self._next_allowed_at[connection_id] = max(
            self._next_allowed_at.get(connection_id, 0.0), candidate
        )

    def discard(self, key: str) -> None:
        """Forget a finished turn's last-delivered text. The connection's
        shared cooldown is untouched — it belongs to the connection, not
        to any one turn."""
        self._last_text.pop(key, None)
