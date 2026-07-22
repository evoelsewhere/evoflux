"""Tests for app/agent/agent_loop.py — missing coverage lines.

Covers:
- Line 235: before_model hook returns non-None updated request
- Lines 276, 278, 280: usage dict optional fields (cache, thoughts, tool_use)
- Line 457: tool_calls_buffer update when id is empty on first chunk, set on second
"""

from __future__ import annotations

from unittest.mock import MagicMock


from app.agent.agent_loop import Agent
from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    HumanMessage,
    ToolCallDelta,
    FunctionCallDelta,
    ToolMessage,
    Usage,
)
from app.agent.schemas.agent import RunConfig
from app.agent.state import AgentState, ModelRequest, RunContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(chunks: list[ChatCompletionChunk]) -> Agent:
    """Build an Agent whose provider streams the given chunks."""

    async def _gen():
        for c in chunks:
            yield c

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()
    return Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
    )


def _text_chunk(content: str, finish: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-1",
        created=1,
        model="mock",
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(content=content),
                finish_reason=finish,
            )
        ],
    )


def _usage_chunk(
    prompt: int = 10,
    completion: int = 5,
    total: int = 15,
    cached: int | None = None,
    thoughts: int | None = None,
    tool_use: int | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-usage",
        created=1,
        model="mock",
        choices=[],
        usage=Usage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=cached,
            thoughts_tokens=thoughts,
            tool_use_tokens=tool_use,
        ),
    )


def _tool_chunk(
    idx: int,
    call_id: str | None,
    name: str | None = None,
    arguments: str = "",
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-tool",
        created=1,
        model="mock",
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(
                    tool_calls=[
                        ToolCallDelta(
                            index=idx,
                            id=call_id,
                            function=FunctionCallDelta(
                                name=name,
                                arguments=arguments,
                            ),
                        )
                    ]
                ),
                finish_reason=None,
            )
        ],
    )


def _finish_chunk() -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-finish",
        created=1,
        model="mock",
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(),
                finish_reason="stop",
            )
        ],
    )


def _text_chunk(content: str, *, finish: str | None = None) -> ChatCompletionChunk:
    """Return a chunk with text content (needed after tool calls)."""
    return ChatCompletionChunk(
        id="chunk-text",
        created=1,
        model="mock",
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionDelta(content=content),
                finish_reason=finish,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Line 235: before_model hook returns non-None updated request
# ---------------------------------------------------------------------------


async def test_before_model_hook_returns_updated_request():
    """Line 235: when a hook's before_model returns a non-None ModelRequest,
    model_request is updated to the returned value."""
    captured_prompts: list[str] = []

    class CapturingHook(BaseAgentHook):
        async def before_model(
            self,
            ctx: RunContext,
            state: AgentState,
            request: ModelRequest | None = None,
        ) -> ModelRequest | None:
            if request is not None:
                # Me return modified request with different system prompt
                return request.override(system_prompt="modified by hook")
            return None

        async def wrap_model_call(self, ctx, state, request, handler):
            # Me capture the system prompt that actually reaches the model
            captured_prompts.append(request.system_prompt)
            return await handler(request)

    async def _gen():
        yield _text_chunk("hello", finish="stop")
        yield _usage_chunk()

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="original prompt",
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s1", run_id="r1")
    await agent.run([HumanMessage(content="hi")], config=config)

    # Me hook modified the request — model saw "modified by hook"
    assert len(captured_prompts) >= 1
    assert captured_prompts[0] == "modified by hook"


async def test_stop_after_before_model_skips_provider_call():
    """Control commands can persist before_model changes without an LLM call."""

    class StopAfterBeforeModelHook(BaseAgentHook):
        async def before_model(
            self,
            ctx: RunContext,
            state: AgentState,
            request: ModelRequest | None = None,
        ) -> ModelRequest | None:
            state.messages.append(HumanMessage(content="compacted summary"))
            return (
                request.override(messages=tuple(state.messages_for_llm))
                if request
                else None
            )

    mock_provider = MagicMock()
    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        hooks=[StopAfterBeforeModelHook()],
    )

    config = RunConfig(
        session_id="s-compact",
        run_id="r-compact",
        metadata={"stop_after_before_model": True},
    )
    messages = await agent.run(
        [AssistantMessage(content="previous answer")], config=config
    )

    mock_provider.stream.assert_not_called()
    assert [m.content for m in messages] == ["previous answer", "compacted summary"]


# ---------------------------------------------------------------------------
# Lines 276, 278, 280: usage dict optional fields (cache, thoughts, tool_use)
# ---------------------------------------------------------------------------


async def test_usage_dict_includes_cache_thoughts_tool_use():
    """Lines 276, 278, 280: when Usage has cached/thoughts/tool_use tokens,
    assistant_msg.extra['usage'] contains 'cache', 'thoughts', 'tool_use' keys."""

    async def _gen():
        yield _text_chunk("hello", finish="stop")
        yield _usage_chunk(
            prompt=100,
            completion=50,
            total=150,
            cached=10,
            thoughts=5,
            tool_use=3,
        )

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
    )

    config = RunConfig(session_id="s2", run_id="r2")
    messages = await agent.run([HumanMessage(content="hi")], config=config)

    # Me find the assistant message
    assistant_msgs = [m for m in messages if isinstance(m, AssistantMessage)]
    assert len(assistant_msgs) >= 1
    extra = assistant_msgs[-1].extra or {}
    usage = extra.get("usage", {})

    assert usage.get("cache") == 10
    assert usage.get("thoughts") == 5
    assert usage.get("tool_use") == 3


async def test_usage_dict_no_optional_fields_when_none():
    """When Usage has no cached/thoughts/tool_use, those keys are absent from extra."""

    async def _gen():
        yield _text_chunk("hello", finish="stop")
        yield _usage_chunk(prompt=10, completion=5, total=15)

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
    )

    config = RunConfig(session_id="s3", run_id="r3")
    messages = await agent.run([HumanMessage(content="hi")], config=config)

    assistant_msgs = [m for m in messages if isinstance(m, AssistantMessage)]
    assert len(assistant_msgs) >= 1
    extra = assistant_msgs[-1].extra or {}
    usage = extra.get("usage", {})

    assert "cache" not in usage
    assert "thoughts" not in usage
    assert "tool_use" not in usage


# ---------------------------------------------------------------------------
# Line 457: tool_calls_buffer — id set on second chunk when first had no id
# ---------------------------------------------------------------------------


async def test_tool_calls_buffer_id_set_on_second_chunk():
    """Line 457: when first tool chunk has no id and second chunk has the id,
    the buffer is updated with the id from the second chunk."""
    # Me track what tool calls were assembled
    assembled_tool_calls: list = []

    class CapturingHook(BaseAgentHook):
        async def after_model(self, ctx, state, assistant_message):
            if assistant_message.tool_calls:
                assembled_tool_calls.extend(assistant_message.tool_calls)

    # Me first chunk: tool call at index 0, NO id, has name
    chunk1 = _tool_chunk(idx=0, call_id=None, name="search", arguments="")
    # Me second chunk: same index 0, NOW has id, no name (continuation)
    chunk2 = _tool_chunk(idx=0, call_id="call_abc", name=None, arguments='{"q":"test"}')
    # Me finish chunk
    chunk3 = _finish_chunk()
    chunk4 = _usage_chunk()

    async def _gen():
        yield chunk1
        yield chunk2
        yield chunk3
        yield chunk4

    mock_provider = MagicMock()
        # First call: tool chunks + text response. Subsequent: text only.
    _first_call_done = [False]
    def _stream_side_effect(**_kw):
        if not _first_call_done[0]:
            _first_call_done[0] = True
            return _gen()
        async def _text_only():
            yield _text_chunk("Done")
            yield _finish_chunk()
        return _text_only()
    mock_provider.stream.side_effect = _stream_side_effect

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s4", run_id="r4")
    await agent.run([HumanMessage(content="search something")], config=config)

    # Me the assembled tool call should have the id from the second chunk
    assert len(assembled_tool_calls) >= 1
    assert assembled_tool_calls[0].id == "call_abc"
    assert assembled_tool_calls[0].function.name == "search"


