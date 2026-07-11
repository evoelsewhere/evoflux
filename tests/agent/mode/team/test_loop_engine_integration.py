"""Integration tests for Loop Engine v2 with AgentTeam.

Tests the full lifecycle: start → iterate → verify → stop, and
backward compatibility with existing /loop commands.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.agent.mode.team.loop_engine import LoopEngine, LoopConfig


class TestLoopEngineFullLifecycle:
    """Test complete loop lifecycle with AgentTeam."""

    async def test_loop_engine_full_lifecycle(self, basic_team, mock_stream_store):
        """Test complete loop lifecycle: start → iterate → verify → stop."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Start a loop — /loop <prompt> delivers to the lead
        await team.handle_user_message(
            "/loop run tests", session_id=session_id
        )
        assert session_id in team._loop_engines
        engine = team._loop_engines[session_id]
        assert engine.config.prompt == "run tests"

        # Verify loop status was pushed
        events = [c.args[1].event for c in mock_stream_store.call_args_list]
        assert "loop_status" in events

        # Stop the loop
        await team.handle_user_message("/loop:stop", session_id=session_id)
        assert session_id not in team._loop_engines

        await team.stop()

    async def test_loop_engine_with_verifier(self, basic_team, mock_stream_store):
        """Test loop with verify_command tracking via engine config."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Set a limit first
        await team.handle_user_message("/loop:set 5", session_id=session_id)
        assert team._loop_limits.get(session_id) == 5

        # Start a loop
        await team.handle_user_message(
            "/loop fix the tests", session_id=session_id
        )
        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.config.max_iterations == 5
        # remaining = max_iterations at creation; begin_iteration() is called
        # later when _activate_loop_message fires after lead goes idle.
        assert engine.state.remaining == 5

        # Verify loop status events were emitted
        status_events = [
            c for c in mock_stream_store.call_args_list
            if c.args[1].event == "loop_status"
        ]
        assert len(status_events) >= 2  # one for set, one for start

        await team.stop()

    async def test_loop_engine_no_progress_state_tracking(
        self, basic_team, mock_stream_store
    ):
        """Test that no-progress state is tracked via the engine."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        await team.handle_user_message("/loop:set 5", session_id=session_id)
        await team.handle_user_message(
            "/loop fix the tests", session_id=session_id
        )

        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.config.no_progress_threshold == 3  # default

        await team.stop()

    async def test_loop_engine_token_budget_state(self, basic_team, mock_stream_store):
        """Test token budget state is tracked in engine config."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        await team.handle_user_message("/loop:set 20", session_id=session_id)
        await team.handle_user_message(
            "/loop process data", session_id=session_id
        )

        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.config.max_iterations == 20
        assert engine.state.total_tokens_used == 0

        await team.stop()

    async def test_loop_engine_prompt_stored_in_config(
        self, basic_team, mock_stream_store
    ):
        """Test prompt is stored in engine config for evolution."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        original_prompt = "fix the failing test"
        await team.handle_user_message(
            f"/loop {original_prompt}", session_id=session_id
        )

        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.config.prompt == original_prompt

        await team.stop()

    async def test_loop_status_command(self, basic_team, mock_stream_store):
        """Test /loop:status returns engine status."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Before any loop — no engine exists
        status = team.loop_status(session_id)
        assert status is None

        # Start a loop
        await team.handle_user_message(
            "/loop run task", session_id=session_id
        )
        status = team.loop_status(session_id)
        assert status is not None
        assert status["prompt"] == "run task"
        assert status["remaining"] > 0

        await team.stop()

    async def test_loop_backward_compat(self, basic_team, mock_stream_store):
        """Test that /loop <prompt> without v2 features works exactly as before."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # The basic /loop command should work without any v2 config
        await team.handle_user_message(
            '/loop "just say hi"', session_id=session_id
        )

        # Engine should be created
        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.config.prompt == '"just say hi"'
        assert engine.state.remaining > 0
        assert engine.state.paused is False

        # Should be pausable/resumable/stoppable
        await team.handle_user_message("/loop:pause", session_id=session_id)
        assert engine.state.paused is True

        await team.handle_user_message("/loop:resume", session_id=session_id)
        assert engine.state.paused is False

        await team.handle_user_message("/loop:stop", session_id=session_id)
        assert session_id not in team._loop_engines

        await team.stop()

    async def test_loop_pause_blocks_activation(self, basic_team, mock_stream_store):
        """Paused loop should not activate the lead."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        await team.handle_user_message(
            "/loop run tests", session_id=session_id
        )
        await team.handle_user_message("/loop:pause", session_id=session_id)

        engine = team._loop_engines.get(session_id)
        assert engine is not None
        assert engine.state.paused is True

        # _activate_loop_message should return False when paused
        activated = await team._activate_loop_message(session_id)
        assert activated is False

        await team.stop()

    async def test_loop_set_changes_limit(self, basic_team, mock_stream_store):
        """Loop:set updates the limit for current and future loops."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Default limit should be 10
        await team.handle_user_message(
            "/loop run task", session_id=session_id
        )
        engine = team._loop_engines[session_id]
        assert engine.config.max_iterations == 10
        # remaining = max_iterations at creation (before activation)
        assert engine.state.remaining == 10

        # Stop and set new limit
        await team.handle_user_message("/loop:stop", session_id=session_id)
        await team.handle_user_message("/loop:set 20", session_id=session_id)

        # New loop uses new limit
        await team.handle_user_message(
            "/loop run task again", session_id=session_id
        )
        engine = team._loop_engines[session_id]
        assert engine.config.max_iterations == 20
        # remaining = max_iterations at creation (before activation)
        assert engine.state.remaining == 20

        await team.stop()

    async def test_loop_interrupt_stops_loop(self, basic_team, mock_stream_store):
        """Interrupting a message should stop the loop."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        await team.handle_user_message(
            "/loop run tests", session_id=session_id
        )
        assert session_id in team._loop_engines

        # Interrupt clears the loop
        await team.handle_user_message(
            "stop everything", session_id=session_id, interrupt=True
        )
        assert session_id not in team._loop_engines

        await team.stop()

    async def test_loop_status_payload_structure(self, basic_team):
        """Loop status payload has the expected keys from the engine."""
        team = basic_team
        session_id = str(uuid.uuid4())

        # Create engine directly for payload testing
        config = LoopConfig(prompt="test", max_iterations=10)
        engine = LoopEngine(config)
        team._loop_engines[session_id] = engine

        status = team.loop_status(session_id)
        assert status is not None

        expected_keys = {"prompt", "limit", "remaining", "used", "paused"}
        assert expected_keys.issubset(set(status.keys()))
        assert status["prompt"] == "test"
        assert status["limit"] == 10
        assert status["remaining"] == 10
        assert status["used"] == 0
        assert status["paused"] is False

    async def test_loop_not_available_in_non_coding_mode(self, basic_team):
        """Loop commands raise in non-coding mode."""
        team = basic_team
        team.mode = "chat"  # not coding
        session_id = str(uuid.uuid4())

        from app.agent.mode.team.team import ContinuePreconditionError

        with pytest.raises(ContinuePreconditionError):
            await team.handle_user_message(
                "/loop run tests", session_id=session_id
            )

    async def test_loop_status_subcommand_emits_event(self, basic_team, mock_stream_store):
        """/loop:status emits loop_status event from the engine."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Start a loop first
        await team.handle_user_message(
            "/loop run task", session_id=session_id
        )

        initial_count = len(mock_stream_store.call_args_list)

        # Query status
        await team.handle_user_message(
            "/loop:status", session_id=session_id
        )

        new_events = [
            c.args[1].event
            for c in mock_stream_store.call_args_list[initial_count:]
        ]
        assert "loop_status" in new_events

        await team.stop()

    async def test_loop_status_without_active_engine(self, basic_team, mock_stream_store):
        """/loop:status with no active loop still works."""
        team = basic_team
        team.mode = "coding"
        await team.start()
        session_id = str(uuid.uuid4())

        # Should not raise
        await team.handle_user_message(
            "/loop:status", session_id=session_id
        )

        await team.stop()
