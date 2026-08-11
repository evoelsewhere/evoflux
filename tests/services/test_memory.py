from __future__ import annotations

from pathlib import Path

import pytest

from app.core.wiki_seed import seed_wiki
from app.models.chat import ChatSession, SessionMessage
from app.services.memory import (
    CURATED_MEMORY_DIRS,
    memory_root,
    memory_search,
    search_curated_memory,
    search_memory_files,
    search_memory_messages,
)
from app.services.wiki import write_file


@pytest.fixture
def memory_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    monkeypatch.setattr("app.core.config.settings.EVOFLUX_WIKI_DIR", str(root))
    seed_wiki()
    return root


def test_seed_wiki_creates_one_canonical_memory_layout(memory_dir: Path) -> None:
    assert memory_root() == memory_dir.resolve()
    assert (memory_dir / "USER.md").is_file()
    assert (memory_dir / "notes").is_dir()
    assert (memory_dir / "imports").is_dir()
    for directory in CURATED_MEMORY_DIRS:
        assert (memory_dir / directory).is_dir()
    assert not (memory_dir / "wiki").exists()
    assert not (memory_dir / "SCHEMA.md").exists()


def test_search_curated_memory_returns_ranked_topic(memory_dir: Path) -> None:
    write_file(
        "topics/response-style.md",
        "---\n"
        "description: Durable response style preferences\n"
        "tags: [preferences, communication]\n"
        "confidence: high\n"
        "sources: [session-test]\n"
        "---\n\n"
        "# Response style\n\nHoang prefers direct detailed fact-based dialogue.",
    )
    write_file(
        "sources/session-test.md",
        "---\ndescription: Kubernetes research\ntags: [kubernetes]\n---\n\n"
        "# Kubernetes\n\nA cluster scheduling discussion.",
    )

    results = search_curated_memory("Hoang direct dialogue", limit=3)

    assert results
    assert results[0].source_ref == "topic:response-style"
    assert results[0].path == "topics/response-style.md"
    assert results[0].diagnostics["memory_scope"] == "curated"
    assert results[0].diagnostics["sources"] == ["session-test"]


def test_search_curated_memory_supports_user_profile(memory_dir: Path) -> None:
    (memory_dir / "USER.md").write_text(
        "identity:\n  name: Hoang\npreferences:\n  answer_style: concise technical\n",
        encoding="utf-8",
    )

    results = search_curated_memory("Hoang concise technical", limit=3)

    assert [result.source_ref for result in results] == ["memory:user"]
    assert results[0].path == "USER.md"


def test_search_memory_files_uses_stable_namespaces(memory_dir: Path) -> None:
    pages = {
        "topics/retrieval.md": "topic marker retrieval",
        "entities/evoflux.md": "entity marker retrieval",
        "sources/session-a.md": "source marker retrieval",
        "comparisons/lexical-vs-vector.md": "comparison marker retrieval",
        "notes/2026-08-11.md": "note marker retrieval",
        "imports/article.md": "import marker retrieval",
    }
    for path, content in pages.items():
        write_file(path, content)

    results = search_memory_files("marker retrieval", limit=10, abstain_weak=False)
    refs = {result.source_ref for result in results}

    assert "topic:retrieval" in refs
    assert "entity:evoflux" in refs
    assert "source:session-a" in refs
    assert "comparison:lexical-vs-vector" in refs
    assert "note:2026-08-11.md" in refs
    assert "import:article" in refs


def test_curated_scope_excludes_notes_and_imports(memory_dir: Path) -> None:
    write_file("notes/2026-08-11.md", "implicit personalization target")
    write_file("imports/article.md", "implicit personalization target")
    write_file("topics/profile.md", "direct answer preference")

    results = search_memory_files("implicit personalization", scope="curated")

    assert results == []


def test_search_abstains_on_unanswered_detail(memory_dir: Path) -> None:
    (memory_dir / "USER.md").write_text(
        "identity:\n  name: Hoang\npreferences:\n  answer_style: direct fact based\n",
        encoding="utf-8",
    )

    strict = search_curated_memory(
        "What is Hoang's preferred Kubernetes scheduler plugin?"
    )
    candidates = search_curated_memory(
        "What is Hoang's preferred Kubernetes scheduler plugin?",
        abstain_weak=False,
    )

    assert strict == []
    assert candidates[0].source_ref == "memory:user"
    assert candidates[0].diagnostics["query_coverage"] < 0.5


def test_search_supports_vietnamese_queries(memory_dir: Path) -> None:
    write_file(
        "topics/response-style.md",
        "---\ndescription: Cách trả lời người dùng\ntags: [giao-tiếp]\n---\n\n"
        "Người dùng muốn câu trả lời ngắn gọn và có dẫn chứng.",
    )

    results = search_curated_memory("Người dùng muốn trả lời thế nào?", limit=3)

    assert [result.source_ref for result in results] == ["topic:response-style"]


def test_search_normalizes_non_positive_limits(memory_dir: Path) -> None:
    write_file("topics/profile.md", "Hoang prefers direct dialogue.")

    assert len(search_curated_memory("Hoang", limit=0)) == 1
    assert len(search_curated_memory("Hoang", limit=-1)) == 1


@pytest.mark.asyncio
async def test_search_memory_messages_returns_visible_results(setup_db) -> None:
    from app.core.db import async_session_factory

    session = ChatSession(agent_name="chat", title="Preference chat")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        visible = SessionMessage(
            session_id=session.id,
            role="user",
            content="Hoang prefers benchmarkable memory retrieval.",
        )
        hidden = SessionMessage(
            session_id=session.id,
            role="user",
            content="Hoang secret excluded memory retrieval.",
            exclude_from_context=True,
        )
        db.add(visible)
        db.add(hidden)
        await db.commit()

    async with async_session_factory() as db:
        results = await search_memory_messages(db, "benchmarkable memory", limit=5)

    assert [result.source_ref for result in results] == [f"message:{visible.id}"]
    assert results[0].title == "Preference chat (user)"


@pytest.mark.asyncio
async def test_memory_search_merges_curated_raw_and_messages(
    setup_db, memory_dir: Path
) -> None:
    from app.core.db import async_session_factory

    write_file("topics/memory.md", "Benchmarkable curated retrieval.")
    write_file("notes/2026-08-11.md", "Benchmarkable raw note retrieval.")
    session = ChatSession(agent_name="chat", title="Raw memory chat")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Benchmarkable visible message retrieval.",
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        results = await memory_search(
            db=db,
            query="benchmarkable retrieval",
            limit=10,
        )

    refs = {result.source_ref for result in results}
    assert "topic:memory" in refs
    assert "note:2026-08-11.md" in refs
    assert any(ref.startswith("message:") for ref in refs)
