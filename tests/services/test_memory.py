from __future__ import annotations

from pathlib import Path

import pytest

from app.models.chat import ChatSession, SessionMessage
from app.services.memory import (
    IMPORTS_DIR,
    SCHEMA_FILE,
    WIKI_DIR,
    extract_memory_facts,
    list_memory_tree,
    memory_root,
    memory_search,
    read_memory_file,
    search_memory_facts,
    search_memory_files,
    search_memory_messages,
    seed_memory,
    validate_memory_path,
    write_memory_file,
)
from app.services.wiki import WikiPathError


@pytest.fixture
def memory_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memory"
    monkeypatch.setattr("app.core.config.settings.EVOFLUX_WIKI_DIR", str(root))
    return root


def test_seed_memory_creates_v2_layout(memory_dir: Path) -> None:
    seed_memory()

    assert memory_root() == memory_dir.resolve()
    assert (memory_dir / SCHEMA_FILE).is_file()
    assert (memory_dir / "INDEX.md").is_file()
    assert (memory_dir / "LOG.md").is_file()
    assert (memory_dir / "notes").is_dir()
    assert (memory_dir / IMPORTS_DIR).is_dir()
    assert (memory_dir / WIKI_DIR).is_dir()

    tree = list_memory_tree()
    assert [item.path for item in tree.system] == ["SCHEMA.md", "INDEX.md", "LOG.md"]


def test_validate_memory_path_allows_only_v2_paths(memory_dir: Path) -> None:
    seed_memory()

    assert (
        validate_memory_path("wiki/user.md") == (memory_dir / "wiki/user.md").resolve()
    )
    assert (
        validate_memory_path("imports/article.md")
        == (memory_dir / "imports/article.md").resolve()
    )

    for bad_path in (
        "USER.md",
        "topics/foo.md",
        "wiki/nested/foo.md",
        "../x.md",
        "wiki/x.txt",
    ):
        with pytest.raises(WikiPathError):
            validate_memory_path(bad_path)


def test_search_memory_files_returns_cited_ranked_results(memory_dir: Path) -> None:
    seed_memory()
    (memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct detailed fact based dialogue.",
        encoding="utf-8",
    )
    (memory_dir / "imports" / "karpathy.md").write_text(
        "# LLM Wiki\n\nA markdown wiki compiled from raw sources.",
        encoding="utf-8",
    )

    results = search_memory_files("Hoang direct dialogue", limit=3)

    assert results
    assert results[0].source_ref == "wiki:user"
    assert results[0].path == "wiki/user.md"
    assert "Hoang prefers" in results[0].excerpt


def test_extract_memory_facts_reads_active_and_stale_cited_bullets() -> None:
    text = (
        "---\nmemory_kind: profile\nscope: user\ntopics: [preferences]\n---\n\n"
        "# User\n\n"
        "## Facts\n\n"
        "- Hoang prefers direct answers. [session:abc] confidence=medium fact_id=abc123\n\n"
        "## Conflicts / stale candidates\n\n"
        "- Hoang used to prefer terse answers. [session:old]\n\n"
        "## Ignored source notes\n\n"
        "- Skipped possible noise. [session:skip]\n"
    )

    facts = extract_memory_facts("wiki/user.md", text)

    assert [(fact.section, fact.citations) for fact in facts] == [
        ("active", ("session:abc",)),
        ("stale", ("session:old",)),
    ]
    assert facts[0].text == "Hoang prefers direct answers. [session:abc]"


def test_search_memory_facts_returns_active_cited_fact_not_whole_page(
    memory_dir: Path,
) -> None:
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        "---\n"
        "description: User preferences\n"
        "memory_kind: profile\n"
        "scope: user\n"
        "topics: [preferences, response-style]\n"
        "---\n\n"
        "# User\n\n"
        "## Facts\n\n"
        "- Hoang prefers direct fact-based answers. [session:new]\n\n"
        "## Conflicts / stale candidates\n\n"
        "- Hoang prefers verbose answers. [session:old]\n",
    )

    results = search_memory_facts("How should you answer Hoang?", limit=3)

    assert [result.source_ref for result in results] == ["wiki:user#fact-1"]
    assert (
        results[0].excerpt == "Hoang prefers direct fact-based answers. [session:new]"
    )
    assert results[0].diagnostics["fact_section"] == "active"


def test_search_memory_facts_can_expose_stale_candidates_for_debug(
    memory_dir: Path,
) -> None:
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        "# User\n\n"
        "## Facts\n\n"
        "- Hoang prefers direct answers. [session:new]\n\n"
        "## Conflicts / stale candidates\n\n"
        "- Hoang prefers terse answers. [session:old]\n",
    )

    strict = search_memory_facts("terse answers", limit=3)
    debug = search_memory_facts("terse answers", limit=3, include_stale=True)

    assert all(result.diagnostics["fact_section"] == "active" for result in strict)
    assert any(result.diagnostics["fact_section"] == "stale" for result in debug)


