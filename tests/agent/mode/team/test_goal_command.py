"""Tests for durable /goal command parsing."""

from __future__ import annotations

from app.agent.mode.team.team import is_goal_command, parse_goal_command


def test_parse_goal_start_uses_objective_text() -> None:
    command = parse_goal_command("/goal implement and verify Goal mode")

    assert command is not None
    assert command.action == "start"
    assert command.objective == "implement and verify Goal mode"


def test_bare_goal_requests_status() -> None:
    command = parse_goal_command("/goal")

    assert command is not None
    assert command.action == "status"


def test_parse_goal_controls() -> None:
    assert parse_goal_command("/goal:status").action == "status"  # type: ignore[union-attr]
    assert parse_goal_command("/goal:pause").action == "pause"  # type: ignore[union-attr]
    assert parse_goal_command("/goal:resume").action == "resume"  # type: ignore[union-attr]
    assert parse_goal_command("/goal:stop").action == "stop"  # type: ignore[union-attr]


def test_parse_goal_budget() -> None:
    limited = parse_goal_command("/goal:budget 25000")
    unlimited = parse_goal_command("/goal:budget none")

    assert limited is not None and limited.token_budget == 25_000
    assert unlimited is not None and unlimited.token_budget is None


def test_parse_goal_rejects_invalid_forms_and_set_alias() -> None:
    assert parse_goal_command("/goal:budget 0") is None
    assert parse_goal_command("/goal:budget nope") is None
    assert parse_goal_command("/goal:pause now") is None
    assert parse_goal_command("/goal:set replacement") is None


def test_is_goal_command_matches_namespace() -> None:
    assert is_goal_command("/goal objective")
    assert is_goal_command("/goal:pause")
    assert not is_goal_command("/loop prompt")
