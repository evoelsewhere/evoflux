# Remote Telegram Live Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `response_mode = "live"` (already persisted and settable from `/settings` since the response-mode-implementation plan) actually do something: a live turn's status card shows a rolling window of recent activity, edited on a throttled, budgeted cadence, and never regresses `summary` mode's existing behavior.

**Architecture:** Two new pure, synchronous, no-I/O modules — `app/remote/live_activity.py` (bounded rolling window + redacted/escaped rendering of tool/thinking events) and `app/remote/edit_budget.py` (shared per-connection edit throttle with 429 backoff) — plumbed into `app/remote/outbound.py`'s existing per-turn lifecycle (`_TurnDeliveryState`, `observe`, `drain_pending`). `response_mode` is threaded from the pairing row through `RemoteInboundService.handle_text` into `RemoteProjection.begin_phone_turn` so it is read fresh at the start of every turn (AC-55's "takes effect on the next turn with no restart"), never cached. As a small, purely mechanical bonus, this plan also closes AC-58 (the command menu is currently missing `/settings`, `/health`, `/changes`).

**Tech Stack:** Python 3.12, FastAPI/SQLModel backend, pytest + pytest-asyncio, `ruff`, `ty` (Astral type checker, suppress with `# ty: ignore[<rule>]`).

**Spec:** `documents/plans/remote-telegram-control-surface.md` — this plan implements AC-56 and AC-57 (live-mode content and bounds; throttled, budgeted edits), plus AC-58 (bounded command surface). AC-55 (the preference itself) was implemented by `documents/plans/remote-telegram-response-mode-implementation.md`. AC-53 (providers read-only listing) is a separate, unbuilt feature and is explicitly out of scope for this plan.

## Global Constraints

- `MAX_ENTRIES = 6` activity entries in the rolling window (AC-56).
- `MAX_ARG_SUMMARY_LENGTH = 80` characters per tool argument summary, after redaction, before escaping (AC-56).
- `LIVE_EDIT_INTERVAL = 3.0` seconds — at most one live edit per turn per interval, shared across a connection's concurrently-live turns (AC-57).
- `ToolOutputDeltaEvent` is never observed or rendered in live mode (AC-56).
- In `summary` mode (the default), no activity entry is ever rendered — zero behavior change from today (AC-20 regression guard).
- A turn's final done/error card is never gated by the edit budget — liveliness is best-effort, completion is not.
- Every rendered tool-argument summary passes through outbound redaction (`app.agent.outbound_redaction.protect_outbound_text`, channel `"remote"`) before HTML-escaping, same order as every other rendered field in this feature.
- No new durable storage — activity windows and edit budgets are in-memory and discarded with the turn, same as today's progress-message state.

---

## File Structure

- `app/remote/live_activity.py` (new) — `LiveActivityWindow`: a bounded, keyed, in-memory rolling window. Observes `tool_call`/`tool_start`/`tool_end`/`thinking` payload fields and renders each into one already-redacted, already-escaped display line. Pure — no asyncio, no adapter, no database.
- `app/remote/edit_budget.py` (new) — `EditBudget`: per-connection throttle (`LIVE_EDIT_INTERVAL`) plus unchanged-text skip plus 429/`retry_after` backoff. Pure — no I/O, just monotonic-clock bookkeeping.
- `app/remote/formatting.py` (modified) — new `render_live_status_card` builder, following the existing `render_status_card`/`render_done_card` pattern.
- `app/remote/inbound.py` (modified) — `RemoteInboundResult` gains `response_mode`, set from the pairing row already loaded in `handle_text`.
- `app/remote/runtime.py` (modified) — passes `result.response_mode` into `begin_phone_turn`.
- `app/remote/outbound.py` (modified) — `_TurnDeliveryState` gains `activity`/`response_mode`; `begin_phone_turn` accepts `response_mode`; `observe` grows a mode-gated activity branch; a new `_maybe_schedule_live_edit` consults `EditBudget` and enqueues a throttled edit; the edit-drain loop records 429s into the budget.
- `app/remote/telegram/adapter.py` (modified) — `_register_commands`'s list grows to the AC-58 set.
- `tests/remote/test_live_activity.py` (new), `tests/remote/test_edit_budget.py` (new), `tests/remote/test_formatting.py` (modified), `tests/remote/test_inbound.py` (modified), `tests/remote/test_outbound.py` (modified), `tests/remote/telegram/test_adapter.py` (modified).

---

### Task 1: `app/remote/live_activity.py` — the rolling activity window

**Files:**
- Create: `app/remote/live_activity.py`
- Test: `tests/remote/test_live_activity.py`

