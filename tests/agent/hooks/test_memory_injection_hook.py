"""Tests for WikiInjectionHook — canonical USER.md injection."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.wiki_injection import WikiInjectionHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.state import AgentState, ModelRequest, RunContext


@pytest.fixture(autouse=True)
def _wiki_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "wiki"
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(target))
    target.mkdir(parents=True, exist_ok=True)
    yield target


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state() -> AgentState:
    return AgentState(
        messages=[HumanMessage(content="hi")],
        system_prompt="Base prompt.",
    )


def _request(prompt: str = "Base prompt.", last_user: str = "hi") -> ModelRequest:
    return ModelRequest(
        messages=(HumanMessage(content=last_user),),
        system_prompt=prompt,
    )


async def _invoke(hook: WikiInjectionHook, req: ModelRequest) -> str:
    received: list[str] = []

    async def handler(r: ModelRequest) -> AssistantMessage:
        received.append(r.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), req, handler)
    return received[0]


# ── USER.md injection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_user_md_passes_through_unchanged(_wiki_dir: Path):
    """When USER.md doesn't exist, the prompt is passed through unchanged."""
    hook = WikiInjectionHook()
    req = _request("Base prompt.")
    received: list[str] = []

    async def handler(r: ModelRequest) -> AssistantMessage:
        received.append(r.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), req, handler)
    assert received[0] == "Base prompt."


@pytest.mark.asyncio
async def test_user_md_injected_in_full(_wiki_dir: Path):
    """USER.md content should be injected into the system prompt."""
    (_wiki_dir / "USER.md").write_text(
        "# User\n\n## Identity\nHoang, Saigon.\n", encoding="utf-8"
    )
    hook = WikiInjectionHook()
    result = await _invoke(hook, _request("Base."))
    assert "Hoang, Saigon." in result
    assert "## About the user" in result


@pytest.mark.asyncio
async def test_existing_prompt_preserved(_wiki_dir: Path):
    """The original system prompt should be preserved before the injected block."""
    (_wiki_dir / "USER.md").write_text("# User\n", encoding="utf-8")
    hook = WikiInjectionHook()
    result = await _invoke(hook, _request("CUSTOM BASE"))
    assert result.startswith("CUSTOM BASE")
    assert "## About the user" in result


@pytest.mark.asyncio
async def test_empty_user_md_passes_through(_wiki_dir: Path):
    """An empty USER.md should not inject anything."""
    (_wiki_dir / "USER.md").write_text("", encoding="utf-8")
    hook = WikiInjectionHook()
    req = _request("Base.")
    received: list[str] = []

    async def handler(r: ModelRequest) -> AssistantMessage:
        received.append(r.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), req, handler)
    assert received[0] == "Base."


@pytest.mark.asyncio
async def test_nested_user_page_is_ignored(_wiki_dir: Path):
    """The removed parallel wiki/user.md location is not consulted."""
    (_wiki_dir / "wiki").mkdir()
    (_wiki_dir / "wiki" / "user.md").write_text("obsolete", encoding="utf-8")
    hook = WikiInjectionHook()

    result = await _invoke(hook, _request("Base."))

    assert result == "Base."


@pytest.mark.asyncio
async def test_user_md_injection_is_capped(_wiki_dir: Path):
    """Long USER.md files should be capped before prompt injection."""
    (_wiki_dir / "USER.md").write_text("x" * 5000, encoding="utf-8")
    hook = WikiInjectionHook()

    result = await _invoke(hook, _request("Base."))

    assert len(result) < 4100
    assert "[truncated]" in result
