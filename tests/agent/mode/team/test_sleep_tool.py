"""Tests for the ``sleep`` tool — the only way to end a turn while waiting.

There is deliberately no text form: ``<sleep>`` in a reply is ordinary prose.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.mode.team.sleep import _MAX_GUARD_REFUSALS, make_sleep_tool
from app.agent.permission import _SAFE_TOOLS
from app.agent.mode.team.tier_policy import SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS


def _state():
    return SimpleNamespace(metadata={})


class TestSleepTool:
    def test_takes_no_arguments(self):
        definition = make_sleep_tool().definition["function"]
        assert definition["name"] == "sleep"
        assert definition["parameters"]["properties"] == {}
        assert definition["parameters"]["required"] == []

    @pytest.mark.asyncio
    async def test_call_asks_the_loop_to_stop_after_the_turn(self):
        state = _state()

        result = await make_sleep_tool().arun(_injected={"_state": state})

        assert state.metadata["stop_after_tool_call"] == "sleep"
        assert result == "Sleeping until the next message."

    @pytest.mark.asyncio
    async def test_runs_without_a_run_context(self):
        assert await make_sleep_tool().arun() == "Sleeping until the next message."

    def test_description_tells_the_model_not_to_write_text(self):
        description = make_sleep_tool().description
        assert "Takes no arguments" in description
        assert "Never write text" in description


class TestSleepGuard:
    """The optional team-owned guard that refuses an early yield.

    ``AgentTeam`` injects this for the lead so it cannot stop while an isolated
    delegation's worktree is unresolved; members get no guard.
    """

    @pytest.mark.asyncio
    async def test_refusal_is_returned_and_the_turn_continues(self):
        state = _state()

        async def guard():
            return "task t-1 is still unmerged"

        result = await make_sleep_tool(guard=guard).arun(_injected={"_state": state})

        assert result == "task t-1 is still unmerged"
        assert "stop_after_tool_call" not in state.metadata

    @pytest.mark.asyncio
    async def test_allowing_the_yield_stops_the_turn(self):
        state = _state()

        async def guard():
            return None

        result = await make_sleep_tool(guard=guard).arun(_injected={"_state": state})

        assert state.metadata["stop_after_tool_call"] == "sleep"
        assert result == "Sleeping until the next message."

    @pytest.mark.asyncio
    async def test_refusals_are_bounded_per_run(self):
        state = _state()

        async def guard():
            return "task t-1 is still unmerged"

        tool = make_sleep_tool(guard=guard)
        for _ in range(_MAX_GUARD_REFUSALS):
            assert (
                await tool.arun(_injected={"_state": state})
                == "task t-1 is still unmerged"
            )
            assert "stop_after_tool_call" not in state.metadata

        assert (
            await tool.arun(_injected={"_state": state})
            == "Sleeping until the next message."
        )
        assert state.metadata["stop_after_tool_call"] == "sleep"

    @pytest.mark.asyncio
    async def test_broken_guard_does_not_trap_the_agent(self):
        state = _state()

        async def guard():
            raise RuntimeError("ledger unavailable")

        result = await make_sleep_tool(guard=guard).arun(_injected={"_state": state})

        assert result == "Sleeping until the next message."
        assert state.metadata["stop_after_tool_call"] == "sleep"

    @pytest.mark.asyncio
    async def test_refusal_without_run_state_still_yields(self):
        async def guard():
            return "task t-1 is still unmerged"

        assert (
            await make_sleep_tool(guard=guard).arun()
            == "Sleeping until the next message."
        )


class TestSleepPolicy:
    def test_needs_no_permission_prompt(self):
        assert "sleep" in _SAFE_TOOLS

    def test_side_chat_never_gets_it(self):
        assert "sleep" in SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS
