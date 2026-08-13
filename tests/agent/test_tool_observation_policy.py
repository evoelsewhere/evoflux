from __future__ import annotations

import json

import pytest

from app.agent.agent_loop.tool_executor import make_tool_executor
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.schemas.chat import FunctionCall, ToolCall
from app.agent.state import AgentState, RunContext
from app.agent.tools.builtin.filesystem.read import read_file
from app.agent.tools.registry import Tool


def _call(call_id: str, name: str, arguments: dict) -> ToolCall:
    return ToolCall(
        id=call_id,
        function=FunctionCall(name=name, arguments=json.dumps(arguments)),
    )


@pytest.fixture
def observation_sandbox(tmp_path):
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            session_id="observation-test",
            denied_roots=[],
            denied_patterns=[],
        )
    )
    yield tmp_path
    _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_unchanged_read_returns_receipt_and_revision_change_invalidates_cache(
    observation_sandbox,
):
    source = observation_sandbox / "sample.txt"
    source.write_text("first\n")
    state = AgentState(messages=[], tool_names=["read"])
    execute = make_tool_executor({"read": read_file}, "agent")
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")

    first = await execute(ctx, state, _call("call-1", "read", {"path": "sample.txt"}))
    reused = await execute(ctx, state, _call("call-2", "read", {"path": "sample.txt"}))
    source.write_text("second and changed\n")
    changed = await execute(ctx, state, _call("call-3", "read", {"path": "sample.txt"}))

    assert "first" in first
    assert "Observation reused" in reused
    assert "call-1" in reused
    assert "second and changed" in changed
    assert "Observation reused" not in changed
    assert state.metadata["tool_observation_stats"]["reused"] == 1
    assert state.metadata["tool_observation_stats"]["executed"] == 2


@pytest.mark.asyncio
async def test_non_revisioned_observations_are_measured_but_never_blocked():
    executions: list[str] = []

    async def inspect(value: str) -> str:
        executions.append(value)
        return f"evidence:{value}"

    observation = Tool(
        inspect,
        name="inspect",
        read_only=True,
        observation_kind="source",
    )
    state = AgentState(messages=[], tool_names=["inspect"])
    execute = make_tool_executor({"inspect": observation}, "agent")
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")

    first = await execute(ctx, state, _call("call-1", "inspect", {"value": "a"}))
    second = await execute(ctx, state, _call("call-2", "inspect", {"value": "b"}))
    third = await execute(ctx, state, _call("call-3", "inspect", {"value": "c"}))

    assert first == "evidence:a"
    assert second == "evidence:b"
    assert third == "evidence:c"
    assert executions == ["a", "b", "c"]
    assert state.metadata["tool_observation_stats"] == {
        "requests": 3,
        "executed": 3,
        "reused": 0,
        "by_kind": {"source": 3},
    }
