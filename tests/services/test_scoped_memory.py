from __future__ import annotations

import pytest
from sqlmodel import col, select

from app.models.chat import ChatSession, CodingProject
from app.models.memory import MemoryExtractionState, MemoryFact, MemoryFactEvidence
from app.services.scoped_memory import (
    ProposedMemoryFact,
    backfill_extracted_note_projections,
    claim_extraction,
    complete_extraction,
    fail_extraction,
    forget_session_memory,
    search_scoped_memory,
    store_extracted_facts,
)


@pytest.mark.asyncio
async def test_project_facts_are_isolated_but_user_preferences_are_global(setup_db):
    from app.core.db import async_session_factory

    project_a = CodingProject(name="A")
    project_b = CodingProject(name="B")
    session_a = ChatSession(mode="coding", project_id=project_a.id)
    session_b = ChatSession(mode="coding", project_id=project_b.id)
    async with async_session_factory() as db:
        db.add(project_a)
        db.add(project_b)
        await db.flush()
        db.add(session_a)
        db.add(session_b)
        await db.commit()
        await store_extracted_facts(
            db,
            session_a.id,
            [
                ProposedMemoryFact(
                    content="Use repository pattern for authentication changes",
                    kind="decision",
                    scope="project",
                    confidence="high",
                ),
                ProposedMemoryFact(
                    content="The user prefers concise evidence-backed explanations",
                    kind="preference",
                    scope="user",
                    confidence="high",
                ),
            ],
        )
        await db.commit()

    async with async_session_factory() as db:
        own = await search_scoped_memory(
            db, session_a.id, "repository authentication pattern"
        )
        other = await search_scoped_memory(
            db, session_b.id, "repository authentication pattern"
        )
        preference = await search_scoped_memory(
            db, session_b.id, "concise evidence explanations"
        )

    assert any(result.diagnostics["scope_type"] == "project" for result in own)
    assert not any(result.diagnostics["scope_type"] == "project" for result in other)
    assert any(result.diagnostics["scope_type"] == "user" for result in preference)


@pytest.mark.asyncio
async def test_fact_dedupes_and_keeps_multi_session_provenance(setup_db):
    from app.core.db import async_session_factory

    project = CodingProject(name="Shared")
    first = ChatSession(mode="coding", project_id=project.id)
    second = ChatSession(mode="coding", project_id=project.id)
    proposed = ProposedMemoryFact(
        content="Run contract tests before releasing the API",
        kind="convention",
        scope="project",
        confidence="high",
    )
    async with async_session_factory() as db:
        db.add(project)
        await db.flush()
        db.add(first)
        db.add(second)
        await db.commit()
        await store_extracted_facts(db, first.id, [proposed])
        await store_extracted_facts(db, second.id, [proposed])
        await db.commit()

        facts = list((await db.exec(select(MemoryFact))).all())
        evidence = list((await db.exec(select(MemoryFactEvidence))).all())

    assert len(facts) == 1
    assert facts[0].occurrences == 2
    assert {row.session_id for row in evidence} == {first.id, second.id}


@pytest.mark.asyncio
async def test_forget_keeps_supported_fact_then_removes_last_evidence(setup_db):
    from app.core.db import async_session_factory

    project = CodingProject(name="Shared")
    first = ChatSession(mode="coding", project_id=project.id)
    second = ChatSession(mode="coding", project_id=project.id)
    fact = ProposedMemoryFact(
        content="Use migration locks for schema changes",
        kind="decision",
        scope="project",
    )
    async with async_session_factory() as db:
        db.add(project)
        await db.flush()
        db.add(first)
        db.add(second)
        await db.commit()
        await store_extracted_facts(db, first.id, [fact])
        await store_extracted_facts(db, second.id, [fact])
        await db.commit()

        assert await forget_session_memory(db, first.id) == 0
        await db.commit()
        assert len((await db.exec(select(MemoryFact))).all()) == 1

        assert await forget_session_memory(db, second.id) == 1
        await db.commit()
        assert (await db.exec(select(MemoryFact))).all() == []


