from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, CodingProject, CodingWorkspace, SessionMessage
from app.scheduler.models import ScheduledTask
from app.services.app_search_service import search_app


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def quiet_file_sources(monkeypatch):
    """Keep the file-backed sources empty unless a test fills them in.

    The service imports these lazily, so patching the owning module is what
    the call site sees.
    """
    monkeypatch.setattr(
        "app.services.memory.search_memory_files", lambda query, **kwargs: []
    )
    monkeypatch.setattr("app.services.agent_fs.list_agents", lambda: [])
    monkeypatch.setattr("app.services.agent_fs.list_skills", lambda: [])


@pytest.mark.asyncio
async def test_blank_query_returns_nothing(session):
    assert await search_app(session, "   ") == []


@pytest.mark.asyncio
async def test_finds_sessions_by_title(session):
    session.add(ChatSession(title="Refactor the billing importer", mode="work"))
    session.add(ChatSession(title="Unrelated chat", mode="work"))
    await session.commit()

    items = await search_app(session, "billing")

    assert [item.kind for item in items] == ["session"]
    assert items[0].label == "Refactor the billing importer"
    assert items[0].session_id is not None


@pytest.mark.asyncio
async def test_finds_message_content_and_opens_the_owning_session(session):
    lead = ChatSession(title="Payments team", mode="work")
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    member = ChatSession(title="worker", parent_session_id=lead.id, mode="work")
    session.add(member)
    await session.commit()
    await session.refresh(member)
    session.add(
        SessionMessage(
            session_id=member.id,
            role="assistant",
            content="The refund webhook retries three times before parking the job.",
        )
    )
    await session.commit()

    items = await search_app(session, "refund webhook")

    message = next(item for item in items if item.kind == "message")
    # The sub-session is never listed in the sidebar — open the lead instead.
    assert message.session_id == str(lead.id)
    # The row is named after the chat it opens; the match is the second line.
    assert message.label == "Payments team"
    assert "refund webhook" in message.description


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["toàn cục", "TOÀN CỤC", "Toàn Cục"])
async def test_matches_are_case_insensitive_beyond_ascii(session, query):
    session.add(ChatSession(title="Tìm Kiếm Toàn Cục", mode="work"))
    other = ChatSession(title="Ghi chú palette", mode="work")
    session.add(other)
    await session.commit()
    await session.refresh(other)
    session.add(
        SessionMessage(
            session_id=other.id,
            role="user",
            content="Bật tìm kiếm toàn cục cho palette",
        )
    )
    await session.commit()

    items = await search_app(session, query)

    assert "Tìm Kiếm Toàn Cục" in [item.label for item in items]
    assert any(item.kind == "message" for item in items)


@pytest.mark.asyncio
async def test_messages_collapse_to_one_row_per_chat(session):
    chat = ChatSession(title="Payments", mode="work")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    for index in range(4):
        session.add(
            SessionMessage(
                session_id=chat.id,
                role="assistant",
                content=f"refund webhook attempt {index}",
            )
        )
    await session.commit()

    items = await search_app(session, "refund webhook")

    messages = [item for item in items if item.kind == "message"]
    assert len(messages) == 1
    assert messages[0].label == "Payments"
    assert messages[0].description.startswith("4 matches · ")
    assert messages[0].metadata is not None
    assert messages[0].metadata["match_count"] == 4


@pytest.mark.asyncio
async def test_a_chat_that_matches_by_title_is_not_repeated_as_a_message(session):
    chat = ChatSession(title="refund webhook retries", mode="work")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    session.add(
        SessionMessage(
            session_id=chat.id, role="user", content="the refund webhook retries twice"
        )
    )
    await session.commit()

    items = await search_app(session, "refund webhook")

    # One chat, one row — both rows would have opened the same conversation.
    assert [item.kind for item in items] == ["session"]


@pytest.mark.asyncio
async def test_excerpt_drops_markdown_scaffolding(session):
    chat = ChatSession(title="Release", mode="work")
    session.add(chat)
    await session.commit()
    await session.refresh(chat)
    session.add(
        SessionMessage(
            session_id=chat.id,
            role="assistant",
            content="## Phase 1\n**Root cause:** the `spend_limit` table is missing.",
        )
    )
    await session.commit()

    items = await search_app(session, "spend_limit")

    excerpt = next(item for item in items if item.kind == "message").description
    assert "spend_limit" in excerpt
    assert "**" not in excerpt
    assert "`" not in excerpt
    assert "##" not in excerpt


@pytest.mark.asyncio
async def test_underscore_is_matched_literally(session):
    session.add(ChatSession(title="auth_service rewrite", mode="coding"))
    session.add(ChatSession(title="authXservice rewrite", mode="coding"))
    await session.commit()

    items = await search_app(session, "auth_service")

    assert [item.label for item in items] == ["auth_service rewrite"]


