from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.hooks.configured_skills import (
    MAX_CONFIGURED_SKILL_CHARS,
    ConfiguredSkillsHook,
)
from app.agent.hooks.skill_catalog import SkillCatalogFinalizerHook, SkillCatalogHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.skills.activation import MAX_ACTIVATED_SKILL_BYTES, activate_skill
from app.agent.skills.catalog import render_skill_catalog
from app.agent.skills.discovery import MAX_SKILL_FILE_BYTES
from app.agent.skills.models import SkillRecord
from app.agent.state import AgentState, ModelRequest


def _record(
    name: str,
    description: str,
    *,
    modes: tuple[str, ...] = ("work", "coding"),
    implicit: bool = True,
    valid: bool = True,
    root: Path = Path("/tmp/skills"),
) -> SkillRecord:
    return SkillRecord(
        name=name,
        description=description,
        skill_file=root / name / "SKILL.md",
        root=root,
        source="test",
        modes=modes,
        allow_implicit_invocation=implicit,
        valid=valid,
    )


def test_catalog_filters_mode_policy_and_invalid_records():
    rendered = render_skill_catalog(
        [
            _record(
                "work-writing", "Draft substantial work products.", modes=("work",)
            ),
            _record("coding-review", "Review coding changes.", modes=("coding",)),
            _record("manual", "Explicit specialist.", implicit=False),
            _record("broken", "Invalid.", valid=False),
        ],
        mode="work",
    )

    assert "work-writing" in rendered.text
    assert "coding-review" not in rendered.text
    assert "manual" not in rendered.text
    assert "broken" not in rendered.text
    assert "Draft substantial work products" in rendered.text


def test_catalog_ranks_matching_metadata_without_filtering_other_skills():
    rendered = render_skill_catalog(
        [
            _record("work-writing", "Draft substantial knowledge-work products."),
            _record("work-research", "Research and verify a sourced report."),
            _record("work-planning", "Create an execution plan."),
        ],
        mode="work",
        preferred=("work-writing",),
        query="Please research and verify a sourced report.",
    )

    assert rendered.included == ("work-research", "work-writing", "work-planning")
    assert rendered.query_ranked[0] == "work-research"
    assert set(rendered.included) == {
        "work-planning",
        "work-research",
        "work-writing",
    }
    assert "server-selected workflow" in rendered.text


def test_catalog_uses_preferred_skill_when_query_has_no_lexical_match():
    rendered = render_skill_catalog(
        [
            _record("coding-investigation", "Trace exact symbols and callers."),
            _record("coding-review", "Review software engineering changes."),
        ],
        mode="coding",
        preferred=("coding-review",),
        query="Tìm giúp mình logic bật WebBridge và luồng dữ liệu.",
    )

    assert rendered.query_ranked == ()
    assert rendered.included[0] == "coding-review"


def test_catalog_ranking_never_bypasses_mode_or_invocation_policy():
    rendered = render_skill_catalog(
        [
            _record("work-writing", "Draft work products.", modes=("work",)),
            _record(
                "coding-investigation",
                "Investigate enablement and data flow.",
                modes=("coding",),
                implicit=False,
            ),
        ],
        mode="work",
        query="Investigate enablement and data flow.",
    )

    assert rendered.included == ("work-writing",)
    assert rendered.query_ranked == ()


def test_catalog_preserves_identities_and_shortens_descriptions_under_budget():
    records = [
        _record(f"skill-{index}", f"description {index} " + "x" * 900)
        for index in range(20)
    ]

    rendered = render_skill_catalog(records, mode="work", context_window=20_000)

    assert len(rendered.text.encode("utf-8")) <= rendered.budget_chars
    assert rendered.descriptions_shortened is True
    assert len(rendered.included) == len(records)
    assert rendered.omitted == ()
    for name in rendered.included:
        assert name in rendered.text