# ---------------------------------------------------------------------------
# Multimodal ToolResult handling
# ---------------------------------------------------------------------------


async def test_capabilities_set_on_agent_state():
    """Agent.run() sets capabilities and tool_names as typed fields on AgentState."""
    from app.agent.providers.capabilities import ModelCapabilities

    captured_state = None

    class CapturingHook(BaseAgentHook):
        async def before_agent(self, ctx, state):
            nonlocal captured_state
            captured_state = state

    async def _gen():
        yield _finish_chunk()

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()
    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s5", run_id="r5")
    await agent.run([HumanMessage(content="hello")], config=config)

    assert captured_state is not None
    assert isinstance(captured_state.capabilities, ModelCapabilities)
    assert isinstance(captured_state.tool_names, list)


async def test_tool_result_creates_tool_message_with_parts():
    """When a tool returns ToolResult, the resulting ToolMessage has .parts set."""
    from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
    import base64

    captured_messages: list = []

    class CapturingHook(BaseAgentHook):
        async def after_agent(self, ctx, state, assistant_msg):
            captured_messages.extend(state.messages)

    # Tool that returns ToolResult with multimodal parts
    async def get_image():
        """Get image."""
        img_data = base64.b64encode(b"fake_image").decode("ascii")
        return ToolResult(
            parts=[
                TextBlock(text="Image description"),
                ImageDataBlock(data=img_data, media_type="image/png"),
            ]
        )

    async def _gen():
        yield _tool_chunk(0, "call_1", "get_image", "")
        yield _finish_chunk()
        # Text response after tool call
        yield _text_chunk("Done")
        yield _finish_chunk()

    mock_provider = MagicMock()
        # First call: tool chunks + text response. Subsequent: text only.
    _first_call_done = [False]
    def _stream_side_effect(**_kw):
        if not _first_call_done[0]:
            _first_call_done[0] = True
            return _gen()
        async def _text_only():
            yield _text_chunk("Done")
            yield _finish_chunk()
        return _text_only()
    mock_provider.stream.side_effect = _stream_side_effect

    from app.agent.tools.registry import Tool

    tool = Tool(get_image)

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        tools=[tool],
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s6", run_id="r6")
    await agent.run([HumanMessage(content="get image")], config=config)

    # Find the ToolMessage in captured messages
    tool_messages = [m for m in captured_messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) >= 1
    tool_msg = tool_messages[0]
    assert tool_msg.parts is not None
    assert len(tool_msg.parts) == 2
    assert isinstance(tool_msg.parts[0], TextBlock)
    assert isinstance(tool_msg.parts[1], ImageDataBlock)


async def test_tool_result_content_derived_from_text_blocks():
    """When a tool returns ToolResult, ToolMessage.content is derived from TextBlock items."""
    from app.agent.schemas.chat import TextBlock, ToolResult

    captured_messages: list = []

    class CapturingHook(BaseAgentHook):
        async def after_agent(self, ctx, state, assistant_msg):
            captured_messages.extend(state.messages)

    # Tool that returns ToolResult with multiple TextBlocks
    async def process():
        """Process."""
        return ToolResult(
            parts=[
                TextBlock(text="First part"),
                TextBlock(text="Second part"),
            ]
        )

    async def _gen():
        yield _tool_chunk(0, "call_1", "process", "")
        yield _finish_chunk()
        # Text response after tool call
        yield _text_chunk("Done")
        yield _finish_chunk()

    mock_provider = MagicMock()
        # First call: tool chunks + text response. Subsequent: text only.
    _first_call_done = [False]
    def _stream_side_effect(**_kw):
        if not _first_call_done[0]:
            _first_call_done[0] = True
            return _gen()
        async def _text_only():
            yield _text_chunk("Done")
            yield _finish_chunk()
        return _text_only()
    mock_provider.stream.side_effect = _stream_side_effect

    from app.agent.tools.registry import Tool

    tool = Tool(process)

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        tools=[tool],
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s7", run_id="r7")
    await agent.run([HumanMessage(content="process")], config=config)

    # Find the ToolMessage
    tool_messages = [m for m in captured_messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) >= 1
    tool_msg = tool_messages[0]
    # Content should be derived from TextBlocks
    assert tool_msg.content == "First part Second part"