@pytest.mark.asyncio
async def test_extraction_cursor_triggers_at_minimum_and_retries_failure(setup_db):
    from app.core.db import async_session_factory

    session = ChatSession()
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()

        assert not await claim_extraction(
            db,
            session.id,
            assistant_count=2,
            content_hash="a",
            min_assistant_messages=3,
            every_n_messages=10,
        )
        assert await claim_extraction(
            db,
            session.id,
            assistant_count=3,
            content_hash="b",
            min_assistant_messages=3,
            every_n_messages=10,
        )
        await complete_extraction(db, session.id, assistant_count=3)
        await db.commit()

        assert not await claim_extraction(
            db,
            session.id,
            assistant_count=12,
            content_hash="c",
            min_assistant_messages=3,
            every_n_messages=10,
        )
        assert await claim_extraction(
            db,
            session.id,
            assistant_count=13,
            content_hash="d",
            min_assistant_messages=3,
            every_n_messages=10,
        )
        await fail_extraction(
            db, session.id, assistant_count=13, error="provider unavailable"
        )
        await db.commit()

        assert await claim_extraction(
            db,
            session.id,
            assistant_count=13,
            content_hash="d",
            min_assistant_messages=3,
            every_n_messages=10,
        )
        state = await db.get(MemoryExtractionState, session.id)

    assert state is not None
    assert state.attempts == 3
    assert state.last_assistant_count == 3
    assert state.status == "processing"


@pytest.mark.asyncio
async def test_automatic_recall_abstains_for_generic_single_token(setup_db):
    from app.core.db import async_session_factory

    session = ChatSession()
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()
        await store_extracted_facts(
            db,
            session.id,
            [ProposedMemoryFact(content="Commit signed release artifacts")],
        )
        await db.commit()

        explicit = await search_scoped_memory(db, session.id, "commit")
        automatic = await search_scoped_memory(db, session.id, "commit", automatic=True)

    assert explicit
    assert automatic == []


@pytest.mark.asyncio
async def test_source_message_fk_is_optional_for_background_extraction(setup_db):
    from app.core.db import async_session_factory

    session = ChatSession()
    async with async_session_factory() as db:
        db.add(session)
        await db.commit()
        stored = await store_extracted_facts(
            db,
            session.id,
            [ProposedMemoryFact(content="Prefer deterministic memory tests")],
            source_message_id=None,
        )
        await db.commit()
        evidence = (
            await db.exec(
                select(MemoryFactEvidence).where(
                    col(MemoryFactEvidence.fact_id) == stored[0].id
                )
            )
        ).one()

    assert evidence.source_message_id is None
    assert evidence.session_id == session.id


@pytest.mark.asyncio
async def test_legacy_note_backfill_is_idempotent_and_scoped(
    setup_db, tmp_path, monkeypatch
):
    from app.core.config import settings
    from app.core.db import async_session_factory

    wiki = tmp_path / "wiki"
    notes = wiki / "notes"
    notes.mkdir(parents=True)
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(wiki))

    project = CodingProject(name="Legacy")
    session = ChatSession(mode="coding", project_id=project.id)
    async with async_session_factory() as db:
        db.add(project)
        await db.flush()
        db.add(session)
        await db.commit()

    (notes / "2026-08-01.md").write_text(
        "## 10:00 UTC\n\n"
        f"<!-- evoflux-memory-facts:v1 source=session:{session.id} -->\n\n"
        "- Use deterministic migrations for releases\n"
        "- The user wants one temporary report\n"
        "- [user/preference/high] The user prefers concise verified answers\n",
        encoding="utf-8",
    )
    async with async_session_factory() as db:
        first = await backfill_extracted_note_projections(db, force=True)
        second = await backfill_extracted_note_projections(db, force=True)
        facts = list((await db.exec(select(MemoryFact))).all())
        evidence = list((await db.exec(select(MemoryFactEvidence))).all())

    assert first["facts"] == 3
    assert second["facts"] == 3  # observed, but not duplicated/reinforced
    assert len(facts) == 3
    assert len(evidence) == 3
    assert {fact.scope_type for fact in facts} == {"project", "user"}
    assert {fact.occurrences for fact in facts} == {1}
    assert {
        fact.scope_type for fact in facts if "temporary report" in fact.content
    } == {"project"}