def test_catalog_budget_is_enforced_on_utf8_bytes():
    records = [
        _record(f"skill-{index}", "Quy trình " + "🧪" * 800) for index in range(20)
    ]

    rendered = render_skill_catalog(records, mode="work", context_window=20_000)

    assert len(rendered.text.encode("utf-8")) <= rendered.budget_chars
    assert rendered.descriptions_shortened is True


@pytest.mark.asyncio
async def test_catalog_hook_exposes_metadata_but_never_skill_body(
    monkeypatch, tmp_path
):
    skill_dir = tmp_path / "research"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: research\ndescription: Research current facts.\n---\n"
        "SECRET FULL WORKFLOW BODY"
    )
    record = _record("research", "Research current facts.", root=tmp_path)
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {"research": record},
    )
    monkeypatch.setattr(
        "app.agent.hooks.skill_catalog.get_model_limits",
        lambda _model: SimpleNamespace(context_length=128_000),
    )
    hook = SkillCatalogHook(mode="work", model_id="test:model")
    state = AgentState(messages=[HumanMessage(content="Research current facts")])
    request = ModelRequest(messages=tuple(state.messages), system_prompt="Base")

    updated = await hook.before_model(
        SimpleNamespace(agent_name="agent"), state, request
    )

    assert updated is not None
    assert "research" in updated.system_prompt
    assert "Research current facts" in updated.system_prompt
    assert "SECRET FULL WORKFLOW BODY" not in updated.system_prompt
    assert str(skill_file) not in updated.system_prompt
    assert "(file:" not in updated.system_prompt
    assert "Skills are optional" not in updated.system_prompt
    assert "you must call `skill`" in updated.system_prompt
    assert state.metadata["skill_catalog"]["query_ranked"] == ["research"]
    assert state.messages == [state.messages[0]]


@pytest.mark.asyncio
async def test_team_catalog_finalizer_keeps_catalog_after_stable_prompt(
    monkeypatch, tmp_path
):
    record = _record("research", "Research current facts.", root=tmp_path)
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {"research": record},
    )
    monkeypatch.setattr(
        "app.agent.hooks.skill_catalog.get_model_limits",
        lambda _model: SimpleNamespace(context_length=128_000),
    )
    catalog = SkillCatalogHook(mode="work", model_id="test:model")
    finalizer = SkillCatalogFinalizerHook()
    ctx = SimpleNamespace(agent_name="agent")
    state = AgentState(messages=[HumanMessage(content="Research current facts")])
    request = ModelRequest(
        messages=tuple(state.messages),
        system_prompt="Base\n\nStatic team protocol",
    )

    await finalizer.before_agent(ctx, state)
    updated = await catalog.before_model(ctx, state, request)
    captured: list[ModelRequest] = []

    async def handler(model_request: ModelRequest) -> AssistantMessage:
        captured.append(model_request)
        return AssistantMessage(content="done")

    response = await finalizer.wrap_model_call(ctx, state, request, handler)

    assert updated is None
    assert response.content == "done"
    assert captured[0].system_prompt.startswith("Base\n\nStatic team protocol")
    assert captured[0].system_prompt.index("## Skills") > captured[
        0
    ].system_prompt.index("Static team protocol")


@pytest.mark.asyncio
async def test_catalog_hook_ranks_from_latest_user_turn(monkeypatch):
    records = {
        "work-writing": _record("work-writing", "Draft substantial knowledge work."),
        "work-research": _record(
            "work-research", "Research and verify a sourced report."
        ),
    }
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: records,
    )
    monkeypatch.setattr(
        "app.agent.hooks.skill_catalog.get_model_limits",
        lambda _model: SimpleNamespace(context_length=128_000),
    )
    hook = SkillCatalogHook(
        mode="work",
        model_id="test:model",
        preferred_skills=("work-writing",),
    )
    state = AgentState(
        messages=[
            HumanMessage(content="Earlier unrelated request"),
            HumanMessage(content="Research and verify this sourced report"),
        ]
    )
    request = ModelRequest(messages=tuple(state.messages), system_prompt="Base")

    updated = await hook.before_model(
        SimpleNamespace(agent_name="agent"), state, request
    )

    assert updated is not None
    assert state.metadata["skill_catalog"]["included"][:2] == [
        "work-research",
        "work-writing",
    ]
    assert state.metadata["skill_catalog"]["query_ranked"][0] == "work-research"


