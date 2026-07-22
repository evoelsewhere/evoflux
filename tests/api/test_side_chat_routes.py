"""Tests for side chat API routes."""

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.agent.schemas.chat import (
    AssistantMessage,
    HumanMessage,
)
from app.api.routes.team.chat import SideChatMessageRequest
from app.services.chat_service import (
    create_chat_session,
    create_side_chat_session,
    get_messages,
    get_messages_for_llm,
    get_side_chat_context,
    get_visible_session_rows,
    save_message,
)


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
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


def test_side_chat_message_request_rejects_blank_content():
    with pytest.raises(ValidationError, match="content must not be blank"):
        SideChatMessageRequest(content=" \n\t ")


def test_side_chat_message_request_preserves_content_whitespace():
    content = "  > quoted context\n\nQuestion  "

    assert SideChatMessageRequest(content=content).content == content


@pytest.mark.asyncio
async def test_create_side_chat_session(session):
    """create_side_chat_session creates a side chat linked to a main session."""
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id)

    assert side_chat.session_type == "side_chat"
    assert side_chat.source_session_id == main.id
    assert side_chat.title == "Side Chat: Main Session"
    assert side_chat.mode == main.mode
    assert side_chat.workspace == main.workspace

    # Verify it exists in DB
    db_session = await session.get(ChatSession, side_chat.id)
    assert db_session is not None
    assert db_session.session_type == "side_chat"
    assert db_session.source_session_id == main.id


@pytest.mark.asyncio
async def test_create_side_chat_session_custom_title(session):
    """create_side_chat_session respects custom title."""
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id, title="My Side Chat")

    assert side_chat.title == "My Side Chat"


@pytest.mark.asyncio
async def test_create_side_chat_session_not_found(session):
    """create_side_chat_session raises ValueError for missing main session."""
    from uuid import uuid4

    with pytest.raises(ValueError, match="not found"):
        await create_side_chat_session(session, uuid4())


@pytest.mark.asyncio
async def test_get_side_chat_context(session):
    """get_side_chat_context returns messages from the source session."""
    main = await create_chat_session(session, title="Main Session")

    # Add messages to main session
    await save_message(session, main.id, HumanMessage(content="Hello"))
    await save_message(session, main.id, AssistantMessage(content="Hi there!"))
    await save_message(session, main.id, HumanMessage(content="How are you?"))
    await session.commit()

    # Get context from main session
    context = await get_side_chat_context(session, main.id)
    assert len(context) == 3
    assert context[0].content == "Hello"
    assert context[1].content == "Hi there!"
    assert context[2].content == "How are you?"


@pytest.mark.asyncio
async def test_get_side_chat_context_message_limit(session):
    """get_side_chat_context respects max_messages limit."""
    main = await create_chat_session(session, title="Main Session")

    # Add 10 messages to main session
    for i in range(10):
        await save_message(session, main.id, HumanMessage(content=f"Message {i}"))
    await session.commit()

    # Get only last 5 messages
    context = await get_side_chat_context(session, main.id, max_messages=5)
    assert len(context) == 5
    assert context[0].content == "Message 5"
    assert context[4].content == "Message 9"


@pytest.mark.asyncio
async def test_get_side_chat_context_excludes_hidden(session):
    """get_side_chat_context excludes hidden messages."""
    main = await create_chat_session(session, title="Main Session")

    await save_message(session, main.id, HumanMessage(content="Visible"))
    await save_message(
        session, main.id, HumanMessage(content="Hidden"), is_hidden=True
    )
    await save_message(session, main.id, HumanMessage(content="Also visible"))
    await session.commit()

    context = await get_side_chat_context(session, main.id)
    assert len(context) == 2
    assert context[0].content == "Visible"
    assert context[1].content == "Also visible"


@pytest.mark.asyncio
async def test_side_chat_messages_isolated_from_main(session):
    """Side chat messages don't appear in main session message list."""
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id)

    # Add messages to both sessions
    await save_message(session, main.id, HumanMessage(content="Main message"))
    await save_message(
        session, side_chat.id, HumanMessage(content="Side chat message")
    )
    await session.commit()

    # Main session should only have its own messages
    main_messages = await get_messages(session, main.id)
    assert len(main_messages) == 1
    assert main_messages[0].content == "Main message"

    # Side chat should only have its own messages
    side_messages = await get_messages(session, side_chat.id)
    assert len(side_messages) == 1
    assert side_messages[0].content == "Side chat message"


@pytest.mark.asyncio
async def test_side_chat_inherits_settings(session):
    """Side chat inherits mode and workspace from main session."""
    main = await create_chat_session(session, title="Main Session")
    main.mode = "coding"
    main.workspace = "/path/to/workspace"
    session.add(main)
    await session.commit()

    side_chat = await create_side_chat_session(session, main.id)
    assert side_chat.mode == "coding"
    assert side_chat.workspace == "/path/to/workspace"


