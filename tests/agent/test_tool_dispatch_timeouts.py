from __future__ import annotations

import asyncio

import pytest

from app.agent.agent_loop.tool_dispatch import NETWORK_TOOL_TIMEOUTS, _run_bounded
from app.agent.schemas.chat import FunctionCall, ToolCall


@pytest.mark.asyncio
async def test_network_tool_timeout_cancels_work_and_returns_tool_result(monkeypatch):
    monkeypatch.setitem(NETWORK_TOOL_TIMEOUTS, "web_search", 0.01)
    tool_call = ToolCall(
        id="call-1",
        function=FunctionCall(name="web_search", arguments="{}"),
    )
    cancelled = False

    async def slow_tool() -> str:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        finally:
            cancelled = True

    result = await _run_bounded(slow_tool(), tool_call, "agent")

    assert result == (
        tool_call,
        "Tool timed out after 0s and was cancelled.",
    )
    assert cancelled


@pytest.mark.asyncio
async def test_non_network_tool_timeout_is_not_overridden():
    tool_call = ToolCall(
        id="call-2",
        function=FunctionCall(name="custom_tool", arguments="{}"),
    )

    assert (
        await _run_bounded(asyncio.sleep(0, result="done"), tool_call, "agent")
        == "done"
    )
