"""Tests for LoopEngine v2 — goal-based termination, prompt evolution,
verification, no-progress detection, token budget, and audit trail."""

from __future__ import annotations

import time

from app.agent.mode.team.loop_engine import (
    LoopConfig,
    LoopEngine,
    LoopState,
    LoopTurnRecord,
    classify_error,
    normalize_error_signature,
)


# ── normalize_error_signature ────────────────────────────────────────────────


class TestNormalizeErrorSignature:
    def test_strips_line_col_numbers(self) -> None:
        sig = normalize_error_signature("ImportError at 42:5 No module named 'foo'")
        assert "42:5" not in sig

    def test_strips_file_paths(self) -> None:
        sig = normalize_error_signature("error in /usr/local/lib/python3.12/foo.py")
        assert "/usr/local" not in sig

    def test_strips_timestamps(self) -> None:
        sig = normalize_error_signature("2024-01-15T12:30:45 connection failed")
        assert "2024-01-15T12:30:45" not in sig

    def test_strips_uuids(self) -> None:
        sig = normalize_error_signature(
            "task a1b2c3d4-e5f6-7890-abcd-ef1234567890 failed"
        )
        assert "a1b2c3d4" not in sig

    def test_same_errors_produce_same_signature(self) -> None:
        e1 = "AssertionError at 10:5: expected 5, got 3"
        e2 = "AssertionError at 42:8: expected 5, got 3"
        assert normalize_error_signature(e1) == normalize_error_signature(e2)

    def test_different_errors_produce_different_signatures(self) -> None:
        e1 = "AssertionError: expected 5, got 3"
        e2 = "ImportError: No module named foo"
        assert normalize_error_signature(e1) != normalize_error_signature(e2)

    def test_collapses_whitespace(self) -> None:
        sig = normalize_error_signature("  too   many    spaces  ")
        assert "  " not in sig
        assert sig == "too many spaces"


# ── classify_error ───────────────────────────────────────────────────────────


class TestClassifyError:
    def test_test_failure_is_recoverable(self) -> None:
        assert classify_error("AssertionError: expected True, got False") == "recoverable"

    def test_type_error_is_recoverable(self) -> None:
        assert classify_error("TypeError: unsupported operand") == "recoverable"

    def test_missing_credential_is_fatal(self) -> None:
        assert classify_error("Missing credential: API key not found") == "fatal"

    def test_permission_denied_is_fatal(self) -> None:
        assert classify_error("Permission denied: /root/secret") == "fatal"

    def test_enomem_is_fatal(self) -> None:
        assert classify_error("OSError: [Errno 12] ENOMEM") == "fatal"

    def test_rate_limit_is_fatal(self) -> None:
        assert classify_error("Rate limit exceeded, try again later") == "fatal"

    def test_empty_error_is_recoverable(self) -> None:
        assert classify_error("") == "recoverable"


# ── LoopEngine construction ──────────────────────────────────────────────────


class TestLoopEngineConstruction:
    def test_default_config(self) -> None:
        config = LoopConfig(prompt="test prompt")
        engine = LoopEngine(config)

        assert engine.config.prompt == "test prompt"
        assert engine.config.max_iterations == 10
        assert engine.config.goal is None
        assert engine.config.evolve_prompt is True
        assert engine.config.max_total_tokens is None
        assert engine.config.no_progress_threshold == 3
        assert engine.config.verify_command is None
        assert engine.config.max_consecutive_errors == 3
        assert engine.config.delay_between_iterations == 0.0

    def test_initial_state(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=5)
        engine = LoopEngine(config)

        state = engine.state
        assert state.remaining == 5
        assert state.paused is False
        assert state.current_iteration == 0
        assert state.total_tokens_used == 0
        assert state.consecutive_errors == 0
        assert state.consecutive_same_error == 0
        assert state.last_error is None
        assert state.goal_met is False
        assert state.turn_history == []

    def test_stop_reason_initially_none(self) -> None:
        engine = LoopEngine(LoopConfig(prompt="test"))
        assert engine.stop_reason is None


# ── should_continue ──────────────────────────────────────────────────────────