@pytest.mark.asyncio
async def test_integrated_code_navigation_is_visible_without_body_preload(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.agent.hooks.skill_catalog.get_model_limits",
        lambda _model: SimpleNamespace(context_length=128_000),
    )
    hook = SkillCatalogHook(mode="coding", model_id="test:model")
    state = AgentState(messages=[HumanMessage(content="Who calls calculate_total?")])
    request = ModelRequest(messages=tuple(state.messages), system_prompt="Base")

    updated = await hook.before_model(
        SimpleNamespace(agent_name="agent"), state, request
    )

    assert updated is not None
    assert "coding-investigation" in updated.system_prompt
    assert "Never pass request prose" not in updated.system_prompt
    assert "loaded_skills" not in state.metadata
    assert state.messages == [state.messages[0]]


@pytest.mark.asyncio
async def test_configured_skill_is_preloaded_as_durable_activation(
    monkeypatch, tmp_path
):
    skill_dir = tmp_path / "specialist"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: specialist\ndescription: Specialist workflow.\n---\n"
        "Follow the exact specialist contract."
    )
    record = _record("specialist", "Specialist workflow.", root=tmp_path)
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {"specialist": record},
    )
    state = AgentState(messages=[HumanMessage(content="Do the assigned work")])
    hook = ConfiguredSkillsHook(["specialist"], mode="work")

    await hook.before_agent(SimpleNamespace(agent_name="agent"), state)

    assert len(state.messages) == 3
    assert state.messages[1].tool_calls[0].function.name == "skill"
    assert "<skill_content" in (state.messages[2].content or "")
    assert "Follow the exact specialist contract" in (state.messages[2].content or "")
    assert "specialist" in state.metadata["loaded_skills"]


@pytest.mark.asyncio
async def test_configured_skill_larger_than_preload_budget_is_never_loaded(
    monkeypatch,
):
    oversized = _record("oversized", "Oversized workflow.")
    compact = _record("compact", "Compact workflow.")
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {"oversized": oversized, "compact": compact},
    )

    async def fake_activate(_state, record):
        if record.name == "oversized":
            return "x" * (MAX_CONFIGURED_SKILL_CHARS + 1)
        return '<skill_content name="compact">Compact.</skill_content>'

    monkeypatch.setattr(
        "app.agent.hooks.configured_skills.activate_skill_with_runtime",
        fake_activate,
    )
    state = AgentState(messages=[HumanMessage(content="Do the assigned work")])
    hook = ConfiguredSkillsHook(["oversized", "compact"], mode="work")

    await hook.before_agent(SimpleNamespace(agent_name="agent"), state)

    assert len(state.messages) == 3
    assert state.messages[1].tool_calls[0].function.arguments == (
        '{"action": "load", "skill_name": "compact"}'
    )
    assert set(state.metadata["loaded_skills"]) == {"compact"}


@pytest.mark.asyncio
async def test_activation_stays_bounded_after_post_discovery_file_growth(tmp_path):
    skill_dir = tmp_path / "mutable"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: mutable\ndescription: Mutable workflow.\n---\nBody.\n"
    )
    record = _record("mutable", "Mutable workflow.", root=tmp_path)
    skill_file.write_text("x" * (MAX_SKILL_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="runtime limit"):
        await activate_skill(record)


@pytest.mark.asyncio
async def test_activation_has_a_model_context_budget_below_discovery_limit(tmp_path):
    skill_dir = tmp_path / "verbose"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: verbose\ndescription: Verbose workflow.\n---\n"
        + ("🧪" * MAX_ACTIVATED_SKILL_BYTES)
    )
    record = _record("verbose", "Verbose workflow.", root=tmp_path)

    with pytest.raises(ValueError, match="model-context limit"):
        await activate_skill(record)