# ---------------------------------------------------------------------------
# Partial tool calls (mid-arguments interrupt) are filtered before assembly
# ---------------------------------------------------------------------------


async def test_partial_tool_call_with_invalid_json_is_dropped():
    """Truncated JSON ``arguments`` → tool call dropped before the
    ``AssistantMessage`` is built."""
    captured_tool_calls: list = []

    class CapturingHook(BaseAgentHook):
        async def after_model(self, ctx, state, assistant_message):
            captured_tool_calls.append(assistant_message.tool_calls)

    truncated = '{"file_path": "/tmp/a.py", "old_string": "def foo'

    async def _gen():
        yield _tool_chunk(0, "fc_xyz", "Edit", truncated)
        yield _finish_chunk()

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s_partial", run_id="r_partial")
    await agent.run([HumanMessage(content="edit a file")], config=config)

    assert captured_tool_calls, "after_model hook never fired"
    assert captured_tool_calls[0] is None


async def test_partial_tool_call_with_empty_name_is_dropped():
    """Stream interrupted before OpenAI Responses ``function_call_arguments.done``
    fires → tool name stays empty → entry dropped."""
    captured_tool_calls: list = []

    class CapturingHook(BaseAgentHook):
        async def after_model(self, ctx, state, assistant_message):
            captured_tool_calls.append(assistant_message.tool_calls)

    async def _gen():
        yield _tool_chunk(0, "fc_xyz", None, '{"ok": true}')
        yield _finish_chunk()

    mock_provider = MagicMock()
    mock_provider.stream.return_value = _gen()

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s_empty_name", run_id="r_empty_name")
    await agent.run([HumanMessage(content="hi")], config=config)

    assert captured_tool_calls, "after_model hook never fired"
    assert captured_tool_calls[0] is None


async def test_complete_tool_call_with_empty_args_is_kept():
    """Empty ``arguments`` string is a legitimate no-arg call — must not be
    filtered out."""
    captured_tool_calls: list = []

    class CapturingHook(BaseAgentHook):
        async def after_model(self, ctx, state, assistant_message):
            if assistant_message.tool_calls:
                captured_tool_calls.extend(assistant_message.tool_calls)

    async def noop():
        """No-arg tool."""
        return "ok"

    async def _gen():
        yield _tool_chunk(0, "fc_xyz", "noop", "")
        yield _finish_chunk()
        # Text response after tool call
        yield _text_chunk("Done")
        yield _finish_chunk()

    mock_provider = MagicMock()
        # First call: tool chunks + text response. Subsequent: text only.
    _first_call_done = [False]
    def _stream_side_effect(**_kw):
        if not _first_call_done[0]:
            _first_call_done[0] = True
            return _gen()
        async def _text_only():
            yield _text_chunk("Done")
            yield _finish_chunk()
        return _text_only()
    mock_provider.stream.side_effect = _stream_side_effect

    from app.agent.tools.registry import Tool

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        tools=[Tool(noop)],
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s_empty_args", run_id="r_empty_args")
    await agent.run([HumanMessage(content="run noop")], config=config)

    assert len(captured_tool_calls) == 1
    assert captured_tool_calls[0].function.name == "noop"


