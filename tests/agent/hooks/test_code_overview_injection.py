"""Tests for CodeOverviewHook."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.hooks.code_overview_injection import CodeOverviewHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.agent.state import AgentState


def _make_state(messages=None):
    return AgentState(messages=messages or [])


def _make_ctx(agent_name="test-agent"):
    return SimpleNamespace(agent_name=agent_name, session_id=None, run_id="r1")


_OVERVIEW_TEXT = (
    "Code index: 100 nodes, 200 edges, 10 files.\n"
    "Languages: python, typescript\n"
    "Symbol kinds: class=5, function=50, method=45\n"
    "Densest files:\n  app/server.py (12 symbols)"
)


class TestCodeOverviewHook:
    @pytest.mark.asyncio
    async def test_injects_overview_on_first_turn(self):
        hook = CodeOverviewHook()
        state = _make_state([HumanMessage(content="Hello")])
        ctx = _make_ctx()

        with patch.object(hook, "_fetch_overview", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _OVERVIEW_TEXT
            await hook.before_agent(ctx, state)

        # [HumanMessage, AssistantMessage(tool_call), ToolMessage]
        assert len(state.messages) == 3
        assert isinstance(state.messages[0], HumanMessage)
        assert isinstance(state.messages[1], AssistantMessage)
        assert state.messages[1].tool_calls is not None
        assert len(state.messages[1].tool_calls) == 1
        assert state.messages[1].tool_calls[0].function.name == "code_overview"
        assert isinstance(state.messages[2], ToolMessage)
        assert state.messages[2].content == _OVERVIEW_TEXT
        assert state.messages[2].name == "code_overview"

    @pytest.mark.asyncio
    async def test_skips_when_code_tools_already_in_history(self):
        from app.agent.schemas.chat import FunctionCall, ToolCall

        hook = CodeOverviewHook()
        existing_tc = ToolCall(
            id="existing_1",
            function=FunctionCall(name="code_search", arguments='{"query":"foo"}'),
        )
        state = _make_state(
            [
                HumanMessage(content="Hi"),
                AssistantMessage(content=None, tool_calls=[existing_tc]),
                ToolMessage(
                    tool_call_id="existing_1", name="code_search", content="Found 3"
                ),
            ]
        )
        ctx = _make_ctx()

        with patch.object(hook, "_fetch_overview", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _OVERVIEW_TEXT
            await hook.before_agent(ctx, state)

        # No new messages injected
        assert len(state.messages) == 3
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_human_message(self):
        hook = CodeOverviewHook()
        state = _make_state([])
        ctx = _make_ctx()

        with patch.object(hook, "_fetch_overview", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _OVERVIEW_TEXT
            await hook.before_agent(ctx, state)

        assert len(state.messages) == 0
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_overview_returns_none(self):
        hook = CodeOverviewHook()
        state = _make_state([HumanMessage(content="Hi")])
        ctx = _make_ctx()

        with patch.object(hook, "_fetch_overview", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None
            await hook.before_agent(ctx, state)

        # No injection
        assert len(state.messages) == 1

    @pytest.mark.asyncio
    async def test_preserves_existing_messages_after_injection(self):
        hook = CodeOverviewHook()
        state = _make_state(
            [
                HumanMessage(content="First"),
                AssistantMessage(content="Reply"),
                HumanMessage(content="Second"),
            ]
        )
        ctx = _make_ctx()

        with patch.object(hook, "_fetch_overview", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _OVERVIEW_TEXT
            await hook.before_agent(ctx, state)

        # [Human, AssistantSynthetic, ToolMessage, AssistantOriginal, Human]
        assert len(state.messages) == 5
        assert isinstance(state.messages[0], HumanMessage)
        assert state.messages[0].content == "First"
        assert isinstance(state.messages[1], AssistantMessage)
        assert state.messages[1].tool_calls is not None  # synthetic
        assert isinstance(state.messages[2], ToolMessage)
        assert state.messages[3].content == "Reply"
        assert isinstance(state.messages[4], HumanMessage)
        assert state.messages[4].content == "Second"
