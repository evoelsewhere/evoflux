"""The per-run Skills contract: catalog prompt, file access, ``$name``, preload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.hooks.skills import (
    CATALOG_KEY,
    SkillsHook,
    SkillsPromptFinalizerHook,
)
from app.agent.model_context import PREFIX_SNAPSHOT_FROZEN_KEY
from app.agent.sandbox import SandboxConfig, get_sandbox, set_sandbox
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from app.agent.skills.activation import activated_skills
from app.agent.skills.invocation import skill_mentions
from app.agent.skills.models import Skill
from app.agent.skills.registry import SkillCatalog, invalidate_skill_cache
from app.agent.state import AgentState, ModelRequest, RunContext
from app.agent.tools.builtin.filesystem.read import _read_file

from tests.agent.skills.test_registry import write_skill


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    user_skills = tmp_path / "user-skills"
    monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", str(user_skills))
    monkeypatch.setattr("app.plugin_platform.skills.plugin_skill_roots", lambda: [])
    project_skills = root / ".agents" / "skills"
    write_skill(project_skills, "alpha", description="Alpha work. Use for alpha.")
    write_skill(project_skills, "manual", extra="disable-model-invocation: true\n")
    write_skill(project_skills, "model-only", extra="user-invocable: false\n")
    write_skill(user_skills, "outside", body="Outside instructions.")
    token = set_sandbox(SandboxConfig(workspace=str(root)))
    invalidate_skill_cache()
    yield root
    invalidate_skill_cache()
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state(text: str = "hello") -> AgentState:
    return AgentState(messages=[HumanMessage(content=text)], system_prompt="Base.")


async def _prompt(hook: SkillsHook, state: AgentState) -> str:
    request = ModelRequest(messages=(), system_prompt="Base.")
    updated = await hook.before_model(_ctx(), state, request)
    return updated.system_prompt if updated is not None else request.system_prompt


def _read_calls(state: AgentState) -> list[str]:
    return [
        json.loads(call.function.arguments)["path"]
        for message in state.messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls or []
        if call.function.name == "read"
    ]


def test_skill_mentions_rule():
    text = (
        "> $quoted is context\n"
        "Use $alpha and $beta-two, then $alpha again.\n"
        "```\n$in-fence\n```\n"
        "Price is US$5 and a$b is not a mention; ($gamma)."
    )

    assert skill_mentions(text) == ["alpha", "beta-two", "gamma"]
    assert skill_mentions("$Upper $under_score") == []


@pytest.mark.asyncio
async def test_catalog_lists_model_visible_skills_with_locations(workspace):
    hook = SkillsHook()
    state = _state()
    await hook.before_agent(_ctx(), state)

    prompt = await _prompt(hook, state)

    assert prompt.startswith("Base.\n\n## Skills")
    assert "use the `read` tool to load the\nSKILL.md" in prompt
    alpha = (workspace / ".agents" / "skills" / "alpha" / "SKILL.md").resolve()
    assert (
        "    <name>alpha</name>\n"
        "    <description>Alpha work. Use for alpha.</description>\n"
        f"    <location>{alpha.as_posix()}</location>"
    ) in prompt
    assert "<name>model-only</name>" in prompt
    assert "<name>outside</name>" in prompt
    assert "<name>manual</name>" not in prompt
    assert "User skills directory:" in prompt
    assert isinstance(state.metadata[CATALOG_KEY], SkillCatalog)


@pytest.mark.asyncio
async def test_catalog_is_byte_stable_between_runs(workspace):
    first, second = _state("one"), _state("two")
    await SkillsHook().before_agent(_ctx(), first)
    await SkillsHook().before_agent(_ctx(), second)

    assert await _prompt(SkillsHook(), first) == await _prompt(SkillsHook(), second)


@pytest.mark.asyncio
async def test_skill_directories_outside_the_workspace_become_readable(
    workspace, tmp_path
):
    outside = tmp_path / "user-skills" / "outside" / "SKILL.md"
    with pytest.raises(PermissionError):
        await _read_file(path=str(outside))

    await SkillsHook().before_agent(_ctx(), _state())

    assert outside.parent.resolve() in get_sandbox().read_only_paths
    content = await _read_file(path=outside.as_posix())
    assert "Outside instructions." in content
    with pytest.raises(PermissionError):
        get_sandbox().validate_path(str(outside.parent / "new.md"), is_write=True)


@pytest.mark.asyncio
async def test_dollar_mentions_insert_real_read_calls_once(workspace):
    state = _state("Please use $manual and $alpha here. Also $model-only and $missing.")
    await SkillsHook().before_agent(_ctx(), state)

    paths = _read_calls(state)
    assert [Path(path).parent.name for path in paths] == ["manual", "alpha"]
    assert isinstance(state.messages[0], HumanMessage)
    assert isinstance(state.messages[1], AssistantMessage)
    result = state.messages[2]
    assert isinstance(result, ToolMessage) and result.name == "read"
    assert result.content.startswith("00001| ---")
    assert [item.metadata["skill"] for item in state.pending_tool_lifecycles] == [
        "manual",
        "alpha",
    ]
    catalog = state.metadata[CATALOG_KEY]
    assert set(activated_skills(state.messages, catalog)) == {"manual", "alpha"}

    await SkillsHook().before_agent(_ctx(), state)
    assert len(_read_calls(state)) == 2


@pytest.mark.asyncio
async def test_disabled_skill_is_hidden_and_not_invocable(workspace):
    from app.core.skill_settings import set_skill_enabled

    set_skill_enabled("alpha", False)
    try:
        hook = SkillsHook()
        state = _state("$alpha please")
        await hook.before_agent(_ctx(), state)

        assert _read_calls(state) == []
        assert "<name>alpha</name>" not in await _prompt(hook, state)
    finally:
        set_skill_enabled("alpha", True)


@pytest.mark.asyncio
async def test_preloaded_skills_are_inlined_and_left_out_of_the_catalog(workspace):
    hook = SkillsHook(preloaded=["alpha", "does-not-exist"])
    state = _state()
    await hook.before_agent(_ctx(), state)

    prompt = await _prompt(hook, state)

    assert '<skill_content name="alpha" location="' in prompt
    assert "Follow these steps." in prompt
    assert "<name>alpha</name>" not in prompt
    assert "<name>outside</name>" in prompt


@pytest.mark.asyncio
async def test_frozen_prefix_and_finalizer_leave_prompt_to_the_right_owner(workspace):
    hook = SkillsHook()
    finalizer = SkillsPromptFinalizerHook()
    state = _state()
    await finalizer.before_agent(_ctx(), state)
    await hook.before_agent(_ctx(), state)

    assert await _prompt(hook, state) == "Base."

    seen: list[str] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        seen.append(request.system_prompt)
        return AssistantMessage(content="ok")

    await finalizer.wrap_model_call(
        _ctx(), state, ModelRequest(messages=(), system_prompt="Base."), handler
    )
    assert "<available_skills>" in seen[-1]

    state.metadata[PREFIX_SNAPSHOT_FROZEN_KEY] = True
    await finalizer.wrap_model_call(
        _ctx(), state, ModelRequest(messages=(), system_prompt="Frozen."), handler
    )
    assert seen[-1] == "Frozen."


def _plugin_catalog(tmp_path: Path) -> tuple[SkillCatalog, Skill]:
    directory = write_skill(tmp_path / "plugin" / "skills", "plug")
    skill = Skill(
        name="plug",
        description="d",
        location=(directory / "SKILL.md").absolute(),
        root=directory.parent.absolute(),
        source="plugin",
        plugin_id="install-1",
    )
    return SkillCatalog({"plug": skill}), skill


def _read(call_id: str, path: str, **extra: object) -> ToolCall:
    return ToolCall(
        id=call_id,
        function=FunctionCall(
            name="read", arguments=json.dumps({"path": path, **extra})
        ),
    )


@pytest.mark.asyncio
async def test_reading_a_plugin_skill_grants_its_mcp_tools(tmp_path):
    catalog, skill = _plugin_catalog(tmp_path)
    granted: list[str] = []
    state = _state()
    state.metadata[CATALOG_KEY] = catalog

    def grant(installation_id: str) -> tuple[str, ...]:
        granted.append(installation_id)
        return ("mcp_plugin_tool",)

    state.metadata["_grant_plugin_mcp_tools"] = grant

    async def handler(ctx, state, call):
        return "00001| ---"

    hook = SkillsHook()
    await hook.wrap_tool_call(
        _ctx(), state, _read("c1", str(skill.location), offset=5, limit=3), handler
    )
    assert granted == []
    await hook.wrap_tool_call(_ctx(), state, _read("c2", str(skill.location)), handler)
    assert granted == ["install-1"]
    assert state.metadata["activated_deferred_tools"] == {"mcp_plugin_tool"}


def test_activated_skills_requires_a_complete_successful_read(tmp_path):
    catalog, skill = _plugin_catalog(tmp_path)
    path = str(skill.location)
    messages = [
        AssistantMessage(content=None, tool_calls=[_read("a", path, limit=10)]),
        ToolMessage(tool_call_id="a", name="read", content="00001| ---"),
        AssistantMessage(content=None, tool_calls=[_read("b", path)]),
        ToolMessage(tool_call_id="b", name="read", content="Error: denied"),
    ]
    assert activated_skills(messages, catalog) == {}

    messages += [
        AssistantMessage(content=None, tool_calls=[_read("c", path)]),
        ToolMessage(tool_call_id="c", name="read", content="00001| ---"),
    ]
    assert list(activated_skills(messages, catalog)) == ["plug"]
