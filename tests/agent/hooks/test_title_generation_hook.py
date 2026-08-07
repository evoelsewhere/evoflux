"""Tests for the non-blocking session title generation hook."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.hooks.title_generation import TitleGenerationHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, SystemMessage
from app.agent.state import AgentState, RunContext

_TEST_SESSION_ID = "12345678-1234-5678-1234-567812345678"


def make_ctx(
    session_id: str | None = _TEST_SESSION_ID,
    run_id: str = "run_1",
    agent_name: str = "bot",
) -> RunContext:
    return RunContext(session_id=session_id, run_id=run_id, agent_name=agent_name)


def make_state(messages: list | None = None) -> AgentState:
    return AgentState(messages=messages or [])


def make_hook() -> TitleGenerationHook:
    return TitleGenerationHook(
        provider=MagicMock(),
        db_factory=MagicMock(),
        system_prompt="test title prompt",
    )


async def start_primary_stream(
    hook: TitleGenerationHook,
    ctx: RunContext,
    state: AgentState,
) -> None:
    await hook.on_model_delta(ctx, state, MagicMock())


class TestBeforeAgentEarlyReturns:
    async def test_no_session_id_does_nothing(self):
        hook = make_hook()
        await hook.before_agent(
            make_ctx(session_id=None),
            make_state([HumanMessage(content="Hello")]),
        )

        assert hook._pending is None
        assert hook._task is None

    async def test_has_assistant_message_does_nothing(self):
        hook = make_hook()
        state = make_state(
            [
                HumanMessage(content="Hello"),
                AssistantMessage(content="Hi there"),
                HumanMessage(content="Follow up"),
            ]
        )

        await hook.before_agent(make_ctx(), state)

        assert hook._pending is None
        assert hook._task is None

    async def test_no_human_message_does_nothing(self):
        hook = make_hook()
        await hook.before_agent(
            make_ctx(),
            make_state([SystemMessage(content="You are helpful.")]),
        )

        assert hook._pending is None
        assert hook._task is None

    async def test_empty_human_content_does_nothing(self):
        hook = make_hook()
        await hook.before_agent(
            make_ctx(),
            make_state([HumanMessage(content="")]),
        )

        assert hook._pending is None
        assert hook._task is None

    async def test_scheduled_task_does_nothing(self):
        hook = make_hook()
        await hook.before_agent(
            make_ctx(),
            make_state([HumanMessage(content="[Scheduled Task: nightly] run")]),
        )

        assert hook._pending is None
        assert hook._task is None


class TestDeferredTitleGeneration:
    async def test_primary_stream_starts_before_title_request(self):
        hook = make_hook()
        ctx = make_ctx()
        state = make_state([HumanMessage(content="Write a sorting algorithm")])

        with patch(
            "app.services.title_service.generate_and_save_title",
            new_callable=AsyncMock,
        ) as mock_gen:
            await hook.before_agent(ctx, state)

            assert hook._pending is not None
            assert hook._task is None
            mock_gen.assert_not_awaited()

            await start_primary_stream(hook, ctx, state)
            assert hook._task is not None
            await hook._task

            mock_gen.assert_awaited_once()
            call_kwargs = mock_gen.call_args.kwargs
            assert str(call_kwargs["session_id"]) == _TEST_SESSION_ID
            assert call_kwargs["user_message"] == "Write a sorting algorithm"
            assert call_kwargs["provider"] is hook._provider
            assert call_kwargs["db_factory"] is hook._db_factory
            assert call_kwargs["system_prompt"] == "test title prompt"

    async def test_repeated_stream_chunks_spawn_only_one_task(self):
        hook = make_hook()
        ctx = make_ctx()
        state = make_state([HumanMessage(content="Hello")])

        with patch(
            "app.services.title_service.generate_and_save_title",
            new_callable=AsyncMock,
        ) as mock_gen:
            await hook.before_agent(ctx, state)
            await start_primary_stream(hook, ctx, state)
            first_task = hook._task
            await start_primary_stream(hook, ctx, state)

            assert hook._task is first_task
            assert first_task is not None
            await first_task
            mock_gen.assert_awaited_once()

    async def test_after_model_is_fallback_when_no_chunk_was_emitted(self):
        hook = make_hook()
        ctx = make_ctx()
        state = make_state([HumanMessage(content="Hello")])

        with patch(
            "app.services.title_service.generate_and_save_title",
            new_callable=AsyncMock,
        ) as mock_gen:
            await hook.before_agent(ctx, state)
            await hook.after_model(ctx, state, AssistantMessage(content="Done"))

            assert hook._task is not None
            await hook._task
            mock_gen.assert_awaited_once()

    async def test_after_agent_never_waits_for_pending_title(self):
        hook = make_hook()
        ctx = make_ctx()
        state = make_state([HumanMessage(content="Hello")])
        title_started = asyncio.Event()
        release_title = asyncio.Event()

        async def blocked_title(**_kwargs):
            title_started.set()
            await release_title.wait()

        with patch(
            "app.services.title_service.generate_and_save_title",
            new=AsyncMock(side_effect=blocked_title),
        ):
            await hook.before_agent(ctx, state)
            await start_primary_stream(hook, ctx, state)
            await title_started.wait()

            await asyncio.wait_for(
                hook.after_agent(ctx, state, AssistantMessage(content="Done")),
                timeout=0.05,
            )

            assert hook._task is not None
            assert not hook._task.done()
            release_title.set()
            await hook._task

    async def test_picks_last_non_empty_human_message(self):
        hook = make_hook()
        ctx = make_ctx()
        state = make_state(
            [
                SystemMessage(content="System prompt"),
                HumanMessage(content="First question"),
                HumanMessage(content="Actually, this one"),
                HumanMessage(content=""),
            ]
        )

        with patch(
            "app.services.title_service.generate_and_save_title",
            new_callable=AsyncMock,
        ) as mock_gen:
            await hook.before_agent(ctx, state)
            await start_primary_stream(hook, ctx, state)
            assert hook._task is not None
            await hook._task

            assert mock_gen.call_args.kwargs["user_message"] == "Actually, this one"

    async def test_short_messages_are_forwarded_unchanged(self):
        for message in ("Good morning!", "fix tests", "xin chào"):
            hook = make_hook()
            ctx = make_ctx()
            state = make_state([HumanMessage(content=message)])
            with patch(
                "app.services.title_service.generate_and_save_title",
                new_callable=AsyncMock,
            ) as mock_gen:
                await hook.before_agent(ctx, state)
                await start_primary_stream(hook, ctx, state)
                assert hook._task is not None
                await hook._task
                assert mock_gen.call_args.kwargs["user_message"] == message
