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


async def _project(messages, *, keep: int):
    """Run the hook over *messages* and return what it sent to the provider."""
    handler = AsyncMock(return_value=AssistantMessage(content="ok"))
    await ToolContextProjectionHook(keep_recent_batches=keep).wrap_model_call(
        RunContext(session_id="s", run_id="r", agent_name="evoflux"),
        AgentState(messages=messages),
        ModelRequest(messages=tuple(messages), system_prompt=""),
        handler,
    )
    return handler.await_args.args[0]


@pytest.mark.asyncio
async def test_projects_old_results_without_mutating_durable_messages():
    messages = [*_batch(1), *_batch(2), *_batch(3), *_batch(4)]
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
    assert "Earlier grep result compacted" in sent.messages[3].content
    assert "result-3" in sent.messages[5].content
    assert "result-4" in sent.messages[7].content
    assert len(messages[1].content or "") > 2_000
    assert state.metadata["tool_context_projection"]["saved_chars"] > 0


@pytest.mark.asyncio
async def test_boundary_holds_still_while_the_conversation_grows():
    """A batch appended must not re-compact a batch the provider already saw.

    The boundary is what the prompt cache keys on: moving it by one on every
    batch rewrites an already-cached message and discards the whole tail.
    """
    keep = 3
    history: list = []
    seen: list[set[int]] = []
    for index in range(1, 11):
        history = [*history, *_batch(index)]
        sent = await _project(history, keep=keep)
        seen.append(
            {
                position
                for position, message in enumerate(sent.messages)
                if isinstance(message, ToolMessage)
                and "compacted" in (message.content or "")
            }
        )

    # The compacted set only ever grows — nothing is un-compacted.
    for earlier, later in zip(seen, seen[1:]):
        assert earlier <= later

    moves = sum(1 for earlier, later in zip(seen, seen[1:]) if earlier != later)
    # Ten batches, a window of three: the boundary steps at six and at nine.
    # Recomputing "all but the last three" per call would instead have moved it
    # on every batch from the fourth on — seven rewrites of cached history.
    assert moves == 2


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