async def test_plain_string_tool_result_has_no_parts():
    """When a tool returns a plain str, ToolMessage.parts is NOT set (None)."""
    captured_messages: list = []

    class CapturingHook(BaseAgentHook):
        async def after_agent(self, ctx, state, assistant_msg):
            captured_messages.extend(state.messages)

    # Tool that returns plain string
    async def simple():
        """Simple."""
        return "Plain text result"

    async def _gen():
        yield _tool_chunk(0, "call_1", "simple", "")
        yield _finish_chunk()
        # Text response after tool call
        yield _text_chunk("Done")
        yield _finish_chunk()

    mock_provider = MagicMock()
        # First call: tool chunks + text response. Subsequent: text only.
    _first_call_done = [False]
    def _stream_side_effect(**_kw):
        if not _first_call_done[0]:
            _first_call_done[0] = True
            return _gen()
        async def _text_only():
            yield _text_chunk("Done")
            yield _finish_chunk()
        return _text_only()
    mock_provider.stream.side_effect = _stream_side_effect

    from app.agent.tools.registry import Tool

    tool = Tool(simple)

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="You are helpful.",
        tools=[tool],
        hooks=[CapturingHook()],
    )

    config = RunConfig(session_id="s8", run_id="r8")
    await agent.run([HumanMessage(content="simple")], config=config)

    # Find the ToolMessage
    tool_messages = [m for m in captured_messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) >= 1
    tool_msg = tool_messages[0]
    # Parts should be None for plain string result
    assert tool_msg.parts is None
    assert tool_msg.content == "Plain text result"


# ---------------------------------------------------------------------------
# Adjacent HumanMessage merge — see streaming._merge_consecutive_user_messages.
# ---------------------------------------------------------------------------


def test_merge_consecutive_user_messages_joins_text_pairs():
    from app.agent.agent_loop.streaming import _merge_consecutive_user_messages
    from app.agent.schemas.chat import HumanMessage, SystemMessage

    out = _merge_consecutive_user_messages(
        [
            SystemMessage(content="sys"),
            HumanMessage(content="first"),
            HumanMessage(content="second"),
        ]
    )
    assert len(out) == 2
    assert isinstance(out[0], SystemMessage)
    assert isinstance(out[1], HumanMessage)
    assert out[1].content == "first\n\nsecond"


def test_merge_consecutive_user_messages_does_not_cross_other_roles():
    from app.agent.agent_loop.streaming import _merge_consecutive_user_messages
    from app.agent.schemas.chat import AssistantMessage, HumanMessage

    out = _merge_consecutive_user_messages(
        [
            HumanMessage(content="A"),
            AssistantMessage(content="ack"),
            HumanMessage(content="B"),
        ]
    )
    assert len(out) == 3
    assert out[0].content == "A"
    assert out[2].content == "B"


def test_merge_consecutive_user_messages_preserves_multimodal_neighbours():
    from app.agent.agent_loop.streaming import _merge_consecutive_user_messages
    from app.agent.schemas.chat import HumanMessage, TextBlock

    out = _merge_consecutive_user_messages(
        [
            HumanMessage(content="A"),
            HumanMessage(content="B", parts=[TextBlock(text="B")]),
        ]
    )
    assert len(out) == 2


async def test_stream_and_assemble_merges_consecutive_user_messages():
    """provider.stream() must receive a single merged user message."""
    captured_kwargs: dict = {}

    async def _gen():
        yield _text_chunk("ok", finish="stop")
        yield _usage_chunk()

    def _capture(**kwargs):
        captured_kwargs.update(kwargs)
        return _gen()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _capture

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="sys",
    )

    await agent.run(
        [HumanMessage(content="first"), HumanMessage(content="second")],
        config=RunConfig(session_id="s_merge", run_id="r_merge"),
    )

    sent = captured_kwargs["messages"]
    assert len(sent) == 2  # SystemMessage + one merged HumanMessage
    user_msgs = [m for m in sent if isinstance(m, HumanMessage)]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "first\n\nsecond"


# ---------------------------------------------------------------------------
# deferred_tools: hidden from tool_defs until load_tool activates them
# ---------------------------------------------------------------------------


