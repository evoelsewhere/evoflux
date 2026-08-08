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


def _record(tmp_path: Path, *, dependency: str = "code_context") -> SkillRecord:
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
    state = AgentState(messages=[], tool_names=["skill", "code_context"])
    state.metadata["deferred_tool_catalog"] = {
        "code_context": DeferredToolEntry(summary="Navigate exact symbols.")
    }
    state.metadata["activated_deferred_tools"] = set()

    content = await activate_skill_with_runtime(state, record)

    assert "Trace exact evidence" in content
    assert state.metadata["activated_deferred_tools"] == {"code_context"}
    assert state.metadata["skill_runtime_contracts"]["investigate"] == {
        "required_tools": ("code_context",),
        "activated_tools": ("code_context",),
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
        tool_names=["skill", "code_context"],
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
        "code_context": DeferredToolEntry(summary="Navigate exact symbols.")
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

    assert state.metadata["activated_deferred_tools"] == {"code_context"}
    assert state.metadata["loaded_skills"][record.name] == content


@pytest.mark.asyncio
async def test_runtime_contract_does_not_restrict_tool_calls_or_completion() -> None:
    hook = SkillRuntimeContractHook(mode="coding")
    state = AgentState(messages=[])
    ctx = RunContext(session_id="s", run_id="r", agent_name="agent")
    executions: list[str] = []

    async def handler(_ctx, _state, tool_call):
        executions.append(tool_call.function.name)
        return "executed"

    for index in range(12):
        result = await hook.wrap_tool_call(
            ctx,
            state,
            _call(str(index), "code_context", '{"symbol":"Service"}'),
            handler,
        )
        assert result == "executed"
    edit_result = await hook.wrap_tool_call(
        ctx, state, _call("edit", "edit", '{"path":"app.py"}'), handler
    )
    feedback = await hook.before_completion(
        ctx, state, AssistantMessage(content="done")
    )

    assert edit_result == "executed"
    assert executions == ["code_context"] * 12 + ["edit"]
    assert feedback is None
