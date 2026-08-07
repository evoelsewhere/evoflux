from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agent.hooks.tool_context_projection import ToolContextProjectionHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    ToolCall,
    ToolMessage,
)
from app.agent.state import AgentState, ModelRequest, RunContext


def _batch(index: int, *, size: int = 2_000, name: str = "grep"):
    call_id = f"call-{index}"
    return [
        AssistantMessage(
            tool_calls=[
                ToolCall(
                    id=call_id,
                    function=FunctionCall(name=name, arguments='{"query":"x"}'),
                )
            ]
        ),
        ToolMessage(
            content=f"result-{index}\n" + "x" * size,
            tool_call_id=call_id,
            name=name,
        ),
    ]


@pytest.mark.asyncio
async def test_projects_old_results_without_mutating_durable_messages():
    messages = [*_batch(1), *_batch(2), *_batch(3)]
    state = AgentState(messages=messages)
    request = ModelRequest(messages=tuple(messages), system_prompt="")
    handler = AsyncMock(return_value=AssistantMessage(content="ok"))

    await ToolContextProjectionHook(keep_recent_batches=2).wrap_model_call(
        RunContext(session_id="s", run_id="r", agent_name="evoflux"),
        state,
        request,
        handler,
    )

    sent = handler.await_args.args[0]
    assert "Earlier grep result compacted" in sent.messages[1].content
    assert "result-2" in sent.messages[3].content
    assert "result-3" in sent.messages[5].content
    assert len(messages[1].content or "") > 2_000
    assert state.metadata["tool_context_projection"]["saved_chars"] > 0


@pytest.mark.asyncio
async def test_preserves_skill_and_multimodal_results():
    messages = [
        *_batch(1),
        AssistantMessage(
            tool_calls=[
                ToolCall(
                    id="skill-1",
                    function=FunctionCall(name="skill", arguments="{}"),
                )
            ]
        ),
        ToolMessage(content="s" * 3_000, tool_call_id="skill-1", name="skill"),
        *_batch(2),
    ]
    state = AgentState(messages=messages)
    handler = AsyncMock(return_value=AssistantMessage(content="ok"))

    await ToolContextProjectionHook(keep_recent_batches=1).wrap_model_call(
        RunContext(session_id="s", run_id="r", agent_name="evoflux"),
        state,
        ModelRequest(messages=tuple(messages), system_prompt=""),
        handler,
    )

    sent = handler.await_args.args[0]
    skill_result = next(
        message
        for message in sent.messages
        if isinstance(message, ToolMessage) and message.name == "skill"
    )
    assert skill_result.content == "s" * 3_000


@pytest.mark.asyncio
async def test_projects_new_text_tools_without_an_allowlist_change():
    messages = [*_batch(1, name="future_tool"), *_batch(2)]
    state = AgentState(messages=messages)
    handler = AsyncMock(return_value=AssistantMessage(content="ok"))

    await ToolContextProjectionHook(keep_recent_batches=1).wrap_model_call(
        RunContext(session_id="s", run_id="r", agent_name="evoflux"),
        state,
        ModelRequest(messages=tuple(messages), system_prompt=""),
        handler,
    )

    sent = handler.await_args.args[0]
    assert "Earlier future_tool result compacted" in sent.messages[1].content


@pytest.mark.asyncio
async def test_single_line_receipt_stays_bounded():
    messages = [*_batch(1, size=20_000), *_batch(2)]
    messages[1].content = "x" * 20_000
    state = AgentState(messages=messages)
    handler = AsyncMock(return_value=AssistantMessage(content="ok"))

    await ToolContextProjectionHook(keep_recent_batches=1).wrap_model_call(
        RunContext(session_id="s", run_id="r", agent_name="evoflux"),
        state,
        ModelRequest(messages=tuple(messages), system_prompt=""),
        handler,
    )

    sent = handler.await_args.args[0]
    assert len(sent.messages[1].content) < 1_200