def test_search_memory_facts_supports_unicode_evidence(memory_dir: Path) -> None:
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        "# User\n\n"
        "## Facts\n\n"
        "- Người dùng muốn câu trả lời ngắn gọn. [session:test]\n",
    )

    results = search_memory_facts("Người dùng muốn trả lời thế nào?", limit=3)

    assert [result.source_ref for result in results] == ["wiki:user#fact-1"]


def test_search_memory_facts_returns_negated_active_fact_when_supported(
    memory_dir: Path,
) -> None:
    seed_memory()
    write_memory_file(
        "wiki/decisions.md",
        "# Decisions\n\n"
        "## Facts\n\n"
        "- Memory v2 has no mandatory root USER.md taxonomy. [session:new]\n\n"
        "## Conflicts / stale candidates\n\n"
        "- USER.md was mandatory. [session:old]\n",
    )

    results = search_memory_facts(
        "What mandatory root USER.md taxonomy does Memory v2 require?", limit=3
    )

    assert [result.source_ref for result in results] == ["wiki:decisions#fact-1"]
    assert "no mandatory root USER.md taxonomy" in results[0].excerpt


def test_search_memory_files_normalizes_non_positive_limits(memory_dir: Path) -> None:
    seed_memory()
    (memory_dir / "wiki" / "user.md").write_text("Hoang prefers direct dialogue.")

    assert len(search_memory_files("Hoang", limit=0)) == 1
    assert len(search_memory_files("Hoang", limit=-1)) == 1


def test_search_memory_files_compiled_scope_excludes_raw_notes(
    memory_dir: Path,
) -> None:
    seed_memory()
    (memory_dir / "notes" / "2026-05-31.md").write_text(
        "## 10:00 UTC\nHoang wants implicit personalization.", encoding="utf-8"
    )
    (memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct answers.", encoding="utf-8"
    )

    results = search_memory_files("implicit personalization", scope="compiled")

    assert results == []


def test_search_memory_files_abstains_on_weak_domain_preference(
    memory_dir: Path,
) -> None:
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        "---\n"
        "description: User preferences\n"
        "memory_kind: profile\n"
        "scope: user\n"
        "topics: [preferences, response-style]\n"
        "---\n\n"
        "# User\n\nHoang prefers direct fact-based answers.",
    )

    strict = search_memory_files(
        "What is Hoang's preferred Kubernetes scheduler plugin?",
        scope="compiled",
    )
    candidates = search_memory_files(
        "What is Hoang's preferred Kubernetes scheduler plugin?",
        scope="compiled",
        abstain_weak=False,
    )

    assert strict == []
    assert candidates[0].source_ref == "wiki:user"
    assert candidates[0].diagnostics["query_coverage"] < 0.5


def test_search_memory_files_uses_answerability_filter(
    memory_dir: Path,
) -> None:
    seed_memory()
    write_memory_file(
        "wiki/user.md",
        "---\n"
        "description: User preferences\n"
        "memory_kind: profile\n"
        "scope: user\n"
        "topics: [preferences, response-style]\n"
        "---\n\n"
        "# User\n\nHoang prefers direct fact-based answers.",
    )

    strict = search_memory_files(
        "Which LLM provider did Hoang choose for Dream synthesis?",
        scope="compiled",
    )
    candidates = search_memory_files(
        "Which LLM provider did Hoang choose for Dream synthesis?",
        scope="compiled",
        abstain_weak=False,
    )

    assert strict == []
    assert candidates[0].source_ref == "wiki:user"
    assert candidates[0].diagnostics["query_coverage"] < 0.5


def test_read_write_memory_file_round_trip(memory_dir: Path) -> None:
    seed_memory()

    written = write_memory_file(
        "wiki/user.md", "# User\n\nHoang prefers concise facts."
    )
    read_back = read_memory_file("wiki/user.md")

    assert written.path == "wiki/user.md"
    assert read_back.content == "# User\n\nHoang prefers concise facts."

    with pytest.raises(WikiPathError):
        write_memory_file("topics/legacy.md", "legacy")


@pytest.mark.asyncio
async def test_search_memory_messages_returns_visible_message_results(setup_db):
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
async def test_memory_search_merges_files_and_db_messages(
    setup_db, memory_dir: Path
) -> None:
    from app.core.db import async_session_factory

    seed_memory()
    (memory_dir / "wiki" / "memory.md").write_text(
        "# Memory\n\nBenchmarkable wiki retrieval.", encoding="utf-8"
    )
    session = ChatSession(agent_name="chat", title="Raw memory chat")
    async with async_session_factory() as db:
        db.add(session)
        await db.flush()
        db.add(
            SessionMessage(
                session_id=session.id,
                role="user",
                content="Benchmarkable raw retrieval fallback.",
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        results = await memory_search(db=db, query="benchmarkable retrieval", limit=5)

    refs = {result.source_ref for result in results}
    assert "wiki:memory" in refs
    assert any(ref.startswith("message:") for ref in refs)
