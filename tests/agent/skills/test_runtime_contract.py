from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.skill_runtime_contract import SkillRuntimeContractHook
from app.agent.schemas.chat import AssistantMessage, FunctionCall, ToolCall
from app.agent.skills.activation import (
    SkillDependencyError,
    activate_skill_with_runtime,
    inject_skill_activation,
)
from app.agent.skills.models import SkillRecord
from app.agent.state import AgentState, RunContext
from app.agent.tools.registry import DeferredToolEntry


def _call(call_id: str, name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(
        id=call_id,
        function=FunctionCall(name=name, arguments=arguments),
    )


def _investigation_state() -> AgentState:
    return AgentState(
        messages=[],
        metadata={
            "skill_runtime_contracts": {
                "coding-investigation": {
                    "required_tools": ("code_graph", "code_search"),
                    "activated_tools": ("code_search",),
                }
            },
            "loaded_skills": {"coding-investigation": "body"},
            "_tool_capabilities": {
                "code_graph": ("code_graph_navigation",),
                "code_search": ("code_source_search",),
                "read": ("workspace_read",),
                "grep": ("source_navigation",),
            },
        },
    )


def _record(tmp_path: Path, *, dependency: str = "code_graph") -> SkillRecord:
    skill_dir = tmp_path / "investigate"
    skill_dir.mkdir(exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: investigate\ndescription: Investigate code.\n---\n"
        "Trace exact evidence.\n"
    )
    return SkillRecord(
        name="investigate",
        description="Investigate code.",
        skill_file=skill_file,
        root=tmp_path,
        source="test",
        modes=("coding",),
        dependencies=({"type": "builtin", "value": dependency},),
    )


@pytest.mark.asyncio
async def test_activation_atomically_enables_declared_deferred_tools(tmp_path):
    record = _record(tmp_path)
    state = AgentState(messages=[], tool_names=["skill", "code_graph"])
    state.metadata["deferred_tool_catalog"] = {
        "code_graph": DeferredToolEntry(summary="Navigate exact symbols.")
    }
    state.metadata["activated_deferred_tools"] = set()

    content = await activate_skill_with_runtime(state, record)

    assert "Trace exact evidence" in content
    assert state.metadata["activated_deferred_tools"] == {"code_graph"}
    assert state.metadata["skill_runtime_contracts"]["investigate"] == {
        "required_tools": ("code_graph",),
        "activated_tools": ("code_graph",),
    }


@pytest.mark.asyncio
async def test_activation_fails_without_partially_applying_missing_dependency(
    tmp_path,
):
    record = _record(tmp_path, dependency="missing_tool")
    state = AgentState(messages=[], tool_names=["skill"])
    state.metadata["activated_deferred_tools"] = set()

    with pytest.raises(SkillDependencyError, match="missing_tool"):
        await activate_skill_with_runtime(state, record)

    assert state.metadata["activated_deferred_tools"] == set()
    assert "skill_runtime_contracts" not in state.metadata


@pytest.mark.asyncio
async def test_runtime_hook_rehydrates_contract_from_durable_activation(
    monkeypatch, tmp_path
):
    record = _record(tmp_path)
    state = AgentState(
        messages=[AssistantMessage(content="seed")],
        tool_names=["skill", "code_graph"],
    )
    content = await activate_skill_with_runtime(state, record)
    state.metadata.clear()
    inject_skill_activation(
        state,
        skill_name=record.name,
        content=content,
        source="test",
    )
    state.metadata.clear()
    state.metadata["deferred_tool_catalog"] = {
        "code_graph": DeferredToolEntry(summary="Navigate exact symbols.")
    }
    state.metadata["activated_deferred_tools"] = set()
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {record.name: record},
    )

    await SkillRuntimeContractHook(mode="coding").before_agent(
        RunContext(session_id="s", run_id="r", agent_name="agent"),
        state,
    )

    assert state.metadata["activated_deferred_tools"] == {"code_graph"}
    assert state.metadata["loaded_skills"][record.name] == content


@pytest.mark.asyncio
async def test_investigation_promotes_discovery_to_graph_before_source_fallback() -> None:
    hook = SkillRuntimeContractHook(mode="coding")
    state = _investigation_state()
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")
    executions: list[str] = []

    async def handler(_ctx, _state, tool_call):
        executions.append(tool_call.function.name)
        if tool_call.function.name == "code_search":
            return "Indexed code search\nmatches: 3\n## app/service.py:1-5"
        if tool_call.function.name == "code_graph":
            return "Native code graph\nmatches: 1\nrelationships: 1"
        return "source"

    await hook.wrap_tool_call(ctx, state, _call("search", "code_search"), handler)
    blocked = await hook.wrap_tool_call(
        ctx,
        state,
        _call("read-before-graph", "read", '{"path":"app/service.py"}'),
        handler,
    )
    await hook.wrap_tool_call(
        ctx,
        state,
        _call("graph", "code_graph", '{"symbol":"Service"}'),
        handler,
    )
    source = await hook.wrap_tool_call(
        ctx,
        state,
        _call("read-after-graph", "read", '{"path":"app/service.py"}'),
        handler,
    )

    assert "Blocked by coding-investigation" in blocked
    assert source == "source"
    assert executions == ["code_search", "code_graph", "read"]


@pytest.mark.asyncio
async def test_investigation_reuses_identical_graph_observation() -> None:
    hook = SkillRuntimeContractHook(mode="coding")
    state = _investigation_state()
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")
    executions = 0

    async def handler(_ctx, _state, _tool_call):
        nonlocal executions
        executions += 1
        return "Native code graph\nmatches: 1\nrelationships: 2"

    first = _call(
        "graph-1",
        "code_graph",
        '{"symbol":"Service","operation":"callers"}',
    )
    duplicate = _call(
        "graph-2",
        "code_graph",
        '{"operation":"callers","symbol":"Service"}',
    )
    first_result = await hook.wrap_tool_call(ctx, state, first, handler)
    assert first_result.startswith("Native code graph")
    reused = await hook.wrap_tool_call(ctx, state, duplicate, handler)

    assert executions == 1
    assert "Observation reused" in reused
    assert "original_call_id: graph-1" in reused


@pytest.mark.asyncio
async def test_investigation_blocks_mutation_and_requires_graph_before_completion() -> None:
    hook = SkillRuntimeContractHook(mode="coding")
    state = _investigation_state()
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")
    executed = False

    async def handler(_ctx, _state, _tool_call):
        nonlocal executed
        executed = True
        return "changed"

    blocked = await hook.wrap_tool_call(
        ctx,
        state,
        _call("edit", "edit", '{"path":"app.py"}'),
        handler,
    )
    feedback = await hook.before_completion(
        ctx, state, AssistantMessage(content="done")
    )

    assert executed is False
    assert "read-only investigation" in blocked
    assert feedback is not None
    assert "requires at least one exact-symbol code_graph" in feedback
