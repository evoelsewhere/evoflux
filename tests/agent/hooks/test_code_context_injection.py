"""Tests for task-specific code context prefetch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.hooks.code_context_injection import CodeContextHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from app.agent.state import AgentState


def _ctx():  # noqa: ANN202
    return SimpleNamespace(agent_name="coding", session_id=None, run_id="run")


@pytest.mark.asyncio
async def test_injects_context_for_latest_coding_request():
    hook = CodeContextHook()
    state = AgentState(
        messages=[
            HumanMessage(content="hello"),
            AssistantMessage(content="hi"),
            HumanMessage(content="fix reconnect_session in service.py"),
        ]
    )
    with patch.object(hook, "_fetch", new_callable=AsyncMock) as fetch:
        fetch.return_value = "Code query: strategy=graph"
        await hook.before_agent(_ctx(), state)

    fetch.assert_awaited_once_with("fix reconnect_session in service.py")
    assert isinstance(state.messages[-2], AssistantMessage)
    assert state.messages[-2].tool_calls[0].function.name == "code_query"
    assert isinstance(state.messages[-1], ToolMessage)
    assert state.messages[-1].name == "code_query"


@pytest.mark.asyncio
async def test_skips_non_coding_request():
    hook = CodeContextHook()
    state = AgentState(messages=[HumanMessage(content="write a friendly greeting")])
    with patch.object(hook, "_fetch", new_callable=AsyncMock) as fetch:
        await hook.before_agent(_ctx(), state)

    fetch.assert_not_awaited()
    assert len(state.messages) == 1


@pytest.mark.asyncio
async def test_prior_turn_code_tool_does_not_block_new_turn_prefetch():
    hook = CodeContextHook()
    state = AgentState(
        messages=[
            HumanMessage(content="find old_handler"),
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="old-call",
                        function=FunctionCall(
                            name="code_query", arguments='{"query":"old_handler"}'
                        ),
                    )
                ],
            ),
            ToolMessage(tool_call_id="old-call", name="code_query", content="old"),
            AssistantMessage(content="done"),
            HumanMessage(content="fix new_handler in service.py"),
        ]
    )
    with patch.object(hook, "_fetch", new_callable=AsyncMock) as fetch:
        fetch.return_value = "Code query: strategy=graph"
        await hook.before_agent(_ctx(), state)

    fetch.assert_awaited_once_with("fix new_handler in service.py")
    assert isinstance(state.messages[-1], ToolMessage)
