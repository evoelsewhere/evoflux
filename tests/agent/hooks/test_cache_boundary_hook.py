"""Tests for CacheBoundaryHook — the prompt-cache split marker."""

from __future__ import annotations

import pytest

from app.agent.hooks.cache_boundary import CACHE_VOLATILE_MARKER, CacheBoundaryHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.state import AgentState, ModelRequest, RunContext


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state() -> AgentState:
    return AgentState(messages=[HumanMessage(content="hi")], system_prompt="Base.")


@pytest.mark.asyncio
async def test_cache_boundary_hook_appends_marker_to_system_prompt() -> None:
    hook = CacheBoundaryHook()
    request = ModelRequest(messages=(), system_prompt="stable head")
    seen: list[str] = []

    async def handler(req: ModelRequest) -> AssistantMessage:
        seen.append(req.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), request, handler)

    assert seen == [f"stable head{CACHE_VOLATILE_MARKER}"]
