"""Honest Memory v2 retrieval regression tests.

These tests intentionally include a known hard negative. They should not be
made to pass by benchmark-specific scoring tricks; failures should identify
where retrieval/injection policy needs real improvement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.hooks.memory_context import MemoryContextHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage
from app.agent.state import AgentState, ModelRequest, RunContext
from app.models.chat import ChatSession, SessionMessage
from app.services.dream import process_memory_sources
from app.services.memory import (
    read_memory_file,
    search_memory_files,
    seed_memory,
    write_memory_file,
)

_memory_bench = pytest.importorskip(
    "manual.memory_bench",
    reason="manual/memory_bench.py (the Honest Memory v2 eval harness) isn't "
    "present in this checkout — these tests need it authored, not stubbed.",
)
BenchItem = _memory_bench.BenchItem
RetrievalHit = _memory_bench.RetrievalHit
_coerce_items = _memory_bench._coerce_items
_empty_stats = _memory_bench._empty_stats
_finalize_stats = _memory_bench._finalize_stats
_record_item = _memory_bench._record_item


@pytest.fixture
def memory_eval_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    monkeypatch.setattr("app.core.config.settings.EVOFLUX_WIKI_DIR", str(root))
    seed_memory()
    return root


async def _invoke_memory_context(query: str) -> str:
    received: list[str] = []

    async def handler(request: ModelRequest) -> AssistantMessage:
        received.append(request.system_prompt)
        return AssistantMessage(content="ok")

    hook = MemoryContextHook()
    request = ModelRequest(
        messages=(HumanMessage(content=query),), system_prompt="Base."
    )
    await hook.wrap_model_call(
        RunContext(session_id="eval", run_id="run", agent_name="agent"),
        AgentState(messages=list(request.messages), system_prompt="Base."),
        request,
        handler,
    )
    return received[0]


def _user_memory_page(body: str) -> str:
    return (
        "---\n"
        "description: User preferences\n"
        "memory_kind: profile\n"
        "scope: user\n"
        "topics: [preferences, response-style, personalization]\n"
        "---\n\n"
        f"# User\n\n## Facts\n\n{body}"
    )


@pytest.mark.asyncio
async def test_memory_v2_retrieval_fixture_parsing_and_known_false_positive(
    setup_db,
    memory_eval_dir: Path,
    tmp_path: Path,
) -> None:
    """Unit-level correctness check; full benchmarks live in manual/."""
    from app.core.db import async_session_factory

    write_memory_file(
        "wiki/user.md",
        _user_memory_page(
            "- Hoang prefers direct fact-based answers and wants implicit personalization. [session:test]\n"
        ),
    )
    session = ChatSession(agent_name="chat", title="memory eval")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content=(
                    "EvoFlux Memory v2 should help through implicit "
                    "personalization without repeated reminders."
                ),
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        result = await process_memory_sources(db, limit=10)
    assert result["processed"] == 1

    data_path = tmp_path / "memory_eval.jsonl"
    rows = [
        {
            "id": "pref-style",
            "type": "preference",
            "question": "How should the assistant respond to Hoang?",
            "answers": ["direct fact-based answers"],
        },
        {
            "id": "memory-goal",
            "type": "preference",
            "question": "What does Hoang want memory to do?",
            "answers": ["implicit personalization"],
        },
        {
            "id": "scheduler-negative",
            "type": "abstention",
            "question": "What is Hoang's preferred Kubernetes scheduler plugin?",
            "negative": True,
        },
    ]
    data_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )

    items = _coerce_items(data_path, limit=None)
    positive_hits = search_memory_files(
        "How should the assistant respond to Hoang?", scope="compiled"
    )
    negative_hits = search_memory_files(
        "What is Hoang's preferred Kubernetes scheduler plugin?",
        scope="compiled",
        abstain_weak=False,
    )

    assert [item.id for item in items] == [
        "pref-style",
        "memory-goal",
        "scheduler-negative",
    ]
    assert items[-1].is_negative is True
    assert any("direct fact-based answers" in hit.excerpt for hit in positive_hits)
    assert any(hit.source_ref == "wiki:user" for hit in negative_hits)


@pytest.mark.asyncio
async def test_memory_context_policy_abstains_on_known_negative(
    memory_eval_dir: Path,
) -> None:
    write_memory_file(
        "wiki/user.md",
        _user_memory_page(
            "- Hoang prefers direct fact-based answers and wants implicit personalization. [session:test]\n"
        ),
    )

    prompt = await _invoke_memory_context(
        "What is Hoang's preferred Kubernetes scheduler plugin?"
    )

    assert prompt == "Base."


@pytest.mark.asyncio
async def test_memory_context_policy_injects_relevant_preference(
    memory_eval_dir: Path,
) -> None:
    write_memory_file(
        "wiki/user.md",
        _user_memory_page(
            "- Hoang prefers direct fact-based answers and wants implicit personalization. [session:test]\n"
        ),
    )

    prompt = await _invoke_memory_context("How should you answer Hoang?")

    assert "## Relevant memory" in prompt
    assert "direct fact-based answers" in prompt


def test_eval_fixture_reads_full_file_text_for_scoring(memory_eval_dir: Path) -> None:
    write_memory_file(
        "wiki/long.md",
        "# Long\n\n"
        + "filler " * 200
        + "The important answer is deeply buried after the excerpt window.",
    )

    result = search_memory_files("important answer", scope="compiled", limit=1)[0]
    assert "important answer" in read_memory_file(result.path or "").content


def test_eval_metrics_split_candidate_and_injection_false_positives() -> None:
    item = BenchItem(
        id="negative",
        query="What is Hoang's preferred Kubernetes scheduler plugin?",
        answers=[],
        question_type="abstention",
        is_negative=True,
    )
    stats = _empty_stats()

    passed = _record_item(
        stats,
        item=item,
        hits=[],
        candidate_hits=[
            RetrievalHit("wiki:user", 1.0, "Hoang prefers direct answers.")
        ],
        rr=0.0,
    )

    metrics = _finalize_stats(stats, injection_mode=True)
    assert passed is True
    assert metrics["candidate_false_positive_rate"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["injection_false_positive_rate"] == 0.0