@pytest.mark.asyncio
async def test_session_rows_carry_what_the_coding_route_needs(session):
    project = CodingProject(name="Atlas", description="")
    session.add(project)
    await session.commit()
    await session.refresh(project)
    route = {
        "mode": "coding",
        "workspace": "/repos/atlas",
        "project_id": project.id,
    }
    session.add(ChatSession(title="atlas rollout", **route))
    # A second chat carries the match in its dialogue rather than its title,
    # so both kinds of row are present.
    discussion = ChatSession(title="deploy log", **route)
    session.add(discussion)
    await session.commit()
    await session.refresh(discussion)
    session.add(
        SessionMessage(
            session_id=discussion.id, role="user", content="atlas rollout notes"
        )
    )
    await session.commit()

    items = await search_app(session, "atlas rollout")

    # Both kinds navigate, so both need the mode/workspace/project triple that
    # /coding/{focus}/{session} is built from.
    for kind in ("session", "message"):
        row = next(item for item in items if item.kind == kind)
        assert row.metadata is not None
        assert row.metadata["mode"] == "coding"
        assert row.metadata["workspace"] == "/repos/atlas"
        assert row.metadata["project_id"] == str(project.id)


@pytest.mark.asyncio
async def test_covers_projects_workspaces_and_scheduled_tasks(session):
    session.add(CodingProject(name="Atlas", description="Billing platform"))
    session.add(CodingWorkspace(path="/repos/atlas-api", name="atlas-api"))
    session.add(
        ScheduledTask(
            name="atlas-nightly",
            schedule_type="cron",
            cron_expression="0 2 * * *",
            prompt="Summarise the Atlas build",
        )
    )
    await session.commit()

    kinds = {item.kind for item in await search_app(session, "atlas")}

    assert kinds == {"project", "workspace", "scheduled_task"}


@pytest.mark.asyncio
async def test_hidden_projects_and_workspaces_stay_out(session):
    session.add(CodingProject(name="Atlas", description="", hidden=True))
    session.add(CodingWorkspace(path="/repos/atlas-api", hidden=True))
    await session.commit()

    assert await search_app(session, "atlas") == []


@pytest.mark.asyncio
async def test_limit_caps_the_merged_result(session):
    for index in range(12):
        session.add(ChatSession(title=f"atlas run {index}", mode="work"))
    await session.commit()

    items = await search_app(session, "atlas", limit=5)

    assert len(items) == 5


@pytest.mark.asyncio
async def test_a_failing_source_does_not_blank_the_palette(session, monkeypatch):
    async def boom(db, query, limit):
        raise RuntimeError("scheduler table is missing")

    monkeypatch.setattr("app.services.app_search_service._scheduled_task_items", boom)
    session.add(ChatSession(title="atlas rollout", mode="work"))
    await session.commit()

    items = await search_app(session, "atlas")

    assert [item.kind for item in items] == ["session"]


@pytest.mark.asyncio
async def test_memory_agent_and_skill_sources_are_included(session, monkeypatch):
    from app.services import agent_fs
    from app.services.memory import MemorySearchResult

    monkeypatch.setattr(
        "app.services.memory.search_memory_files",
        lambda query, **kwargs: [
            MemorySearchResult(
                source_ref="memory:topics/atlas.md",
                path="topics/atlas.md",
                title="Atlas rollout",
                excerpt="<!-- evoflux-memory-facts:v1 --> **Atlas** ships weekly",
                score=1.0,
            )
        ],
    )
    monkeypatch.setattr(agent_fs, "list_agents", lambda: ["atlas-reviewer"])
    monkeypatch.setattr(
        agent_fs,
        "read_agent",
        lambda name: agent_fs.AgentFileRecord(
            name=name,
            path=f"/agents/{name}.md",
            content="---\ndescription: Reviews Atlas changes\n---\nbody\n",
        ),
    )
    monkeypatch.setattr(agent_fs, "list_skills", lambda: ["atlas-release"])
    monkeypatch.setattr(
        agent_fs,
        "read_skill",
        lambda name: agent_fs.SkillFileRecord(
            name=name,
            path=f"/skills/{name}/SKILL.md",
            content="---\ndescription: Cuts an Atlas release\n---\nbody\n",
        ),
    )

    items = await search_app(session, "atlas")
    kinds = {item.kind for item in items}
    assert {"memory", "agent", "skill"} <= kinds
    memory_item = next(item for item in items if item.kind == "memory")
    assert memory_item.path == "topics/atlas.md"
    # Memory pages open with bookkeeping comments — a row shows the prose.
    assert memory_item.description == "Atlas ships weekly"