class TestShouldContinue:
    def test_simple_repeat_no_termination(self) -> None:
        """Basic loop without goal/verifier behaves like old system."""
        config = LoopConfig(prompt="do something", max_iterations=3)
        engine = LoopEngine(config)

        assert engine.should_continue() is True

    def test_stops_when_remaining_zero(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=1)
        engine = LoopEngine(config)
        engine.begin_iteration()

        assert engine.should_continue() is False
        assert engine.stop_reason == "max_iterations"

    def test_stops_when_paused(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=5)
        engine = LoopEngine(config)
        engine.pause()

        assert engine.should_continue() is False

    def test_resumes_after_pause(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=5)
        engine = LoopEngine(config)
        engine.pause()
        engine.resume()

        assert engine.should_continue() is True

    def test_stops_when_goal_met(self) -> None:
        config = LoopConfig(prompt="test", goal="all tests pass")
        engine = LoopEngine(config)
        engine.check_goal_met(verifier_passed=True)

        assert engine.should_continue() is False
        assert engine.stop_reason == "goal_met"

    def test_stops_on_token_budget(self) -> None:
        config = LoopConfig(prompt="test", max_total_tokens=100)
        engine = LoopEngine(config)
        engine.state.total_tokens_used = 150

        assert engine.should_continue() is False
        assert engine.stop_reason == "token_budget"

    def test_stops_on_no_progress(self) -> None:
        config = LoopConfig(prompt="test", no_progress_threshold=3)
        engine = LoopEngine(config)
        engine.state.consecutive_same_error = 3

        assert engine.should_continue() is False
        assert engine.stop_reason == "no_progress"

    def test_stops_on_fatal_error(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        # Simulate a turn with a fatal error
        engine.begin_iteration()
        engine.record_error("Missing credential: API key", category="fatal")

        assert engine.should_continue() is False
        assert engine.stop_reason == "fatal_error"

    def test_stops_on_max_consecutive_errors(self) -> None:
        config = LoopConfig(prompt="test", max_consecutive_errors=2)
        engine = LoopEngine(config)
        engine.state.consecutive_errors = 2

        assert engine.should_continue() is False
        assert engine.stop_reason == "max_errors"

    def test_priority_goal_over_max_iterations(self) -> None:
        """Goal met takes priority over max iterations."""
        config = LoopConfig(prompt="test", max_iterations=10, goal="done")
        engine = LoopEngine(config)
        engine.state.remaining = 0  # Would trigger max_iterations
        engine.check_goal_met(verifier_passed=True)  # But goal takes priority

        # should_continue() evaluates in priority order and sets stop_reason
        assert engine.should_continue() is False
        assert engine.stop_reason == "goal_met"


# ── begin_iteration / record_success / record_error ──────────────────────────


class TestIterationLifecycle:
    def test_begin_iteration_decrements_remaining(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=5)
        engine = LoopEngine(config)

        engine.begin_iteration()
        assert engine.state.remaining == 4
        assert engine.state.current_iteration == 1

    def test_begin_iteration_returns_record(self) -> None:
        config = LoopConfig(prompt="test prompt", max_iterations=3)
        engine = LoopEngine(config)

        record = engine.begin_iteration()
        assert record.iteration == 1
        assert record.prompt == "test prompt"
        assert record.started_at > 0

    def test_record_success_clears_error_state(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()

        engine.record_success(tokens=50)

        assert engine.state.consecutive_errors == 0
        assert engine.state.consecutive_same_error == 0
        assert engine.state.last_error is None
        assert engine.state.total_tokens_used == 50

    def test_record_success_appends_to_history(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()

        engine.record_success(tokens=30)

        assert len(engine.state.turn_history) == 1
        record = engine.state.turn_history[0]
        assert record.success is True
        assert record.tokens_used == 30
        assert record.completed_at is not None

    def test_record_error_increments_consecutive_errors(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()

        engine.record_error("first error")

        assert engine.state.consecutive_errors == 1
        assert engine.state.last_error == "first error"

    def test_record_error_classifies_automatically(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()

        engine.record_error("ImportError: No module named foo")

        record = engine.state.turn_history[0]
        assert record.error_category == "recoverable"

    def test_record_fatal_error_classified_correctly(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()

        engine.record_error("Missing credential: API key not found")

        record = engine.state.turn_history[0]
        assert record.error_category == "fatal"

    def test_same_error_increments_same_error_counter(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)

        engine.begin_iteration()
        engine.record_error("AssertionError at 10:5: expected True")

        engine.begin_iteration()
        engine.record_error("AssertionError at 42:8: expected True")

        # Same signature (line:col stripped)
        assert engine.state.consecutive_same_error == 2

    def test_different_error_resets_same_error_counter(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)

        engine.begin_iteration()
        engine.record_error("AssertionError: expected True")

        engine.begin_iteration()
        engine.record_error("ImportError: No module named foo")

        assert engine.state.consecutive_same_error == 1

    def test_success_resets_consecutive_errors(self) -> None:
        config = LoopConfig(prompt="test", max_consecutive_errors=5)
        engine = LoopEngine(config)

        engine.begin_iteration()
        engine.record_error("first error")
        assert engine.state.consecutive_errors == 1

        engine.begin_iteration()
        engine.record_success()
        assert engine.state.consecutive_errors == 0

        engine.begin_iteration()
        engine.record_error("new error")
        assert engine.state.consecutive_errors == 1


# ── Prompt evolution ─────────────────────────────────────────────────────────


class TestPromptEvolution:
    def test_no_evolution_when_disabled(self) -> None:
        config = LoopConfig(prompt="fix the bug", evolve_prompt=False)
        engine = LoopEngine(config)
        engine.begin_iteration()
        engine.record_error("ImportError at line 42")

        prompt = engine.get_effective_prompt()
        assert prompt == "fix the bug"

    def test_evolution_after_failure(self) -> None:
        config = LoopConfig(prompt="fix the bug", evolve_prompt=True)
        engine = LoopEngine(config)
        engine.begin_iteration()
        engine.record_error("ImportError at line 42")

        prompt = engine.get_effective_prompt()
        assert prompt != "fix the bug"
        assert "fix the bug" in prompt
        assert "Previous attempt" in prompt
        assert "ImportError at line 42" in prompt
        assert "different approach" in prompt

    def test_no_evolution_when_no_history(self) -> None:
        config = LoopConfig(prompt="fix the bug", evolve_prompt=True)
        engine = LoopEngine(config)

        # First iteration — no history yet, use original prompt
        prompt = engine.get_effective_prompt()
        assert prompt == "fix the bug"

    def test_no_evolution_after_success(self) -> None:
        config = LoopConfig(prompt="fix the bug", evolve_prompt=True)
        engine = LoopEngine(config)
        engine.begin_iteration()
        engine.record_success()

        prompt = engine.get_effective_prompt()
        assert prompt == "fix the bug"


# ── Goal-based termination ──────────────────────────────────────────────────


class TestGoalBasedTermination:
    def test_goal_not_met_keeps_going(self) -> None:
        config = LoopConfig(prompt="fix tests", goal="all tests pass")
        engine = LoopEngine(config)
        engine.check_goal_met(verifier_passed=False)

        assert engine.state.goal_met is False
        assert engine.should_continue() is True

    def test_goal_met_stops(self) -> None:
        config = LoopConfig(prompt="fix tests", goal="all tests pass")
        engine = LoopEngine(config)
        engine.check_goal_met(verifier_passed=True)

        assert engine.state.goal_met is True
        assert engine.should_continue() is False
        assert engine.stop_reason == "goal_met"

    def test_check_goal_without_goal_set(self) -> None:
        config = LoopConfig(prompt="fix tests")  # no goal
        engine = LoopEngine(config)
        result = engine.check_goal_met(verifier_passed=True)

        # Without a goal, check_goal_met returns False
        assert result is False
        assert engine.state.goal_met is False


# ── Manual stop ──────────────────────────────────────────────────────────────


class TestManualStop:
    def test_stop_sets_reason(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.stop("user_stop")

        assert engine.stop_reason == "user_stop"

    def test_stop_default_reason(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.stop()

        assert engine.stop_reason == "user_stop"


# ── Serialisation payloads ──────────────────────────────────────────────────


class TestPayloads:
    def test_status_payload_backward_compat(self) -> None:
        """Payload contains all original fields."""
        config = LoopConfig(prompt="test", max_iterations=5)
        engine = LoopEngine(config)
        engine.begin_iteration()

        payload = engine.status_payload()

        assert payload["prompt"] == "test"
        assert payload["limit"] == 5
        assert payload["remaining"] == 4
        assert payload["used"] == 1
        assert payload["paused"] is False

    def test_status_payload_new_fields(self) -> None:
        config = LoopConfig(
            prompt="test",
            max_iterations=5,
            goal="done",
            evolve_prompt=True,
            verify_command="pytest -q",
        )
        engine = LoopEngine(config)
        engine.begin_iteration()

        payload = engine.status_payload()

        assert payload["current_iteration"] == 1
        assert payload["total_tokens_used"] == 0
        assert payload["goal"] == "done"
        assert payload["goal_met"] is False
        assert payload["consecutive_errors"] == 0
        assert payload["no_progress_warning"] is False
        assert isinstance(payload["turn_history"], list)
        assert isinstance(payload["config"], dict)
        assert payload["config"]["goal"] == "done"
        assert payload["config"]["evolve_prompt"] is True
        assert payload["config"]["verify_command"] == "pytest -q"

    def test_status_payload_no_progress_warning(self) -> None:
        config = LoopConfig(prompt="test", no_progress_threshold=3)
        engine = LoopEngine(config)
        # Set consecutive_same_error to threshold-1 (=2) to trigger warning
        engine.state.consecutive_same_error = 2

        payload = engine.status_payload()
        assert payload["no_progress_warning"] is True

    def test_turn_complete_payload(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.begin_iteration()
        engine.record_success(tokens=42)
        record = engine.state.turn_history[0]

        payload = engine.turn_complete_payload(record)

        assert payload["type"] == "loop_turn_complete"
        assert payload["iteration"] == 1
        assert payload["success"] is True
        assert payload["tokens_used"] == 42
        assert isinstance(payload["duration_ms"], int)

    def test_stopped_payload_goal_met(self) -> None:
        config = LoopConfig(prompt="test", goal="done")
        engine = LoopEngine(config)
        engine.check_goal_met(verifier_passed=True)
        # Need a stop reason for the payload
        engine.stop("goal_met")

        payload = engine.stopped_payload()

        assert payload["type"] == "loop_stopped"
        assert payload["reason"] == "goal_met"
        assert payload["goal_met"] is True
        assert isinstance(payload["summary"], str)

    def test_stopped_payload_max_iterations(self) -> None:
        config = LoopConfig(prompt="test", max_iterations=2)
        engine = LoopEngine(config)
        engine.begin_iteration()
        engine.record_success()
        engine.begin_iteration()
        engine.record_success()
        # should_continue will now return False with reason max_iterations
        engine.should_continue()

        payload = engine.stopped_payload()

        assert payload["reason"] == "max_iterations"
        assert payload["total_iterations"] == 2

    def test_stopped_payload_user_stop(self) -> None:
        config = LoopConfig(prompt="test")
        engine = LoopEngine(config)
        engine.stop("user_stop")

        payload = engine.stopped_payload()
        assert payload["reason"] == "user_stop"
        assert "Stopped by user" in payload["summary"]

    def test_status_payload_turn_history_limit(self) -> None:
        """Only last 10 turns are included in the payload."""
        config = LoopConfig(prompt="test", max_iterations=15)
        engine = LoopEngine(config)

        for _ in range(12):
            engine.begin_iteration()
            engine.record_success()

        payload = engine.status_payload()
        assert len(payload["turn_history"]) == 10


# ── Full lifecycle integration ──────────────────────────────────────────────


class TestFullLifecycle:
    def test_simple_repeat_lifecycle(self) -> None:
        """Basic loop: 3 iterations, all succeed, then stops."""
        config = LoopConfig(prompt="do thing", max_iterations=3)
        engine = LoopEngine(config)

        results: list[bool] = []
        while engine.should_continue():
            engine.begin_iteration()
            engine.record_success(tokens=10)
            results.append(True)

        assert len(results) == 3
        assert engine.stop_reason == "max_iterations"
        assert engine.state.total_tokens_used == 30
        assert len(engine.state.turn_history) == 3

    def test_error_recovery_lifecycle(self) -> None:
        """Loop that fails twice then succeeds."""
        config = LoopConfig(
            prompt="fix bug",
            max_iterations=5,
            max_consecutive_errors=5,
        )
        engine = LoopEngine(config)

        # Iteration 1: fail
        engine.begin_iteration()
        engine.record_error("test failure")
        assert engine.should_continue() is True

        # Iteration 2: fail
        engine.begin_iteration()
        engine.record_error("different test failure")
        assert engine.should_continue() is True

        # Iteration 3: succeed
        engine.begin_iteration()
        engine.record_success()
        assert engine.should_continue() is True

        # Should still have iterations left
        assert engine.state.remaining == 2
        assert engine.state.consecutive_errors == 0

    def test_no_progress_detection_lifecycle(self) -> None:
        """Loop that fails with the same error 3 times, then stops."""
        config = LoopConfig(
            prompt="fix error",
            max_iterations=10,
            no_progress_threshold=3,
            max_consecutive_errors=10,
        )
        engine = LoopEngine(config)

        for _ in range(3):
            engine.begin_iteration()
            engine.record_error("AssertionError at line 5: expected True")

        assert engine.should_continue() is False
        assert engine.stop_reason == "no_progress"

    def test_token_budget_lifecycle(self) -> None:
        """Loop that hits token budget."""
        config = LoopConfig(prompt="do work", max_total_tokens=100)
        engine = LoopEngine(config)

        engine.begin_iteration()
        engine.record_success(tokens=60)
        assert engine.should_continue() is True

        engine.begin_iteration()
        engine.record_success(tokens=50)
        # Total: 110 > 100
        assert engine.should_continue() is False
        assert engine.stop_reason == "token_budget"

    def test_goal_achieved_lifecycle(self) -> None:
        """Loop where the goal is achieved after 2 iterations."""
        config = LoopConfig(
            prompt="fix tests",
            max_iterations=10,
            goal="all tests pass",
        )
        engine = LoopEngine(config)

        # Iteration 1: verifier fails
        engine.begin_iteration()
        engine.record_success()
        engine.check_goal_met(verifier_passed=False)
        assert engine.should_continue() is True

        # Iteration 2: verifier passes
        engine.begin_iteration()
        engine.record_success()
        engine.check_goal_met(verifier_passed=True)
        assert engine.should_continue() is False
        assert engine.stop_reason == "goal_met"

    def test_prompt_evolution_lifecycle(self) -> None:
        """Prompt evolves after each failure."""
        config = LoopConfig(
            prompt="fix the bug",
            max_iterations=5,
            evolve_prompt=True,
            max_consecutive_errors=5,
        )
        engine = LoopEngine(config)

        # First iteration — no evolution yet
        record1 = engine.begin_iteration()
        assert record1.prompt == "fix the bug"
        engine.record_error("ImportError at line 42")

        # Second iteration — prompt should evolve
        record2 = engine.begin_iteration()
        assert "fix the bug" in record2.prompt
        assert "Previous attempt" in record2.prompt
        assert "ImportError" in record2.prompt
        engine.record_error("AttributeError: 'NoneType'")

        # Third iteration — evolved with latest error
        record3 = engine.begin_iteration()
        assert "fix the bug" in record3.prompt
        assert "AttributeError" in record3.prompt


# ── LoopState dataclass ─────────────────────────────────────────────────────


class TestLoopStateDataclass:
    def test_default_values(self) -> None:
        config = LoopConfig(prompt="test")
        state = LoopState(config=config, remaining=10)

        assert state.paused is False
        assert state.current_iteration == 0
        assert state.total_tokens_used == 0
        assert state.consecutive_errors == 0
        assert state.turn_history == []
        assert state.goal_met is False
        assert state.started_at is None


# ── LoopTurnRecord dataclass ────────────────────────────────────────────────


class TestLoopTurnRecordDataclass:
    def test_default_values(self) -> None:
        record = LoopTurnRecord(iteration=1, prompt="test", started_at=time.time())

        assert record.completed_at is None
        assert record.success is None
        assert record.tokens_used == 0
        assert record.error is None
        assert record.error_category is None
