"""Rolling activity window for live-mode status cards (AC-56).

Bounded, in-memory, per-turn bookkeeping — owned by
``outbound._TurnDeliveryState`` and discarded wherever that state already
is (completion, error, interrupt, adapter shutdown, unpairing; see that
module's docstring). Pure: no asyncio, no adapter, no database, so this
module is trivially unit-testable and safe to call from the synchronous
``RemoteProjection.observe`` path.

Entries are keyed (by ``tool_call_id``, or ``"thinking:{agent}"`` for a
thinking entry) so a tool's start/end updates the same line in place
rather than growing the window, and the window keeps only the
``MAX_ENTRIES`` most-recently-touched entries — a "most recent" LRU, not a
plain append-only ring buffer, so a long-running tool call started before
five other tools finished still tracks its own completion correctly.

Argument summaries are the highest-risk text this module renders (file
paths, command strings, occasionally secrets — see the control-surface
spec's Permissions section), so they are redacted with the same
``protect_outbound_text(channel="remote")`` every other rendered field in
this feature uses, then truncated to ``MAX_ARG_SUMMARY_LENGTH``, then
HTML-escaped — redaction first, truncation second, escaping last, so a
truncated multi-byte escape sequence can never appear.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.remote.formatting import escape

__all__ = ["LiveActivityWindow", "MAX_ENTRIES", "MAX_ARG_SUMMARY_LENGTH"]

#: The six most recent activity entries bound the block to roughly 600
#: characters even at the 80-char argument cap, well clear of Telegram's
#: 4096-character limit (AC-56).
MAX_ENTRIES = 6
MAX_ARG_SUMMARY_LENGTH = 80

_PENDING_ICON = "⏳"  # ⏳ — tool_start observed, tool_end not yet
_DONE_ICON = "\U0001f527"  # 🔧 — tool_end observed
_THINKING_ICON = "\U0001f4ad"  # 💭
_SKILL_ICON = "\U0001f4da"  # 📚

#: Skills are not a distinct event; they are a tool call carrying
#: ``skill_name`` in its arguments (app/agent/tools/builtin/skill.py) and
#: are special-cased here rather than rendered as a generic tool call.
_SKILL_TOOL_NAME = "skill"


def _redact(text: str) -> str:
    """Apply the shared remote-channel outbound redaction boundary."""
    from app.remote.redaction import redact_remote_text

    return redact_remote_text(text)


def _summarize_arguments(arguments: str | None) -> str:
    """A short, redacted, truncated rendering of a tool's JSON arguments.

    Single-key argument dicts (the common case — ``{"path": ...}``,
    ``{"pattern": ...}``, ``{"command": ...}``) render as just that value,
    matching the spec's mockup (``grep "def test_auth"``, not
    ``grep {"pattern": "def test_auth"}``). Anything else falls back to a
    space-joined dump of the values. Malformed JSON renders as the raw
    string rather than raising — a live-mode line is decoration, never
    worth failing a turn over.
    """
    if not arguments:
        return ""
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        raw = arguments
    else:
        if isinstance(parsed, dict) and parsed:
            raw = " ".join(str(v) for v in parsed.values())
        elif isinstance(parsed, dict):
            raw = ""
        else:
            raw = str(parsed)

    raw = _redact(raw)
    if len(raw) > MAX_ARG_SUMMARY_LENGTH:
        raw = raw[: MAX_ARG_SUMMARY_LENGTH - 1] + "…"
    return escape(raw)


def _extract_skill_name(arguments: str | None) -> str | None:
    if not arguments:
        return None
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    name = parsed.get("skill_name")
    return name if isinstance(name, str) and name else None


@dataclass
class LiveActivityWindow:
    """A bounded rolling window of live-mode activity lines (AC-56)."""

    _order: list[str] = field(default_factory=list)  # keys, oldest-touched first
    _rendered: dict[str, str] = field(default_factory=dict)  # key -> full line

    def _touch(self, key: str, line: str) -> None:
        if key in self._rendered:
            self._order.remove(key)
        self._order.append(key)
        self._rendered[key] = line
        while len(self._order) > MAX_ENTRIES:
            oldest = self._order.pop(0)
            self._rendered.pop(oldest, None)

    def observe_tool_call(self, *, tool_call_id: str | None, name: str) -> None:
        if name == _SKILL_TOOL_NAME:
            return  # rendered richly once tool_start's arguments arrive
        key = tool_call_id or f"anon:{name}"
        self._touch(key, f"{_PENDING_ICON} {escape(name)}")

    def observe_tool_start(
        self, *, tool_call_id: str | None, name: str, arguments: str | None
    ) -> None:
        key = tool_call_id or f"anon:{name}"
        if name == _SKILL_TOOL_NAME:
            skill_name = _extract_skill_name(arguments)
            if skill_name:
                self._touch(key, f"{_SKILL_ICON} Skill: {escape(skill_name)}")
                return
        summary = _summarize_arguments(arguments)
        line = f"{_PENDING_ICON} {escape(name)}"
        if summary:
            line += f"   {summary}"
        self._touch(key, line)

    def observe_tool_end(self, *, tool_call_id: str | None, name: str) -> None:
        key = tool_call_id or f"anon:{name}"
        existing = self._rendered.get(key)
        if existing is not None and existing.startswith(_PENDING_ICON):
            self._touch(key, _DONE_ICON + existing[len(_PENDING_ICON) :])
        elif existing is None:
            self._touch(key, f"{_DONE_ICON} {escape(name)}")
        else:
            self._touch(key, existing)  # already done or a skill card; just re-touch

    def observe_thinking(self, *, agent: str) -> None:
        key = f"thinking:{agent}"
        self._touch(key, f"{escape(agent)} · {_THINKING_ICON} thinking")

    def lines(self) -> list[str]:
        return [self._rendered[key] for key in self._order]