**Interfaces:**
- Produces: `LiveActivityWindow` (dataclass, no required constructor args), with methods `observe_tool_call(*, tool_call_id: str | None, name: str) -> None`, `observe_tool_start(*, tool_call_id: str | None, name: str, arguments: str | None) -> None`, `observe_tool_end(*, tool_call_id: str | None, name: str) -> None`, `observe_thinking(*, agent: str) -> None`, and `lines() -> list[str]` (bounded to `MAX_ENTRIES`, each entry already redacted and HTML-escaped, ready to join with `"\n"`). Also exports `MAX_ENTRIES` and `MAX_ARG_SUMMARY_LENGTH`.
- Consumes: `app.remote.formatting.escape` (existing).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for app/remote/live_activity.py — the rolling activity window (AC-56)."""

from __future__ import annotations

from app.remote.live_activity import MAX_ENTRIES, LiveActivityWindow


def test_tool_start_renders_name_and_argument_summary() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(
        tool_call_id="call-1", name="read", arguments='{"path": "tests/test_auth.py"}'
    )

    lines = window.lines()

    assert len(lines) == 1
    assert "read" in lines[0]
    assert "tests/test_auth.py" in lines[0]


def test_tool_start_truncates_argument_summary_to_80_chars() -> None:
    window = LiveActivityWindow()
    long_value = "x" * 200
    window.observe_tool_start(
        tool_call_id="call-1", name="shell", arguments=f'{{"command": "{long_value}"}}'
    )

    lines = window.lines()

    assert len(lines) == 1
    # Icon + tool name + separator are not part of the 80-char argument
    # budget, so assert on the tail (the argument summary itself) rather
    # than the whole line's length.
    assert "x" * 81 not in lines[0]
    assert "…" in lines[0]  # ellipsis marks the truncation


def test_tool_end_updates_the_same_entry_in_place() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(tool_call_id="call-1", name="grep", arguments="{}")
    window.observe_tool_end(tool_call_id="call-1", name="grep")

    lines = window.lines()

    assert len(lines) == 1  # no duplicate entry from tool_end


def test_tool_end_flips_the_icon_from_pending_to_done() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(tool_call_id="call-1", name="grep", arguments="{}")
    pending_line = window.lines()[0]
    window.observe_tool_end(tool_call_id="call-1", name="grep")
    done_line = window.lines()[0]

    assert pending_line != done_line


def test_skill_tool_call_renders_the_skill_name_not_the_raw_tool_name() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(
        tool_call_id="call-1",
        name="skill",
        arguments='{"action": "load", "skill_name": "test-driven-development"}',
    )

    lines = window.lines()

    assert len(lines) == 1
    assert "test-driven-development" in lines[0]
    assert "skill" not in lines[0].lower() or "Skill:" in lines[0]


def test_thinking_entry_names_the_active_agent() -> None:
    window = LiveActivityWindow()
    window.observe_thinking(agent="explorer")

    lines = window.lines()

    assert len(lines) == 1
    assert "explorer" in lines[0]


def test_window_caps_at_six_most_recently_touched_entries() -> None:
    window = LiveActivityWindow()
    for i in range(9):
        window.observe_tool_start(
            tool_call_id=f"call-{i}", name=f"tool{i}", arguments="{}"
        )

    lines = window.lines()

    assert len(lines) == MAX_ENTRIES
    # The three oldest calls (0, 1, 2) were evicted; the six most recent remain.
    assert "tool0" not in "\n".join(lines)
    assert "tool8" in "\n".join(lines)


def test_argument_summary_is_html_escaped() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(
        tool_call_id="call-1", name="grep", arguments='{"pattern": "<script>"}'
    )

    lines = window.lines()

    assert "<script>" not in lines[0]
    assert "&lt;script&gt;" in lines[0]


def test_tool_name_is_html_escaped() -> None:
    window = LiveActivityWindow()
    window.observe_tool_call(tool_call_id="call-1", name="<b>tool</b>")

    lines = window.lines()

    assert "<b>tool</b>" not in lines[0]
    assert "&lt;b&gt;" in lines[0]


def test_unparseable_arguments_render_without_raising() -> None:
    window = LiveActivityWindow()
    window.observe_tool_start(tool_call_id="call-1", name="shell", arguments="not json")

    lines = window.lines()

    assert len(lines) == 1
    assert "shell" in lines[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_live_activity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.remote.live_activity'`.

- [ ] **Step 3: Write the implementation**

```python
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
    """Best-effort outbound redaction — mirrors outbound.py's own
    ``_redact_text`` (kept independent per this module's "no dependency on
    app.remote state" purity goal; both wrap the same protection call)."""
    try:
        from app.agent.outbound_redaction import OutboundContext, protect_outbound_text

        protected, _report = protect_outbound_text(
            text, context=OutboundContext(channel="remote")
        )
        return protected
    except Exception:
        return text


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_live_activity.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/live_activity.py tests/remote/test_live_activity.py && uv run ty check app/remote/live_activity.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/live_activity.py tests/remote/test_live_activity.py
git commit -m "feat(remote): add the live-mode rolling activity window (AC-56)"
```

---

### Task 2: `app/remote/edit_budget.py` — the shared per-connection edit budget

**Files:**
- Create: `app/remote/edit_budget.py`
- Test: `tests/remote/test_edit_budget.py`

**Interfaces:**
- Produces: `EditBudget` (dataclass, no required constructor args), `LIVE_EDIT_INTERVAL` (float, 3.0). Methods: `should_edit(*, connection_id: str, key: str, text: str, now: float | None = None) -> bool`, `record_edit(*, connection_id: str, key: str, text: str, now: float | None = None) -> None`, `note_rate_limited(*, connection_id: str, retry_after: float, now: float | None = None) -> None`, `discard(key: str) -> None`.
- Consumes: nothing from elsewhere in `app.remote` — pure, `time.monotonic`-based bookkeeping (tests inject `now` explicitly rather than sleeping).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for app/remote/edit_budget.py — the shared per-connection live-mode
edit throttle (AC-57)."""

from __future__ import annotations

from app.remote.edit_budget import LIVE_EDIT_INTERVAL, EditBudget


def test_first_edit_for_a_key_is_always_allowed() -> None:
    budget = EditBudget()

    assert budget.should_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)


def test_unchanged_text_is_skipped_even_when_budget_allows_it() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    assert not budget.should_edit(
        connection_id="conn-1", key="turn-1", text="a", now=10.0
    )


def test_changed_text_is_throttled_within_the_interval() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL - 0.1
    )

    assert not allowed


def test_changed_text_is_allowed_once_the_interval_elapses() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL + 0.1
    )

    assert allowed


def test_budget_is_shared_across_concurrent_turns_on_one_connection() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    # A second, distinct turn on the SAME connection is still throttled by
    # the first turn's recent edit — the budget is per-connection, not
    # per-turn (AC-57: "one shared per-connection edit budget across all
    # concurrently live turns").
    allowed = budget.should_edit(connection_id="conn-1", key="turn-2", text="x", now=0.5)

    assert not allowed


def test_a_different_connection_has_its_own_independent_budget() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)

    allowed = budget.should_edit(connection_id="conn-2", key="turn-2", text="x", now=0.5)

    assert allowed


def test_rate_limit_pushes_the_next_allowed_edit_out_by_retry_after() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    budget.note_rate_limited(connection_id="conn-1", retry_after=30.0, now=1.0)

    still_blocked = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL + 0.1
    )
    allowed_after_backoff = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=31.5
    )

    assert not still_blocked
    assert allowed_after_backoff


def test_rate_limit_never_shortens_an_already_longer_cooldown() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    # A tiny retry_after must not undercut the normal LIVE_EDIT_INTERVAL cooldown.
    budget.note_rate_limited(connection_id="conn-1", retry_after=0.01, now=0.5)

    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="b", now=LIVE_EDIT_INTERVAL - 0.1
    )

    assert not allowed


def test_discard_forgets_a_finished_turns_last_text() -> None:
    budget = EditBudget()
    budget.record_edit(connection_id="conn-1", key="turn-1", text="a", now=0.0)
    budget.discard("turn-1")

    # The connection-level cooldown still applies (discard only forgets the
    # per-key last-text bookkeeping, not the shared connection throttle),
    # but a differently-keyed re-observation of the same text is no longer
    # considered "unchanged".
    allowed = budget.should_edit(
        connection_id="conn-1", key="turn-1", text="a", now=LIVE_EDIT_INTERVAL + 1
    )

    assert allowed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_edit_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.remote.edit_budget'`.

- [ ] **Step 3: Write the implementation**

```python
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

LIVE_EDIT_INTERVAL = 3.0


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_edit_budget.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/edit_budget.py tests/remote/test_edit_budget.py && uv run ty check app/remote/edit_budget.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/edit_budget.py tests/remote/test_edit_budget.py
git commit -m "feat(remote): add the shared live-mode edit budget (AC-57)"
```

---

### Task 3: `render_live_status_card` in `app/remote/formatting.py`

**Files:**
- Modify: `app/remote/formatting.py`
- Test: `tests/remote/test_formatting.py`

**Interfaces:**
- Consumes: `escape`, `format_elapsed` (both already in this module); `Sequence[str]` of already-rendered activity lines from `LiveActivityWindow.lines()`.
- Produces: `render_live_status_card(*, title: str, elapsed_seconds: float, activity_lines: Sequence[str]) -> tuple[str, tuple[RemoteButton, ...]]` (no buttons — a live status card is never actionable, same as `render_status_card` today).

- [ ] **Step 1: Write the failing tests**

Append to `tests/remote/test_formatting.py`:

```python
def test_render_live_status_card_shows_title_elapsed_and_activity() -> None:
    text, buttons = formatting.render_live_status_card(
        title="Fix failing tests",
        elapsed_seconds=72.0,
        activity_lines=["\U0001f4ad explorer thinking", "\U0001f527 grep foo"],
    )
    assert "Fix failing tests" in text
    assert "1m 12s" in text
    assert "explorer thinking" in text
    assert "grep foo" in text
    assert buttons == ()


def test_render_live_status_card_escapes_title() -> None:
    text, _ = formatting.render_live_status_card(
        title="<script>alert(1)</script>", elapsed_seconds=1.0, activity_lines=[]
    )
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_render_live_status_card_with_no_activity_yet_still_renders() -> None:
    text, buttons = formatting.render_live_status_card(
        title="New task", elapsed_seconds=0.5, activity_lines=[]
    )
    assert "New task" in text
    assert buttons == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_formatting.py -k live_status_card -v`
Expected: FAIL with `AttributeError: module 'app.remote.formatting' has no attribute 'render_live_status_card'`.

- [ ] **Step 3: Write the implementation**

Add to `app/remote/formatting.py`, near `render_status_card`, and add `"render_live_status_card"` to `__all__`:

```python
def render_live_status_card(
    *, title: str, elapsed_seconds: float, activity_lines: Sequence[str]
) -> tuple[str, tuple[RemoteButton, ...]]:
    """The single status card a live-mode turn edits in place (AC-56). No
    buttons — like ``render_status_card``, this card is never actionable;
    when the turn ends this same message becomes the done/error card."""
    header = f"\U0001f527 <b>{escape(title)}</b> · {format_elapsed(elapsed_seconds)}"
    if not activity_lines:
        return header, ()
    return header + "\n\n" + "\n".join(activity_lines), ()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_formatting.py -v`
Expected: PASS, all tests in the file green (no regressions).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/formatting.py tests/remote/test_formatting.py && uv run ty check app/remote/formatting.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/formatting.py tests/remote/test_formatting.py
git commit -m "feat(remote): add render_live_status_card for live-mode turns (AC-56)"
```

---

### Task 4: Thread `response_mode` from the pairing into `begin_phone_turn`

**Files:**
- Modify: `app/remote/inbound.py`
- Modify: `app/remote/runtime.py`
- Test: `tests/remote/test_inbound.py`

**Interfaces:**
- Consumes: `RemotePairing.response_mode` (already persisted, `app/models/remote.py`).
- Produces: `RemoteInboundResult.response_mode: str = "summary"` (new field, default preserves every existing caller); `runtime.py`'s `_handle_text` passes `response_mode=result.response_mode` into `begin_phone_turn` (Task 5 adds that parameter).

- [ ] **Step 1: Write the failing tests**

`tests/remote/test_inbound.py` already has a `_paired_text_action(db, text=...)` module-level helper (creates a `RemoteConnection` + `RemotePairing` + a matching `RemoteInboundAction`, returns `(pairing, action)`) and an established monkeypatch pattern for stubbing `resolve_team_for_session`/`submit_persisted_interactive_message` — see `test_handle_text_creates_and_selects_a_top_level_work_task` near the top of the file. Add these two tests reusing that exact pattern:

```python
@pytest.mark.asyncio
async def test_handle_text_result_defaults_to_summary_response_mode(monkeypatch):
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            session = await db.get(ChatSession, UUID(session_id))
            return session, team

        submit = AsyncMock(
            side_effect=lambda db, *, session, **_kwargs: InteractiveMessageResult(
                status="accepted", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        assert result.response_mode == "summary"


@pytest.mark.asyncio
async def test_handle_text_result_carries_a_live_response_mode(monkeypatch):
    from app.remote.inbound import RemoteInboundService
    import app.remote.inbound as inbound

    async with db_module.async_session_factory() as db:
        pairing, action = await _paired_text_action(db)
        pairing.response_mode = "live"
        db.add(pairing)
        await db.commit()
        team = SimpleNamespace()

        async def resolve(db, session_id: str, *, require_existing: bool):
            session = await db.get(ChatSession, UUID(session_id))
            return session, team

        submit = AsyncMock(
            side_effect=lambda db, *, session, **_kwargs: InteractiveMessageResult(
                status="accepted", session_id=str(session.id), message_id=None
            )
        )
        monkeypatch.setattr(inbound, "resolve_team_for_session", resolve)
        monkeypatch.setattr(inbound, "submit_persisted_interactive_message", submit)

        result = await RemoteInboundService().handle_text(db, action)

        assert result.response_mode == "live"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/remote/test_inbound.py -k response_mode -v`
Expected: FAIL with `AttributeError: 'RemoteInboundResult' object has no attribute 'response_mode'`.

- [ ] **Step 3: Implement**

In `app/remote/inbound.py`, extend the dataclass and its one success-path construction:

```python
@dataclass(frozen=True)
class RemoteInboundResult:
    """A bounded, adapter-neutral outcome for one remote action."""

    status: str
    session_id: UUID | None = None
    message_id: UUID | None = None
    response_mode: str = "summary"
```

and in `handle_text`'s final `return`:

```python
        return RemoteInboundResult(
            status=result.status,
            session_id=UUID(result.session_id),
            message_id=result.message_id,
            response_mode=pairing.response_mode,
        )
```

(`pairing` is already in scope — it was re-fetched at the top of the `async with await self._lock_for(...)` block.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest --no-cov -q tests/remote/test_inbound.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Wire runtime.py (no new test — covered end-to-end by Task 5's outbound tests)**

In `app/remote/runtime.py`'s `_handle_text`, extend the `begin_phone_turn` call:

```python
            self._projection.begin_phone_turn(
                str(result.session_id),
                connection_id=str(action.connection_id),
                destination_id=action.principal.destination_id,
                principal_id=action.principal.principal_id,
                title=(
                    session_row.title
                    if session_row and session_row.title
                    else "New task"
                ),
                status=result.status,
                response_mode=result.response_mode,
            )
```

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check app/remote/inbound.py app/remote/runtime.py tests/remote/test_inbound.py && uv run ty check app/remote/inbound.py app/remote/runtime.py`
Expected: both clean. (`ty check` on `runtime.py` will fail until Task 5 adds `begin_phone_turn`'s `response_mode` parameter — if this task is executed before Task 5, run this step again after Task 5 instead of failing the branch here.)

- [ ] **Step 7: Commit**

```bash
git add app/remote/inbound.py app/remote/runtime.py tests/remote/test_inbound.py
git commit -m "feat(remote): thread response_mode from the pairing into each new turn (AC-55/56)"
```

---

### Task 5: Wire live-mode observation and throttled edits into `app/remote/outbound.py`

This is the integration task — the largest in this plan. It depends on Tasks 1, 2, 3, and 4.

**Files:**
- Modify: `app/remote/outbound.py`
- Test: `tests/remote/test_outbound.py`

**Interfaces:**
- Consumes: `LiveActivityWindow` (Task 1), `EditBudget` (Task 2), `render_live_status_card` (Task 3), `begin_phone_turn(..., response_mode: str = "summary")` (Task 4's call site).
- Produces: `_TurnDeliveryState.activity: LiveActivityWindow`, `_TurnDeliveryState.response_mode: str`; `RemoteProjection._edit_budget: EditBudget`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/remote/test_outbound.py` (reusing this file's existing `FakeAdapter`, `_envelope` helper, and `begin_phone_turn`-based turn setup patterns — read the file's existing live-turn-adjacent tests first, e.g. around `_handle_gate`/`_finalize_turn`, before writing these):

```python
class TestLiveMode:
    @pytest.mark.asyncio
    async def test_summary_mode_never_renders_activity_even_when_tool_events_flow(
        self,
    ) -> None:
        """AC-20 regression guard: response_mode="summary" (the default)
        must behave exactly as it did before this feature existed."""
        adapter = FakeAdapter()
        projection = RemoteProjection()
        projection.set_adapter(adapter)
        session_id = str(uuid4())
        connection_id = str(uuid4())  # must be a real UUID string — _enqueue_edit/
        # _enqueue_send both do UUID(connection_id) before handing a message to the
        # adapter, matching every other test in this file (e.g. test_done_edits_...
        # above uses connection_id = str(uuid4()) for the same reason).
        projection.register_session(
            session_id, connection_id=connection_id, destination_id="chat-1"
        )
        projection.begin_phone_turn(
            session_id,
            connection_id=connection_id,
            destination_id="chat-1",
            principal_id="user-1",
            title="Task",
            status="accepted",
        )
        await projection.drain_pending()
        edits_before = len(adapter.edited)

        projection.observe(
            session_id,
            _envelope(
                "tool_start",
                agent="explorer",
                tool_call_id="call-1",
                name="grep",
                arguments="{}",
            ),
        )
        await projection.drain_pending()

        assert len(adapter.edited) == edits_before  # no live edit was sent

    @pytest.mark.asyncio
    async def test_live_mode_edits_the_status_card_with_activity(self) -> None:
        adapter = FakeAdapter()
        projection = RemoteProjection()
        projection.set_adapter(adapter)
        session_id = str(uuid4())
        connection_id = str(uuid4())
        projection.register_session(
            session_id, connection_id=connection_id, destination_id="chat-1"
        )
        projection.begin_phone_turn(
            session_id,
            connection_id=connection_id,
            destination_id="chat-1",
            principal_id="user-1",
            title="Task",
            status="accepted",
            response_mode="live",
        )
        await projection.drain_pending()

        projection.observe(
            session_id,
            _envelope(
                "tool_start",
                agent="explorer",
                tool_call_id="call-1",
                name="grep",
                arguments='{"pattern": "def test_auth"}',
            ),
        )
        await projection.drain_pending()

        assert len(adapter.edited) == 1
        assert "grep" in adapter.edited[-1].text
        assert "def test_auth" in adapter.edited[-1].text

    @pytest.mark.asyncio
    async def test_live_mode_throttles_a_second_edit_within_the_interval(self) -> None:
        adapter = FakeAdapter()
        projection = RemoteProjection()
        projection.set_adapter(adapter)
        session_id = str(uuid4())
        connection_id = str(uuid4())
        projection.register_session(
            session_id, connection_id=connection_id, destination_id="chat-1"
        )
        projection.begin_phone_turn(
            session_id,
            connection_id=connection_id,
            destination_id="chat-1",
            principal_id="user-1",
            title="Task",
            status="accepted",
            response_mode="live",
        )
        await projection.drain_pending()

        projection.observe(
            session_id,
            _envelope(
                "tool_start", agent="explorer", tool_call_id="call-1", name="grep",
                arguments="{}",
            ),
        )
        await projection.drain_pending()
        projection.observe(
            session_id,
            _envelope(
                "tool_start", agent="explorer", tool_call_id="call-2", name="read",
                arguments="{}",
            ),
        )
        await projection.drain_pending()

        # Both tool_start events fire well within LIVE_EDIT_INTERVAL of each
        # other in real wall-clock terms (this test runs in milliseconds),
        # so only the first produced an edit.
        assert len(adapter.edited) == 1

    @pytest.mark.asyncio
    async def test_final_card_is_not_starved_by_the_live_edit_budget(self) -> None:
        """A turn's final done card must always be delivered even if the
        edit budget is currently exhausted from live-activity updates."""
        adapter = FakeAdapter()
        projection = RemoteProjection()
        projection.set_adapter(adapter)
        session_id = str(uuid4())
        connection_id = str(uuid4())
        projection.register_session(
            session_id, connection_id=connection_id, destination_id="chat-1"
        )
        projection.begin_phone_turn(
            session_id,
            connection_id=connection_id,
            destination_id="chat-1",
            principal_id="user-1",
            title="Task",
            status="accepted",
            response_mode="live",
        )
        await projection.drain_pending()

        projection.observe(
            session_id,
            _envelope(
                "tool_start", agent="explorer", tool_call_id="call-1", name="grep",
                arguments="{}",
            ),
        )
        await projection.drain_pending()
        edits_after_activity = len(adapter.edited)

        projection.observe(session_id, _envelope("done"))
        await projection.drain_pending()

        assert len(adapter.edited) == edits_after_activity + 1  # the done card landed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest --no-cov -q tests/remote/test_outbound.py -k TestLiveMode -v`
Expected: FAIL — `begin_phone_turn() got an unexpected keyword argument 'response_mode'`.

- [ ] **Step 3: Implement**

In `app/remote/outbound.py`:

1. Add imports:

```python
from app.remote.edit_budget import EditBudget
from app.remote.formatting import (
    render_done_card,
    render_error_card,
    render_live_status_card,
    render_status_card,
)
from app.remote.live_activity import LiveActivityWindow
```

2. Add the activity event set and extend the observed set:

```python
#: Live-mode-only events (AC-56) — only handled for a turn whose cached
#: response_mode is "live"; the check happens in ``observe`` itself
#: (in-memory, synchronous — no I/O), never before it, since ``observe``
#: has no other reason to look at a turn's mode.
_ACTIVITY_EVENT_TYPES = frozenset({"tool_call", "tool_start", "tool_end", "thinking"})

_OBSERVED_EVENT_TYPES = frozenset(
    {
        "done",
        "error",
        "permission_asked",
        "question_asked",
        "plan_approval_requested",
        "permission_replied",
        "question_replied",
        "plan_approval_replied",
    }
) | _ACTIVITY_EVENT_TYPES
```

3. Extend `_TurnDeliveryState`:

```python
    #: "summary" (default) or "live" — read fresh from the pairing at the
    #: start of every phone-admitted turn (never cached across turns), so
    #: AC-55's "no restart needed" holds. Desktop-started turns (no
    #: begin_phone_turn call) stay at the default; only a phone-admitted
    #: turn can be live, since only it owns an editable status card.
    response_mode: str = "summary"
    #: The rolling activity window this turn renders into while live —
    #: unused and empty in summary mode.
    activity: LiveActivityWindow = field(default_factory=LiveActivityWindow)
```

4. Add `_edit_budget` to `RemoteProjection`:

```python
    #: Shared across every live turn on this connection (AC-57) — see
    #: app/remote/edit_budget.py's own docstring for why the throttle is
    #: connection-scoped rather than per-turn.
    _edit_budget: EditBudget = field(default_factory=EditBudget, repr=False)
```

5. Extend `begin_phone_turn`'s signature and construction (add the parameter, thread it into `_TurnDeliveryState(...)`):

```python
    def begin_phone_turn(
        self,
        session_id: str,
        *,
        connection_id: str,
        destination_id: str,
        principal_id: str,
        title: str,
        status: str,
        response_mode: str = "summary",
    ) -> None:
```

```python
        turn = _TurnDeliveryState(
            session_id=session_id,
            connection_id=connection_id,
            destination_id=destination_id,
            principal_id=principal_id,
            lifecycle_correlation_id=correlation_id,
            phone_admitted=True,
            title=title,
            response_mode=response_mode,
        )
```

6. In `observe`, after the existing `turn = self._turns.get(session_id)` / fallback-turn block and before the `if event_type == "done":` chain, add the activity branch:

```python
        if event_type in _ACTIVITY_EVENT_TYPES:
            self._handle_activity(turn, event_type, envelope)
            return
```

7. Add the two new methods (near `_handle_gate`):

```python
    def _handle_activity(
        self, turn: _TurnDeliveryState, event_type: str, envelope
    ) -> None:
        """Feed one tool/thinking event into *turn*'s activity window and,
        if this is a live phone-admitted turn, enqueue a throttled edit.

        A turn whose final card has already been queued
        (``completion_sent``) ignores further activity — the card is
        about to be overwritten by the done/error card regardless."""
        if (
            not turn.phone_admitted
            or turn.response_mode != "live"
            or turn.completion_sent
        ):
            return

        data = envelope.data
        name = data.get("name", "")
        tool_call_id = data.get("tool_call_id")
        if event_type == "tool_call":
            turn.activity.observe_tool_call(tool_call_id=tool_call_id, name=name)
        elif event_type == "tool_start":
            turn.activity.observe_tool_start(
                tool_call_id=tool_call_id, name=name, arguments=data.get("arguments")
            )
        elif event_type == "tool_end":
            turn.activity.observe_tool_end(tool_call_id=tool_call_id, name=name)
        elif event_type == "thinking":
            turn.activity.observe_thinking(agent=data.get("agent", ""))

        self._maybe_schedule_live_edit(turn)

    def _maybe_schedule_live_edit(self, turn: _TurnDeliveryState) -> None:
        correlation_id = turn.lifecycle_correlation_id
        if correlation_id is None:
            return
        text, buttons = render_live_status_card(
            title=turn.title,
            elapsed_seconds=time.monotonic() - turn.started_at,
            activity_lines=turn.activity.lines(),
        )
        if not self._edit_budget.should_edit(
            connection_id=turn.connection_id, key=correlation_id, text=text
        ):
            return
        self._edit_budget.record_edit(
            connection_id=turn.connection_id, key=correlation_id, text=text
        )
        self._enqueue_edit(
            destination_id=turn.destination_id,
            text=text,
            buttons=buttons,
            correlation_id=correlation_id,
        )
```

8. Discard the budget's per-turn bookkeeping wherever a turn's state is torn down — `clear_turn` and `_finalize_turn`:

```python
    def clear_turn(self, session_id: str) -> None:
        """Clear delivery state for a completed turn."""
        turn = self._turns.pop(session_id, None)
        if turn is not None:
            self._stop_typing(turn)
            if turn.lifecycle_correlation_id is not None:
                self._edit_budget.discard(turn.lifecycle_correlation_id)
```

In `_finalize_turn`, right after `self._stop_typing(turn)`:

```python
        self._stop_typing(turn)
        if turn.lifecycle_correlation_id is not None:
            self._edit_budget.discard(turn.lifecycle_correlation_id)
```

9. Honor 429s in the edit-drain loop inside `drain_pending` — replace:

```python
            while self._pending_edits:
                msg = self._pending_edits.pop(0)
                try:
                    await adapter.edit(msg)
                except Exception as exc:
                    logger.warning(
                        "remote_outbound_edit_failed destination_id={} error={}",
                        msg.destination_id,
                        exc,
                    )
```

with:

```python
            while self._pending_edits:
                msg = self._pending_edits.pop(0)
                try:
                    await adapter.edit(msg)
                except Exception as exc:
                    # A 429 carries retry_after on Telegram's own exception
                    # type; duck-typed here rather than importing
                    # TelegramApiError, which would tie this
                    # adapter-neutral module to one adapter's transport.
                    error_code = getattr(exc, "error_code", None)
                    retry_after = getattr(exc, "retry_after", None)
                    if error_code == 429 and retry_after is not None:
                        self._edit_budget.note_rate_limited(
                            connection_id=str(msg.connection_id),
                            retry_after=float(retry_after),
                        )
                    logger.warning(
                        "remote_outbound_edit_failed destination_id={} error={}",
                        msg.destination_id,
                        exc,
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest --no-cov -q tests/remote/test_outbound.py -v`
Expected: PASS, all tests in the file green (no regressions in the ~50+ pre-existing tests).

- [ ] **Step 5: Run the full remote suite, lint, and type-check**

Run: `uv run pytest --no-cov -q tests/remote/ && uv run ruff check app/remote/ tests/remote/ && uv run ty check app/remote/`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/outbound.py tests/remote/test_outbound.py
git commit -m "feat(remote): wire live-mode activity observation and throttled edits (AC-56/57)"
```

---

### Task 6: AC-58 — close the command-menu gap (`/settings`, `/health`, `/changes`)

`_register_commands` in `app/remote/telegram/adapter.py` currently advertises `help`, `status`, `new`, `stop`, `actions`, `unpair` — missing three commands `actions.py` has dispatched since Phases 2 and 3 of the control-surface work. This is the one remaining gap in AC-58's bounded command surface.

**Files:**
- Modify: `app/remote/telegram/adapter.py`
- Test: `tests/remote/telegram/test_adapter.py`

**Interfaces:**
- Consumes: nothing new — `_register_commands` already calls `self._client.set_commands(commands)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/remote/telegram/test_adapter.py`, inside (or alongside) `class TestStartupSequence`:

```python
    @pytest.mark.asyncio
    async def test_registers_exactly_the_ac58_bounded_command_set(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        _, payload = next(c for c in transport.calls if c[0] == "setMyCommands")
        registered = [cmd["command"] for cmd in payload["commands"]]

        assert registered == [
            "help",
            "status",
            "new",
            "stop",
            "settings",
            "health",
            "changes",
            "actions",
            "unpair",
        ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest --no-cov -q tests/remote/telegram/test_adapter.py -k ac58 -v`
Expected: FAIL — `registered` is missing `"settings"`, `"health"`, `"changes"`.

- [ ] **Step 3: Implement**

In `app/remote/telegram/adapter.py`'s `_register_commands`:

```python
        commands = [
            ("help", "What can I do here?"),
            ("status", "What's my agent doing right now?"),
            ("new", "Set aside this task, start a new one"),
            ("stop", "Interrupt the agent mid-task"),
            ("settings", "Change mode, model, agent, or response style"),
            ("health", "Check system health"),
            ("changes", "See this task's file changes"),
            ("actions", "Run a workflow, project, or schedule"),
            ("unpair", "Disconnect this phone"),
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest --no-cov -q tests/remote/telegram/test_adapter.py -v`
Expected: PASS, all tests in the file green.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check app/remote/telegram/adapter.py tests/remote/telegram/test_adapter.py && uv run ty check app/remote/telegram/adapter.py`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add app/remote/telegram/adapter.py tests/remote/telegram/test_adapter.py
git commit -m "feat(remote): advertise settings/health/changes in the command menu (AC-58)"
```

---

## Final verification (after all six tasks)

- [ ] Run the full test suite: `uv run pytest --no-cov -q`
- [ ] Run `uv run ruff check .`
- [ ] Run `uv run ty check app/`
- [ ] Merge to local `main` following this session's established pattern: check `git status --short` on the main checkout first (never overwrite unreviewed WIP), fast-forward merge, re-run the full suite on the merged result, no push.

## Out of scope for this plan

- **AC-53** (providers read-only listing) — this is a new, unbuilt capability (there is no provider-listing action or `/settings` "Providers" row yet), not an audit of existing code. Left for a dedicated follow-up.
- **Phase 6 — onboarding** (AC-54's richer first-run card with Set up/Health check/Just start working buttons) — unrelated to live mode; left for its own plan.
