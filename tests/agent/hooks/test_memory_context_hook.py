"""Tests for MemoryContextHook."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.memory_context import MemoryContextHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
)
from app.agent.state import AgentState, ModelRequest, RunContext
from app.services.memory import seed_memory


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "memory"
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(target))
    seed_memory()
    yield target


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state() -> AgentState:
    return AgentState(messages=[HumanMessage(content="hi")], system_prompt="Base.")


def _request(prompt: str = "Base.", user: str = "hi") -> ModelRequest:
    return ModelRequest(messages=(HumanMessage(content=user),), system_prompt=prompt)


def _memory_page(body: str, *, topics: list[str] | None = None) -> str:
    topics = topics or ["preferences", "response-style"]
    return (
        "---\n"
        "description: Test memory\n"
        "memory_kind: profile\n"
        "scope: user\n"
        f"topics: {topics}\n"
        "---\n\n"
        f"# Memory\n\n## Facts\n\n{body}"
    )


async def _invoke(hook: MemoryContextHook, req: ModelRequest) -> str:
    received: list[str] = []

    async def handler(r: ModelRequest) -> AssistantMessage:
        received.append(r.system_prompt)
        return AssistantMessage(content="ok")

    await hook.wrap_model_call(_ctx(), _state(), req, handler)
    return received[0]


@pytest.mark.asyncio
async def test_no_memory_match_passes_through_unchanged():
    result = await _invoke(MemoryContextHook(), _request(user="unrelated query"))

    assert result == "Base."


@pytest.mark.asyncio
async def test_unrelated_query_does_not_inject_incidental_user_memory(
    _memory_dir: Path,
):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page("- Hoang prefers direct fact-based answers. [session:test]"),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="Explain Kubernetes pod scheduling.")
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_domain_specific_preference_query_does_not_inject_generic_preference(
    _memory_dir: Path,
):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page("- Hoang prefers direct fact-based answers. [session:test]"),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="What is Hoang's preferred Kubernetes scheduler plugin?"),
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_relevant_memory_is_injected(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page("- Hoang prefers direct fact-based answers. [session:test]"),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    assert "## Relevant memory" in result
    assert "source=wiki:user" in result
    assert "direct fact-based" in result


@pytest.mark.asyncio
async def test_metadata_topics_allow_matching_domain_memory(_memory_dir: Path):
    (_memory_dir / "wiki" / "evoflux.md").write_text(
        _memory_page(
            "- EvoFlux Memory v2 should keep retrieval benchmarkable. [session:test]",
            topics=["evoflux", "memory", "retrieval"],
        ),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="How should EvoFlux memory retrieval work?"),
    )

    assert "## Relevant memory" in result
    assert "source=wiki:evoflux" in result


@pytest.mark.asyncio
async def test_product_topic_alone_does_not_inject_for_unanswered_detail(
    _memory_dir: Path,
):
    (_memory_dir / "wiki" / "project-evoflux.md").write_text(
        _memory_page(
            "- EvoFlux is Hoang's main project. [session:test]",
            topics=["evoflux", "project"],
        ),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="Which cloud region does Hoang prefer for EvoFlux deployments?"),
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_injection_keeps_supported_memory_goal(_memory_dir: Path):
    (_memory_dir / "wiki" / "session-local.md").write_text(
        _memory_page(
            "- Hoang wants EvoFlux memory to support implicit personalization. [session:test]",
            topics=["memory", "personalization"],
        ),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="What does Hoang want memory to do?"),
    )

    assert "## Relevant memory" in result
    assert "implicit personalization" in result


@pytest.mark.asyncio
async def test_injection_uses_active_fact_not_stale_candidate(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page(
            "- Hoang prefers direct fact-based answers. [session:new]\n\n"
            "## Conflicts / stale candidates\n\n"
            "- Hoang prefers terse answers. [session:old]"
        ),
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    assert "direct fact-based" in result
    assert "terse answers" not in result


@pytest.mark.asyncio
async def test_injection_requires_cited_fact_bullet(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page("Hoang prefers direct fact-based answers."), encoding="utf-8"
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_memory_search_failure_does_not_block_model_call(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.agent.hooks.memory_context.search_memory_facts", _raise)

    result = await _invoke(MemoryContextHook(), _request(user="remember me"))

    assert result == "Base."


@pytest.mark.asyncio
async def test_memory_context_skips_followup_tool_call_iterations(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        _memory_page("- Hoang prefers direct fact-based answers. [session:test]"),
        encoding="utf-8",
    )
    req = ModelRequest(
        messages=(
            HumanMessage(content="How should you answer Hoang?"),
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="memory_search", arguments="{}"),
                    )
                ],
            ),
        ),
        system_prompt="Base.",
    )

    result = await _invoke(MemoryContextHook(), req)

    assert result == "Base."