async def test_deferred_tool_hidden_until_activated():
    """A deferred tool is absent from tool_defs until load_tool activates it,
    then present starting the very next model call (same run, next iteration).
    Uses "browser_use" — a real entry in load_tool's catalog — as a stand-in
    Tool, since load_tool only accepts catalog names."""
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.tools.registry import Tool

    browser_use = Tool(lambda: "browser result", name="browser_use")
    calls: list[dict] = []

    async def _iter1():
        yield _tool_chunk(0, "call_1", "load_tool", '{"tool_name": "browser_use"}')
        yield _finish_chunk()

    async def _iter2():
        yield _text_chunk("done", finish="stop")

    def _stream_side_effect(**kwargs):
        calls.append(kwargs)
        return _iter1() if len(calls) == 1 else _iter2()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _stream_side_effect

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="sys",
        tools=[browser_use, load_tool],
    )

    await agent.run(
        [HumanMessage(content="use the browser")],
        config=RunConfig(session_id="s_defer", run_id="r_defer"),
        deferred_tools=frozenset({"browser_use"}),
    )

    assert len(calls) == 2
    names_call1 = {t["function"]["name"] for t in calls[0]["tools"]}
    names_call2 = {t["function"]["name"] for t in calls[1]["tools"]}
    assert "browser_use" not in names_call1
    assert "load_tool" in names_call1
    assert "browser_use" in names_call2


async def test_tool_metadata_drives_deferral_without_a_static_catalog():
    """Any granted tool marked deferred participates in lazy loading without
    adding its name to a second policy table."""
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.tools.registry import Tool

    specialized = Tool(
        lambda: "special result",
        name="future_specialized_tool",
        deferred=True,
        deferred_summary="Inspect a future specialized data source.",
    )
    calls: list[dict] = []

    async def _iter1():
        yield _tool_chunk(
            0,
            "call_1",
            "load_tool",
            '{"tool_name": "future_specialized_tool"}',
        )
        yield _finish_chunk()

    async def _iter2():
        yield _text_chunk("done", finish="stop")

    def _stream_side_effect(**kwargs):
        calls.append(kwargs)
        return _iter1() if len(calls) == 1 else _iter2()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _stream_side_effect
    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        tools=[specialized, load_tool],
    )

    await agent.run([HumanMessage(content="use the specialized source")])

    first_names = {t["function"]["name"] for t in calls[0]["tools"]}
    second_names = {t["function"]["name"] for t in calls[1]["tools"]}
    assert "future_specialized_tool" not in first_names
    assert "future_specialized_tool" in second_names


async def test_deferred_metadata_stays_visible_without_loader_tool():
    """A standalone Agent cannot strand a deferred tool when no activation
    tool was granted to that agent."""
    from app.agent.tools.registry import Tool

    specialized = Tool(
        lambda: "special result",
        name="standalone_specialized_tool",
        deferred=True,
    )
    captured: dict = {}

    async def _gen():
        yield _text_chunk("ok", finish="stop")

    def _capture(**kwargs):
        captured.update(kwargs)
        return _gen()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _capture
    agent = Agent(llm_provider=mock_provider, tools=[specialized])

    await agent.run([HumanMessage(content="hi")])

    names = {t["function"]["name"] for t in captured["tools"]}
    assert "standalone_specialized_tool" in names


async def test_deferred_tool_blocked_before_activation():
    """A deferred tool called directly (no prior load_tool) is refused by the
    executor and never actually runs — hiding the schema alone isn't a gate,
    tool_executor must enforce it too."""
    from app.agent.tools.registry import Tool

    call_count = [0]

    def _run_browser():
        call_count[0] += 1
        return "browser ran"

    browser_use = Tool(_run_browser, name="browser_use")
    captured: list = []

    hook_calls = [0]

    class CapturingHook(BaseAgentHook):
        async def wrap_tool_call(self, ctx, state, tool_call, handler):
            hook_calls[0] += 1
            return await handler(ctx, state, tool_call)

        async def after_agent(self, ctx, state, assistant_msg):
            captured.extend(state.messages)

    async def _iter1():
        yield _tool_chunk(0, "call_1", "browser_use", "{}")
        yield _finish_chunk()

    async def _iter2():
        yield _text_chunk("ok", finish="stop")

    calls = [0]

    def _stream_side_effect(**kwargs):
        calls[0] += 1
        return _iter1() if calls[0] == 1 else _iter2()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _stream_side_effect

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="sys",
        tools=[browser_use],
        hooks=[CapturingHook()],
    )

    await agent.run(
        [HumanMessage(content="use the browser")],
        config=RunConfig(session_id="s_blocked", run_id="r_blocked"),
        deferred_tools=frozenset({"browser_use"}),
    )

    assert call_count[0] == 0, "blocked tool must never actually execute"
    assert hook_calls[0] == 0, "blocked tool must not reach permission/plugin hooks"
    tool_messages = [m for m in captured if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "load_tool" in tool_messages[0].content
    assert "not yet available" in tool_messages[0].content


async def test_deferred_tools_none_is_backward_compatible():
    """Omitting deferred_tools sends every tool's definition, as before."""
    from app.agent.tools.registry import Tool

    heavy = Tool(lambda: "heavy result", name="heavy")
    captured: dict = {}

    async def _gen():
        yield _text_chunk("ok", finish="stop")

    def _capture(**kwargs):
        captured.update(kwargs)
        return _gen()

    mock_provider = MagicMock()
    mock_provider.stream.side_effect = _capture

    agent = Agent(
        llm_provider=mock_provider,
        name="test-agent",
        system_prompt="sys",
        tools=[heavy],
    )

    await agent.run(
        [HumanMessage(content="hi")],
        config=RunConfig(session_id="s_nodefer", run_id="r_nodefer"),
    )

    names = {t["function"]["name"] for t in captured["tools"]}
    assert "heavy" in names


async def test_load_tool_rejects_unknown_and_ungranted_names():
    """load_tool fails closed for names outside the catalog or not granted
    to this run, and never raises."""
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.state import AgentState

    state = AgentState(messages=[], tool_names=["load_tool"])  # "browser_use" absent
    unknown = await load_tool.arun(tool_name="not_a_real_tool", _injected={"_state": state})
    assert "not a deferred tool" in unknown

    not_granted = await load_tool.arun(tool_name="browser_use", _injected={"_state": state})
    assert "not available in this session" in not_granted
    assert "activated_deferred_tools" not in state.metadata


async def test_load_tool_search_uses_only_run_local_catalog():
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.state import AgentState

    state = AgentState(messages=[], tool_names=["load_tool", "mcp_docs_search"])
    state.metadata["deferred_tool_catalog"] = {
        "mcp_docs_search": "Search the connected documentation server."
    }

    result = await load_tool.arun(
        query="documentation search", _injected={"_state": state}
    )

    assert "mcp_docs_search" in result
    assert "browser_use" not in result


async def test_load_tool_batch_activation_is_atomic():
    from app.agent.tools.builtin.load_tool import load_tool
    from app.agent.state import AgentState

    state = AgentState(messages=[], tool_names=["load_tool", "bg_start", "bg_wait"])
    state.metadata["deferred_tool_catalog"] = {
        "bg_start": "Start background work.",
        "bg_wait": "Wait for background work.",
    }
    state.metadata["activated_deferred_tools"] = set()

    result = await load_tool.arun(
        tool_names=["bg_start", "bg_wait"], _injected={"_state": state}
    )

    assert "bg_start" in result and "bg_wait" in result
    assert state.metadata["activated_deferred_tools"] == {"bg_start", "bg_wait"}

    failed = await load_tool.arun(
        tool_names=["bg_start", "not_granted"], _injected={"_state": state}
    )

    assert "not available" in failed
    assert state.metadata["activated_deferred_tools"] == {"bg_start", "bg_wait"}
