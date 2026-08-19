from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.hooks.skill_resolution import SkillResolutionHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.skills.models import SkillRecord
from app.agent.skills.resolution import eligible_resolution_records, resolve_skill
from app.agent.state import AgentState


def _record(
    name: str,
    description: str,
    *,
    root: Path = Path("/tmp/skills"),
    modes: tuple[str, ...] = ("coding",),
    implicit: bool = True,
    valid: bool = True,
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


class _Provider:
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload
        self.calls: list[tuple[list, list | None]] = []

    async def chat(self, messages, tools=None, **_kwargs):
        self.calls.append((messages, tools))
        content = (
            self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        )
        return AssistantMessage(content=content)


def test_resolution_eligibility_is_policy_and_mode_bounded():
    records = [
        _record("coding-investigation", "Investigate code."),
        _record("manual-skill", "Manual only.", implicit=False),
        _record("work-writing", "Write reports.", modes=("work",)),
        _record("broken", "Invalid.", valid=False),
    ]

    eligible = eligible_resolution_records(records, mode="coding")

    assert [record.name for record in eligible] == ["coding-investigation"]


@pytest.mark.asyncio
async def test_resolver_selects_one_exact_eligible_skill():
    provider = _Provider(
        {
            "skill_name": "coding-investigation",
            "confidence": 0.94,
            "reason": "The request asks for enablement and data flow evidence.",
        }
    )
    records = [
        _record(
            "coding-investigation",
            "Investigate ownership, enablement, data flow, or unfamiliar behavior.",
        ),
        _record("coding-debugging", "Debug a reproducible failure."),
    ]

    decision = await resolve_skill(
        provider,
        request="Tìm logic bật WebBridge và luồng dữ liệu",
        mode="coding",
        records=records,
    )

    assert decision.status == "selected"
    assert decision.skill_name == "coding-investigation"
    assert provider.calls[0][1] is None
    outbound = json.loads(provider.calls[0][0][1].content)
    assert outbound["request"] == "Tìm logic bật WebBridge và luồng dữ liệu"
    assert {item["name"] for item in outbound["skills"]} == {
        "coding-investigation",
        "coding-debugging",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "status"),
    [
        (
            {"skill_name": "invented", "confidence": 0.99, "reason": "Ignore list."},
            "rejected",
        ),
        (
            {
                "skill_name": "coding-investigation",
                "confidence": 0.4,
                "reason": "Weak match.",
            },
            "low_confidence",
        ),
        ("not json", "invalid"),
    ],
)
async def test_resolver_rejects_untrusted_or_uncertain_output(payload, status):
    decision = await resolve_skill(
        _Provider(payload),
        request="Inspect this",
        mode="coding",
        records=[_record("coding-investigation", "Investigate code paths.")],
    )

    assert decision.skill_name is None
    assert decision.status == status


@pytest.mark.asyncio
async def test_resolution_hook_activates_through_canonical_pair(monkeypatch, tmp_path):
    skill_dir = tmp_path / "coding-investigation"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: coding-investigation\n"
        "description: Investigate enablement and data flow.\n---\n"
        "Trace evidence before explaining behavior."
    )
    record = _record(
        "coding-investigation",
        "Investigate enablement and data flow.",
        root=tmp_path,
    )
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {record.name: record},
    )
    provider = _Provider(
        {
            "skill_name": record.name,
            "confidence": 0.97,
            "reason": "Enablement investigation.",
        }
    )
    state = AgentState(messages=[HumanMessage(content="Tìm logic bật WebBridge")])
    state.metadata["_runtime_provider"] = provider
    hook = SkillResolutionHook(mode="coding")

    await hook.before_agent(SimpleNamespace(agent_name="agent"), state)

    assert len(state.messages) == 3
    assert state.messages[1].tool_calls[0].function.name == "skill"
    assert json.loads(state.messages[1].tool_calls[0].function.arguments) == {
        "action": "load",
        "skill_name": "coding-investigation",
    }
    assert '<skill_content name="coding-investigation"' in state.messages[2].content
    assert state.metadata["skill_resolution"]["status"] == "selected"
    assert "coding-investigation" in state.metadata["loaded_skills"]
    assert len(state.pending_tool_lifecycles) == 1
    lifecycle = state.pending_tool_lifecycles[0]
    assert lifecycle.tool_call_id == state.messages[1].tool_calls[0].id
    assert lifecycle.name == "skill"
    assert json.loads(lifecycle.arguments) == {
        "action": "load",
        "skill_name": "coding-investigation",
    }
    assert lifecycle.result == state.messages[2].content
    assert lifecycle.metadata["activation_source"] == "resolved"


@pytest.mark.asyncio
async def test_resolution_hook_defers_to_explicit_selection():
    provider = _Provider(
        {"skill_name": None, "confidence": 1.0, "reason": "No implicit work."}
    )
    state = AgentState(messages=[HumanMessage(content="$work-writing draft this")])
    state.metadata["_runtime_provider"] = provider
    state.metadata["explicit_skill_selected"] = "work-writing"

    await SkillResolutionHook(mode="work").before_agent(
        SimpleNamespace(agent_name="agent"), state
    )

    assert provider.calls == []


@pytest.mark.asyncio
async def test_resolution_hook_does_not_duplicate_durable_activation(
    monkeypatch, tmp_path
):
    skill_dir = tmp_path / "coding-investigation"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: coding-investigation\n"
        "description: Investigate code.\n---\n"
        "Trace evidence before explaining behavior."
    )
    record = _record(
        "coding-investigation",
        "Investigate code.",
        root=tmp_path,
    )
    monkeypatch.setattr(
        "app.agent.tools.builtin.skill.discover_skill_records_runtime",
        lambda **_kwargs: {record.name: record},
    )
    provider = _Provider(
        {
            "skill_name": record.name,
            "confidence": 0.98,
            "reason": "Continue the investigation.",
        }
    )
    state = AgentState(messages=[HumanMessage(content="Initial investigation")])
    state.metadata["_runtime_provider"] = provider
    hook = SkillResolutionHook(mode="coding")
    await hook.before_agent(SimpleNamespace(agent_name="agent"), state)
    first_activation = list(state.messages)

    state.messages.append(HumanMessage(content="Continue tracing callers"))
    state.metadata.pop("loaded_skills", None)
    await hook.before_agent(SimpleNamespace(agent_name="agent"), state)

    assert state.messages[:-1] == first_activation
    assert len(state.messages) == 4
    assert set(state.metadata["loaded_skills"]) == {record.name}
