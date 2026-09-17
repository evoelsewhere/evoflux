"""Regression tests for session-level prompt-prefix snapshots."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlmodel import select

from app.agent.agent_loop import Agent
from app.agent.checkpointer import SQLiteCheckpointer
from app.agent.hooks.base import BaseAgentHook
from app.agent.hooks.prefix_snapshot import SessionPrefixSnapshotHook
from app.agent.providers.base import LLMProviderBase
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatMessage,
    HumanMessage,
)
from app.agent.state import AgentState, ModelRequest, RunContext
from app.agent.schemas.agent import RunConfig
from app.models.chat import ChatSession
from app.models.prompt_cache import SessionPrefixSnapshot
from app.services.prompt_prefix import prefix_profile_key


class _CaptureProvider(LLMProviderBase):
    model = "mock-model"

    def __init__(self) -> None:
        super().__init__()
        self.system_prompts: list[str] = []

    def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AsyncIterator[ChatCompletionChunk]:
        self.system_prompts.append(messages[0].content or "")

        async def _gen() -> AsyncIterator[ChatCompletionChunk]:
            yield ChatCompletionChunk(
                id="chunk",
                created=1,
                model=self.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionDelta(content="ok"),
                        finish_reason="stop",
                    )
                ],
            )

        return _gen()

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> AssistantMessage:
        return AssistantMessage(content="ok")


class _DynamicSystemHook(BaseAgentHook):
    def __init__(self, value: str) -> None:
        self._value = value

    async def wrap_model_call(self, ctx, state, request, handler):
        return await handler(request.override(system_prompt=self._value))


def _ctx(session_id: uuid.UUID) -> RunContext:
    return RunContext(session_id=str(session_id), run_id="run-1", agent_name="lead")


def test_profile_key_is_independent_of_mapping_insertion_order():
    assert prefix_profile_key({"model": "mimo", "agent": "lead"}) == (
        prefix_profile_key({"agent": "lead", "model": "mimo"})
    )


@pytest.mark.asyncio
async def test_snapshot_freezes_final_system_prefix_across_runs(setup_db):
    from app.core.db import async_session_factory

    session_id = uuid.uuid7()
    async with async_session_factory() as db:
        db.add(ChatSession(id=session_id, agent_name="lead"))
        await db.commit()

    profile = {
        "provider_id": "xiaomi",
        "model_id": "xiaomi:mimo-v2.5",
        "agent": "lead",
        "agent_id": "lead",
        "mode": "coding",
        "role": "lead",
        "permission_mode": "auto",
        "system_prompt": "Base",
    }
    first_hook = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile=profile,
    )
    state = AgentState(
        messages=[HumanMessage(content="first")],
        tool_defs=[{"type": "function", "function": {"name": "shell"}}],
    )
    captured: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        captured.append(request)
        return AssistantMessage(content="ok")

    await first_hook.before_agent(_ctx(session_id), state)
    await first_hook.wrap_model_call(
        _ctx(session_id),
        state,
        ModelRequest(messages=tuple(state.messages), system_prompt="assembled v1"),
        handler,
    )

    second_hook = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile=profile,
    )
    second_state = AgentState(
        messages=[HumanMessage(content="second")],
        tool_defs=state.tool_defs,
    )
    await second_hook.before_agent(_ctx(session_id), second_state)
    frozen = await second_hook.before_model(
        _ctx(session_id),
        second_state,
        ModelRequest(messages=tuple(second_state.messages), system_prompt="changed"),
    )
    assert frozen is not None
    assert frozen.system_prompt == "assembled v1"

    await second_hook.wrap_model_call(
        _ctx(session_id),
        second_state,
        frozen,
        handler,
    )

    assert [request.system_prompt for request in captured] == [
        "assembled v1",
        "assembled v1",
    ]
    async with async_session_factory() as db:
        rows = list(
            (
                await db.exec(
                    select(SessionPrefixSnapshot).where(
                        SessionPrefixSnapshot.session_id == session_id
                    )
                )
            ).all()
        )
    assert len(rows) == 1
    assert rows[0].revision == 1


@pytest.mark.asyncio
async def test_tool_contract_change_rotates_snapshot(setup_db):
    from app.core.db import async_session_factory

    session_id = uuid.uuid7()
    async with async_session_factory() as db:
        db.add(ChatSession(id=session_id, agent_name="lead"))
        await db.commit()

    hook = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile={"provider_id": "xiaomi", "model_id": "mimo-v2.5"},
    )
    state = AgentState(messages=[HumanMessage(content="task")], tool_defs=[])
    captured: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        captured.append(request)
        return AssistantMessage(content="ok")

    await hook.before_agent(_ctx(session_id), state)
    await hook.wrap_model_call(
        _ctx(session_id),
        state,
        ModelRequest(messages=tuple(state.messages), system_prompt="v1"),
        handler,
    )

    state.tool_defs = [{"type": "function", "function": {"name": "grep"}}]
    assert (
        await hook.before_model(
            _ctx(session_id),
            state,
            ModelRequest(messages=tuple(state.messages), system_prompt="v2"),
        )
        is None
    )
    await hook.wrap_model_call(
        _ctx(session_id),
        state,
        ModelRequest(messages=tuple(state.messages), system_prompt="v2"),
        handler,
    )

    assert [request.system_prompt for request in captured] == ["v1", "v2"]
    async with async_session_factory() as db:
        row = (
            await db.exec(
                select(SessionPrefixSnapshot).where(
                    SessionPrefixSnapshot.session_id == session_id
                )
            )
        ).first()
    assert row is not None
    assert row.revision == 2
    assert row.system_prompt == "v2"


@pytest.mark.asyncio
async def test_checkpointer_advances_snapshot_watermark_after_assistant_persist(
    setup_db,
):
    from app.core.db import async_session_factory

    session_id = uuid.uuid7()
    async with async_session_factory() as db:
        db.add(ChatSession(id=session_id, agent_name="lead"))
        await db.commit()

    profile = {"provider_id": "mock", "model_id": "mock-model"}
    hook = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile=profile,
    )
    state = AgentState(messages=[HumanMessage(content="task")])
    await hook.before_agent(_ctx(session_id), state)

    await hook.wrap_model_call(
        _ctx(session_id),
        state,
        ModelRequest(messages=tuple(state.messages), system_prompt="stable"),
        lambda request: _assistant_response(),
    )

    assistant = AssistantMessage(content="done")
    state.messages.append(assistant)
    checkpointer = SQLiteCheckpointer(async_session_factory)
    await checkpointer.sync(_ctx(session_id), state)

    async with async_session_factory() as db:
        row = (
            await db.exec(
                select(SessionPrefixSnapshot).where(
                    SessionPrefixSnapshot.session_id == session_id
                )
            )
        ).first()
    assert row is not None
    assert assistant.db_id is not None
    assert row.watermark_message_id == assistant.db_id


async def _assistant_response() -> AssistantMessage:
    return AssistantMessage(content="ok")


@pytest.mark.asyncio
async def test_agent_run_places_snapshot_after_other_model_hooks(setup_db):
    from app.core.db import async_session_factory

    session_id = uuid.uuid7()
    async with async_session_factory() as db:
        db.add(ChatSession(id=session_id, agent_name="lead"))
        await db.commit()

    profile = {"provider_id": "mock", "model_id": "mock-model", "agent": "bot"}
    provider = _CaptureProvider()
    first_snapshot = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile=profile,
    )
    agent = Agent(name="bot", llm_provider=provider, system_prompt="base")
    await agent.run(
        [HumanMessage(content="first")],
        config=RunConfig(session_id=str(session_id)),
        hooks=[_DynamicSystemHook("assembled-v1")],
        final_model_hooks=[first_snapshot],
    )

    second_snapshot = SessionPrefixSnapshotHook(
        db_factory=async_session_factory,
        session_id=str(session_id),
        profile=profile,
    )
    await agent.run(
        [HumanMessage(content="second")],
        config=RunConfig(session_id=str(session_id)),
        hooks=[_DynamicSystemHook("assembled-v2")],
        final_model_hooks=[second_snapshot],
    )

    assert provider.system_prompts == ["assembled-v1", "assembled-v1"]