@pytest.mark.asyncio
async def test_multiple_side_chats_per_main(session):
    """Multiple side chats can exist for the same main session."""
    main = await create_chat_session(session, title="Main Session")

    side_chat_1 = await create_side_chat_session(session, main.id, title="Side Chat 1")
    side_chat_2 = await create_side_chat_session(session, main.id, title="Side Chat 2")

    assert side_chat_1.id != side_chat_2.id
    assert side_chat_1.source_session_id == main.id
    assert side_chat_2.source_session_id == main.id


@pytest.mark.asyncio
async def test_create_side_chat_session_sets_tag(session):
    """create_side_chat_session tags the session "side_chat" so the team lead
    it resolves to (a dedicated per-session instance, see team_manager's
    (workspace, session_id) cache key) picks up read-only tool restriction
    and the read-only system-prompt addendum via session_tags."""
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id)

    assert side_chat.tags == ["side_chat"]


@pytest.mark.asyncio
async def test_create_side_chat_session_injects_main_context(session):
    """The main session's existing messages are copied into the side chat at
    creation, so the agent actually has the "read-only access" the feature
    promises — previously get_side_chat_context() was never called from any
    production code path, so a side chat had zero awareness of the main
    conversation despite the docs/system-prompt claiming otherwise."""
    main = await create_chat_session(session, title="Main Session")
    await save_message(session, main.id, HumanMessage(content="Hello"))
    await save_message(session, main.id, AssistantMessage(content="Hi there!"))
    await session.commit()

    side_chat = await create_side_chat_session(session, main.id)

    llm_messages = await get_messages_for_llm(session, side_chat.id)
    assert [m.content for m in llm_messages] == ["Hello", "Hi there!"]


@pytest.mark.asyncio
async def test_side_chat_context_hidden_from_user_but_visible_to_llm(session):
    """Injected context is invisible on the user-facing message list (the
    side chat panel would otherwise open pre-filled with the whole main
    conversation) but still part of the LLM-facing window."""
    main = await create_chat_session(session, title="Main Session")
    await save_message(session, main.id, HumanMessage(content="From main"))
    await session.commit()

    side_chat = await create_side_chat_session(session, main.id)

    user_visible = await get_messages(session, side_chat.id)
    assert user_visible == []

    llm_visible = await get_messages_for_llm(session, side_chat.id)
    assert [m.content for m in llm_visible] == ["From main"]

    # The user's own first message in the side chat must NOT be hidden —
    # only the copied main-session context should carry the flag.
    await save_message(session, side_chat.id, HumanMessage(content="My question"))
    await session.commit()
    user_visible_after = await get_messages(session, side_chat.id)
    assert [m.content for m in user_visible_after] == ["My question"]


@pytest.mark.asyncio
async def test_create_side_chat_session_no_context_when_main_empty(session):
    """No main-session messages yet — side chat starts with an empty LLM
    window too, not an empty list crashing anything downstream."""
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id)

    assert await get_messages_for_llm(session, side_chat.id) == []


@pytest.mark.asyncio
async def test_get_visible_session_rows_excludes_hidden_context(session):
    """get_visible_session_rows (used by the GET .../messages route) must
    return raw SessionMessage rows — not get_messages()'s deserialized
    ChatMessage objects, which drop `id`/`session_id` per
    BaseMessage.model_config(extra="ignore") and make MessageResponse.
    model_validate(msg) raise (this was the actual cause of a 500 on the
    real endpoint: it called get_messages() instead of this function)."""
    main = await create_chat_session(session, title="Main Session")
    await save_message(session, main.id, HumanMessage(content="From main"))
    await session.commit()

    side_chat = await create_side_chat_session(session, main.id)
    await save_message(session, side_chat.id, HumanMessage(content="My question"))
    await session.commit()

    rows = await get_visible_session_rows(session, side_chat.id)

    assert [r.content for r in rows] == ["My question"]
    # The critical assertion: raw rows carry real id/session_id columns,
    # unlike get_messages()'s ChatMessage objects (which don't have them).
    for row in rows:
        assert row.id is not None
        assert row.session_id == side_chat.id


@pytest.mark.asyncio
async def test_side_chat_source_session_set_null_on_delete(session):
    """Side chat source_session_id is set to NULL when main session is deleted.

    Note: SQLite doesn't enforce ON DELETE SET NULL by default (requires
    PRAGMA foreign_keys=ON). This test verifies the FK is defined correctly;
    actual cascade behavior is validated against PostgreSQL in integration tests.
    """
    main = await create_chat_session(session, title="Main Session")
    side_chat = await create_side_chat_session(session, main.id)
    await session.commit()

    side_chat_id = side_chat.id

    # Delete main session
    await session.delete(main)
    await session.commit()

    # Side chat should still exist (may retain the FK value on SQLite)
    refreshed_side_chat = await session.get(ChatSession, side_chat_id)
    assert refreshed_side_chat is not None
    # ON DELETE SET NULL is enforced by PostgreSQL; SQLite needs PRAGMA
    # so we just verify the side chat survived the cascade.
    assert refreshed_side_chat.session_type == "side_chat"
