"""Tests for automatic curated Memory recall."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.hooks.memory_context import MemoryContextHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from app.agent.state import AgentState, ModelRequest, RunContext
from app.core.wiki_seed import seed_wiki
from app.services.wiki import write_file


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "memory"
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(target))
    seed_wiki()
    yield target


def _ctx() -> RunContext:
    return RunContext(session_id="s1", run_id="r1", agent_name="bot")


def _state() -> AgentState:
    return AgentState(messages=[HumanMessage(content="hi")], system_prompt="Base.")


def _request(prompt: str = "Base.", user: str = "hi") -> ModelRequest:
    return ModelRequest(messages=(HumanMessage(content=user),), system_prompt=prompt)


def _memory_page(body: str, *, tags: list[str] | None = None) -> str:
    tags = tags or ["preferences", "response-style"]
    return (
        "---\n"
        "description: Durable test memory\n"
        f"tags: {tags}\n"
        "confidence: high\n"
        "sources: [session-test]\n"
        "---\n\n"
        f"# Memory\n\n{body}"
    )


async def _invoke(hook: MemoryContextHook, req: ModelRequest) -> str:
    received: list[str] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        received.append(request.system_prompt)
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
    (_memory_dir / "USER.md").write_text(
        "identity:\n  name: Hoang\npreferences:\n  response: direct fact based\n",
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="Explain Kubernetes pod scheduling.")
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_domain_specific_question_does_not_inject_generic_preference(
    _memory_dir: Path,
):
    (_memory_dir / "USER.md").write_text(
        "identity:\n  name: Hoang\npreferences:\n  response: direct fact based\n",
        encoding="utf-8",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="What is Hoang's preferred Kubernetes scheduler plugin?"),
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_relevant_topic_is_injected():
    write_file(
        "topics/response-style.md",
        _memory_page("Hoang prefers direct fact-based answers."),
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    assert "## Relevant memory" in result
    assert '"source":"topic:response-style"' in result
    assert '"provenance":["session-test"]' in result
    assert "direct fact-based" in result


@pytest.mark.asyncio
async def test_metadata_tags_boost_domain_memory():
    write_file(
        "topics/evoflux-memory.md",
        _memory_page(
            "EvoFlux Memory should keep retrieval benchmarkable.",
            tags=["evoflux", "memory", "retrieval"],
        ),
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="How should EvoFlux memory retrieval work?"),
    )

    assert '"source":"topic:evoflux-memory"' in result
    assert "benchmarkable" in result


@pytest.mark.asyncio
async def test_raw_notes_are_not_automatically_injected():
    write_file(
        "notes/2026-08-11.md",
        "Hoang wants EvoFlux memory to reveal temporary scratchpad content.",
    )

    result = await _invoke(
        MemoryContextHook(),
        _request(user="What temporary scratchpad content should memory reveal?"),
    )

    assert result == "Base."


@pytest.mark.asyncio
async def test_memory_search_failure_does_not_block_model_call(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.agent.hooks.memory_context.search_curated_memory",
        _raise,
    )

    result = await _invoke(MemoryContextHook(), _request(user="remember me"))

    assert result == "Base."


@pytest.mark.asyncio
async def test_memory_block_is_identical_across_a_turns_tool_calls():
    """The block must not appear and vanish between calls in one turn.

    It sits in the system prompt, so dropping it once a tool has run rewrites
    the front of the prompt and costs the cached history behind it.
    """
    write_file(
        "topics/response-style.md",
        _memory_page("Hoang prefers direct fact-based answers."),
    )
    first_call = ModelRequest(
        messages=(HumanMessage(content="How should you answer Hoang?"),),
        system_prompt="Base.",
    )
    after_tool = ModelRequest(
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
            ToolMessage(tool_call_id="call_1", content="{}"),
        ),
        system_prompt="Base.",
    )

    hook = MemoryContextHook()
    assert await _invoke(hook, after_tool) == await _invoke(hook, first_call)
