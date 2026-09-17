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


async def _invoke(hook: MemoryContextHook, req: ModelRequest) -> ModelRequest:
    received: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        received.append(request)
        return AssistantMessage(content="ok")

    state = AgentState(messages=list(req.messages), system_prompt=req.system_prompt)
    await hook.wrap_model_call(_ctx(), state, req, handler)
    return received[0]


@pytest.mark.asyncio
async def test_no_memory_match_passes_through_unchanged():
    result = await _invoke(MemoryContextHook(), _request(user="unrelated query"))

    assert result.system_prompt == "Base."


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

    assert result.system_prompt == "Base."


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

    assert result.system_prompt == "Base."


@pytest.mark.asyncio
async def test_relevant_topic_is_injected():
    write_file(
        "topics/response-style.md",
        _memory_page("Hoang prefers direct fact-based answers."),
    )

    result = await _invoke(
        MemoryContextHook(), _request(user="How should you answer Hoang?")
    )

    context = result.messages[-1].content or ""
    assert result.system_prompt == "Base."
    assert "## Relevant memory" in context
    assert '"source":"topic:response-style"' in context
    assert '"provenance":["session-test"]' in context
    assert "direct fact-based" in context


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

    context = result.messages[-1].content or ""
    assert '"source":"topic:evoflux-memory"' in context
    assert "benchmarkable" in context


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

    assert result.system_prompt == "Base."


@pytest.mark.asyncio
async def test_memory_search_failure_does_not_block_model_call(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.agent.hooks.memory_context.search_curated_memory",
        _raise,
    )

    result = await _invoke(MemoryContextHook(), _request(user="remember me"))

    assert result.system_prompt == "Base."


@pytest.mark.asyncio
async def test_memory_context_is_append_only_and_deduplicated_across_tool_calls():
    """The same durable context row is replayed across model calls."""
    write_file(
        "topics/response-style.md",
        _memory_page("Hoang prefers direct fact-based answers."),
    )
    user_message = HumanMessage(content="How should you answer Hoang?")
    state = AgentState(messages=[user_message], system_prompt="Base.")
    first_call = ModelRequest(messages=(user_message,), system_prompt="Base.")
    received: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        received.append(request)
        return AssistantMessage(content="ok")

    hook = MemoryContextHook()
    first = await hook.wrap_model_call(_ctx(), state, first_call, handler)

    state.messages.extend(
        [
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
        ]
    )
    second_call = ModelRequest(
        messages=tuple(state.messages),
        system_prompt="Base.",
    )
    second = await hook.wrap_model_call(_ctx(), state, second_call, handler)

    assert first.content == second.content == "ok"
    assert first_call.system_prompt == second_call.system_prompt == "Base."
    assert len(state.messages) == 4
    assert len(received) == 2
    assert len(received[0].messages) == 2
    assert len(received[1].messages) == 4
    assert received[0].messages[1].content == received[1].messages[1].content
    assert (
        sum(
            1
            for message in state.messages
            if (message.extra or {}).get("evoflux_model_context") == "memory_recall"
        )
        == 1
    )
