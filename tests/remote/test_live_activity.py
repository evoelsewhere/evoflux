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
