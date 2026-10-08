"""Tests for the ``sleep`` tool — the only way to end a turn while waiting.

There is deliberately no text form: ``<sleep>`` in a reply is ordinary prose.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.mode.team.sleep import make_sleep_tool
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

    def test_is_not_deferred(self):
        """A waiting agent must be able to call it without a load_tool round."""
        assert make_sleep_tool().deferred is False


class TestSleepPolicy:
    def test_needs_no_permission_prompt(self):
        assert "sleep" in _SAFE_TOOLS

    def test_side_chat_never_gets_it(self):
        assert "sleep" in SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS
