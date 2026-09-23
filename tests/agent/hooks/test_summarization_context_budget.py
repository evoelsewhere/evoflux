"""The compaction request has to fit the window it is trying to relieve.

A session whose ordinary turns fit in 200K sent a 404K compaction request —
the summariser replayed the raw transcript while the provider boundary was
projecting old tool results — and took a ``context_length_exceeded`` 400 on
every attempt. It then retried, and failed, on every subsequent turn: the
context could never shrink.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.agent.hooks import summarization as summarization_module
from app.agent.hooks.summarization import SummarizationHook
from app.agent.schemas.chat import (
    AssistantMessage,
    FunctionCall,
    HumanMessage,
    ToolCall,
    ToolMessage,
)
from app.agent.state import AgentState, ModelRequest, RunContext, UsageInfo

BIG_RESULT = "x" * 4_000


@pytest.fixture(autouse=True)
def _clear_failure_streaks():
    summarization_module._failure_streaks.clear()
    yield
    summarization_module._failure_streaks.clear()


def _make_ctx(session_id: str = "sess-budget") -> RunContext:
    return RunContext(session_id=session_id, run_id="run-1", agent_name="TestAgent")


def _history(batches: int = 8) -> list:
    """A tool-heavy transcript: one user turn, then *batches* tool rounds."""
    messages: list = [HumanMessage(content="start the work")]
    for index in range(batches):
        call_id = f"call-{index}"
        messages.append(
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id=call_id,
                        function=FunctionCall(name="read", arguments="{}"),
                    )
                ],
            )
        )
        messages.append(
            ToolMessage(
                content=f"{index}:{BIG_RESULT}",
                tool_call_id=call_id,
                name="read",
            )
        )
    return messages


def _make_state(batches: int = 8) -> AgentState:
    return AgentState(
        messages=_history(batches),
        usage=UsageInfo(last_prompt_tokens=1_000_000),
    )


def _provider(*, summary: str = "Summary text.", raises: list | None = None):
    """A provider whose stream yields a summary, or raises from *raises*."""
    provider = MagicMock()
    sent: list[list] = []
    errors = list(raises or [])

    def _stream(*_args, **kwargs):
        sent.append(list(kwargs.get("messages") or ()))

        async def _iter():
            if errors:
                raise errors.pop(0)
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = summary
            chunk.usage = None
            yield chunk

        return _iter()

    provider.stream.side_effect = _stream
    return provider, sent


def _overflow_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.test/v1/chat/completions")
    response = httpx.Response(
        400,
        text=(
            '{"error":{"message":"This model\'s maximum context length is '
            '262144 tokens. However, you requested 434091 tokens.",'
            '"type":"context_length_exceeded"}}'
        ),
        request=request,
    )
    return httpx.HTTPStatusError("400 Bad Request", request=request, response=response)


async def _compact(hook: SummarizationHook, ctx: RunContext, state: AgentState) -> None:
    await hook.before_model(ctx, state)
    request = ModelRequest(
        messages=tuple(state.messages_for_llm), system_prompt=state.system_prompt
    )

    async def _handler(_request: ModelRequest) -> AssistantMessage:
        return AssistantMessage(content="done")

    await hook.wrap_model_call(ctx, state, request, _handler)


def _hook(provider, **kwargs) -> SummarizationHook:
    return SummarizationHook(
        llm_provider=provider,
        summary_prompt="summarise this",
        prompt_token_threshold=1_000,
        keep_last_assistants=0,
        min_messages_since_last_summary=0,
        **kwargs,
    )


class TestProjectedRequest:
    """The compaction call sends what an ordinary turn sends."""

    @pytest.mark.asyncio
    async def test_old_tool_results_are_receipts_not_transcripts(self) -> None:
        provider, sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=2)

        ctx, state = _make_ctx(), _make_state(batches=8)
        await _compact(hook, ctx, state)

        assert sent, "the summariser never called the provider"
        tool_contents = [
            message.content for message in sent[0] if isinstance(message, ToolMessage)
        ]
        compacted = [c for c in tool_contents if "compacted" in (c or "")]
        assert compacted, "no old tool result was projected"
        # And the raw payload is gone from those.
        assert all(BIG_RESULT not in (c or "") for c in compacted)


class TestContextBudget:
    """Nothing is sent that the model's window cannot hold."""

    @pytest.mark.asyncio
    async def test_oldest_messages_are_dropped_to_fit(self) -> None:
        provider, sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx, state = _make_ctx(), _make_state(batches=8)
        eligible = len(state.messages)

        # A window far smaller than the transcript: 8 x 4,000 chars of tool
        # output is ~11K tokens by the hook's estimate.
        limits = MagicMock(context_length=6_000)
        with patch(
            "app.agent.hooks.summarization.get_model_limits", return_value=limits
        ):
            await _compact(hook, ctx, state)

        assert sent
        assert len(sent[0]) < eligible
        summary = next(m for m in state.messages if m.is_summary)
        assert "were dropped without being summarised" in summary.content

    @pytest.mark.asyncio
    async def test_an_unknown_window_is_left_alone(self) -> None:
        provider, sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx, state = _make_ctx(), _make_state(batches=8)

        limits = MagicMock(context_length=None)
        with patch(
            "app.agent.hooks.summarization.get_model_limits", return_value=limits
        ):
            await _compact(hook, ctx, state)

        summary = next(m for m in state.messages if m.is_summary)
        assert "dropped" not in summary.content

    @pytest.mark.asyncio
    async def test_a_trimmed_request_keeps_tool_pairs_valid(self) -> None:
        """A tool result whose call was trimmed away must go too."""
        provider, sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx, state = _make_ctx(), _make_state(batches=8)

        limits = MagicMock(context_length=6_000)
        with patch(
            "app.agent.hooks.summarization.get_model_limits", return_value=limits
        ):
            await _compact(hook, ctx, state)

        call_ids: set[str] = set()
        for message in sent[0]:
            if isinstance(message, AssistantMessage):
                call_ids.update(c.id for c in message.tool_calls or ())
            elif isinstance(message, ToolMessage):
                assert message.tool_call_id in call_ids


class TestOverflowRetry:
    """The endpoint is the authority on what fits."""

    @pytest.mark.asyncio
    async def test_a_rejected_request_is_retried_smaller(self) -> None:
        provider, sent = _provider(raises=[_overflow_error()])
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx, state = _make_ctx(), _make_state(batches=8)

        await _compact(hook, ctx, state)

        assert len(sent) == 2, "expected one retry"
        assert len(sent[1]) < len(sent[0])
        assert any(m.is_summary for m in state.messages)

    @pytest.mark.asyncio
    async def test_an_unrelated_400_is_not_retried(self) -> None:
        request = httpx.Request("POST", "https://api.test/v1/chat/completions")
        response = httpx.Response(
            400, text='{"error":{"message":"unknown tool"}}', request=request
        )
        provider, sent = _provider(
            raises=[httpx.HTTPStatusError("400", request=request, response=response)]
        )
        hook = _hook(provider, keep_recent_tool_batches=8)

        await _compact(hook, _make_ctx(), state := _make_state(batches=8))

        assert len(sent) == 1
        assert not any(m.is_summary for m in state.messages)


class TestFailureStreak:
    """A compaction that cannot work is not retried every turn forever."""

    @pytest.mark.asyncio
    async def test_compaction_stops_after_repeated_failures(self) -> None:
        errors = [_overflow_error() for _ in range(40)]
        provider, sent = _provider(raises=errors)
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx = _make_ctx("sess-stall")

        for _ in range(summarization_module._FAILURE_STREAK_LIMIT):
            await _compact(hook, ctx, _make_state(batches=8))

        calls_before = len(sent)
        await _compact(hook, ctx, _make_state(batches=8))
        assert len(sent) == calls_before, "a stalled session kept calling the provider"

    @pytest.mark.asyncio
    async def test_an_explicit_force_still_runs(self) -> None:
        provider, sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx = _make_ctx("sess-forced")
        summarization_module._failure_streaks[ctx.session_id] = 99

        state = _make_state(batches=8)
        state.metadata["force_summarization"] = True
        await _compact(hook, ctx, state)

        assert sent

    @pytest.mark.asyncio
    async def test_a_success_clears_the_streak(self) -> None:
        provider, _sent = _provider()
        hook = _hook(provider, keep_recent_tool_batches=8)
        ctx = _make_ctx("sess-recovered")
        summarization_module._failure_streaks[ctx.session_id] = 2

        await _compact(hook, ctx, _make_state(batches=8))

        assert summarization_module.compaction_failure_streak(ctx.session_id) == 0
