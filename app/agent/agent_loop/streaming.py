"""Stream one LLM call and assemble the response into an :class:`AssistantMessage`.

The provider yields a sequence of OpenAI-style chat-completion chunks.
This module concatenates the textual content + reasoning, re-assembles
fragmented tool-call deltas back into whole :class:`ToolCall` objects,
and folds usage information into the final message.

Returns ``(AssistantMessage, last_usage)`` so the caller (``Agent.run``)
can both publish the message and update its rolling usage stats.

Lives outside the :class:`Agent` class because it depends only on the
agent's identity (name + id) for tagging the produced message — no
mutable instance state — which keeps the loop thin and the streaming
logic individually testable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.agent_loop.retry import StreamRestart, stream_with_retry
from app.agent.hooks.cache_boundary import CACHE_VOLATILE_MARKER
from app.agent.lifecycle import SLEEP_LIFECYCLE, SleepSentinelStreamFilter
from app.agent.outbound_redaction import (
    OutboundContext,
    load_outbound_data_policy,
    load_outbound_pii_policy,
    protect_outbound_payload,
)
from app.agent.usage import usage_to_dict
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    ChatCompletionDelta,
    EncryptedReasoningItem,
    HumanMessage,
    SystemMessage,
    ToolCall,
    Usage,
)

if TYPE_CHECKING:
    from typing import AsyncIterator

    from app.agent.hooks import BaseAgentHook
    from app.agent.providers.base import LLMProviderBase
    from app.agent.state import AgentState, ModelRequest, RunContext


def cache_affinity_key(session_id: str | None) -> str | None:
    """Derive a stable opaque provider-routing key without exposing session IDs."""
    if not session_id:
        return None
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return f"evoflux-v1:{digest}"


async def _interruptible_stream(
    source: AsyncIterator,
    interrupt_event: asyncio.Event | None,
):
    """Yield from *source* but stop promptly when *interrupt_event* fires.

    Each ``__anext__`` is awaited concurrently with ``interrupt_event.wait()``.
    If the event wins the race the in-flight fetch is cancelled, which
    propagates ``aclose()`` up through the provider's async generator
    and closes the underlying HTTP stream — so a long mid-chunk pause
    (e.g. Gemini extended-thinking) no longer hides the user's stop
    request until the next SSE event arrives.

    When ``interrupt_event`` is ``None`` this degrades to a plain
    ``async for`` so the no-interrupt path is allocation-free.
    """
    if interrupt_event is None:
        async for item in source:
            yield item
        return

    aiter = source.__aiter__()
    waiter = asyncio.ensure_future(interrupt_event.wait())
    try:
        while True:
            if interrupt_event.is_set():
                return
            fetch = asyncio.ensure_future(aiter.__anext__())
            try:
                done, _ = await asyncio.wait(
                    {fetch, waiter},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                fetch.cancel()
                raise
            if waiter in done and fetch not in done:
                fetch.cancel()
                try:
                    await fetch
                except (asyncio.CancelledError, BaseException):
                    pass
                return
            try:
                item = fetch.result()
            except StopAsyncIteration:
                return
            yield item
    finally:
        waiter.cancel()
        try:
            await waiter
        except (asyncio.CancelledError, BaseException):
            pass
        # Best-effort: close the upstream generator so the provider's
        # ``async with httpx.AsyncClient`` exits and the socket is
        # released instead of waiting on GC.
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except (asyncio.CancelledError, BaseException):
                pass


def _merge_consecutive_user_messages(
    messages: list[ChatMessage],
) -> list[ChatMessage]:
    """Join adjacent plain-text :class:`HumanMessage` rows with ``\\n\\n``.

    Some providers (notably OpenAI gpt-5.5) treat the latest user message
    as superseding earlier ones, dropping prior instructions. Merging at
    the wire preserves additive intent ("Stop + I forgot to add ...")
    while the DB keeps the rows separate.

    Multimodal pairs (either side has ``.parts``) stay separate to
    preserve attachment ordering.
    """
    if not messages:
        return messages
    merged: list[ChatMessage] = []
    for m in messages:
        prev = merged[-1] if merged else None
        can_merge = (
            isinstance(m, HumanMessage)
            and not m.parts
            and isinstance(prev, HumanMessage)
            and not prev.parts
        )
        if can_merge:
            assert isinstance(prev, HumanMessage)
            merged[-1] = HumanMessage(
                content=f"{prev.content or ''}\n\n{m.content or ''}".strip(),
                extra=prev.extra,
            )
        else:
            merged.append(m)
    return merged


async def stream_and_assemble(
    *,
    req: ModelRequest,
    ctx: RunContext,
    state: AgentState,
    hooks: list[BaseAgentHook],
    interrupt_event: asyncio.Event | None,
    tool_defs: list,
    primary_provider: LLMProviderBase,
    primary_label: str,
    fallback_provider: LLMProviderBase | None,
    fallback_label: str,
    agent_name: str,
    agent_id: str,
) -> tuple[AssistantMessage, Usage | None]:
    """Stream one LLM call and assemble the response.

    The innermost handler passed to ``build_model_chain`` in the
    :class:`~app.agent.agent_loop.Agent`.  Hook ``wrap_model_call``
    wrappers receive a callable bound to this and may modify ``req``
    before forwarding it.

    Returns the assembled :class:`AssistantMessage` plus the last
    :class:`Usage` chunk seen during streaming (so the caller can
    update rolling stats).
    """
    full_content = ""
    reasoning = ""
    reasoning_items: list[EncryptedReasoningItem] = []
    content_filter = SleepSentinelStreamFilter()
    last_choice_chunk = None
    tool_calls_buffer: dict[int, dict] = {}
    last_usage: Usage | None = None

    affinity_key = cache_affinity_key(ctx.session_id)

    # Prepend system prompt and merge any [user, user] adjacency for the
    # wire — DB keeps adjacent user rows verbatim.
    request_messages: list[ChatMessage] = list(req.messages)
    protected_prompt, protected_messages, redaction_report = protect_outbound_payload(
        system_prompt=req.system_prompt,
        messages=request_messages,
        policy=load_outbound_data_policy(),
        pii_policy=load_outbound_pii_policy(),
        context=OutboundContext(channel="model", destination=primary_label),
    )
    if redaction_report.matches:
        logger.warning(
            "outbound_sensitive_data_protected channel={} matches={} "
            "secret_matches={} pii_matches={} categories={}",
            redaction_report.context.label
            if redaction_report.context
            else "model:external",
            redaction_report.matches,
            redaction_report.secret_matches,
            redaction_report.pii_matches,
            ",".join(redaction_report.categories),
        )

    # CacheBoundaryHook (if registered) stamps the end of the stable prefix
    # with a marker. Strip it before anything else — logs, summarization, the
    # wire payload — ever sees it, and hand its position to caching-aware
    # providers so they can cache the stable head even though the tail
    # (memory context, skill catalog) changes almost every turn.
    cache_boundary: int | None = None
    marker_index = protected_prompt.find(CACHE_VOLATILE_MARKER)
    if marker_index != -1:
        cache_boundary = marker_index
        protected_prompt = (
            protected_prompt[:marker_index]
            + protected_prompt[marker_index + len(CACHE_VOLATILE_MARKER) :]
        )

    provider_messages: list[ChatMessage] = _merge_consecutive_user_messages(
        [SystemMessage(content=protected_prompt), *protected_messages]
    )

    upstream = stream_with_retry(
        primary_provider=primary_provider,
        primary_label=primary_label,
        fallback_provider=fallback_provider,
        fallback_label=fallback_label,
        agent_name=agent_name,
        ctx=ctx,
        state=state,
        hooks=hooks,
        interrupt_event=interrupt_event,
        cache_affinity_key=affinity_key,
        messages=provider_messages,
        tools=tool_defs or None,
        cache_boundary=cache_boundary,
    )
    async for chunk in _interruptible_stream(upstream, interrupt_event):
        # Preemptive interrupt: break out of streaming early.  The wrapper
        # also races against ``interrupt_event``, so this check fires
        # immediately even if the provider was mid-pause between chunks.
        if interrupt_event is not None and interrupt_event.is_set():
            logger.debug("agent_streaming_interrupted agent={}", agent_name)
            break

        # A retry restarted the provider stream after partial chunks were
        # already buffered.  Drop the partial assembly so the retry's output
        # replaces it instead of concatenating onto a half-formed message.
        if isinstance(chunk, StreamRestart):
            logger.warning(
                "agent_stream_restart_reset agent={} dropped_content_len={} dropped_tool_calls={}",
                agent_name,
                len(full_content),
                len(tool_calls_buffer),
            )
            full_content = ""
            reasoning = ""
            content_filter.reset()
            tool_calls_buffer = {}
            continue

        if chunk.choices:
            last_choice_chunk = chunk
        publish_chunk = chunk
        if chunk.choices and chunk.choices[0].delta.content:
            filtered_content = content_filter.feed(chunk.choices[0].delta.content)
            if filtered_content != chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.model_copy(
                    update={"content": filtered_content or None}
                )
                choice = chunk.choices[0].model_copy(update={"delta": delta})
                publish_chunk = chunk.model_copy(
                    update={"choices": [choice, *chunk.choices[1:]]}
                )

        for hook in hooks:
            await hook.on_model_delta(ctx, state, publish_chunk)

        if chunk.usage:
            last_usage = chunk.usage

        if not chunk.choices:
            continue

        delta = publish_chunk.choices[0].delta

        if delta.reasoning_content:
            reasoning += delta.reasoning_content
        # Opaque and replayed verbatim on the next call, unlike the summary
        # above — see EncryptedReasoningItem.
        if delta.reasoning_item:
            reasoning_items.append(delta.reasoning_item)
        if delta.content:
            full_content += delta.content

        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index if tc.index is not None else 0
                # Me warn if different tool call lands in same slot
                if (
                    idx in tool_calls_buffer
                    and tc.id
                    and tool_calls_buffer[idx]["id"]
                    and tc.id != tool_calls_buffer[idx]["id"]
                ):
                    logger.warning(
                        "tool_call_index_collision idx={} existing_id={} new_id={}",
                        idx,
                        tool_calls_buffer[idx]["id"],
                        tc.id,
                    )
                if idx not in tool_calls_buffer:
                    # Copilot's /responses endpoint streams tool call arguments
                    # as separate chunks with distinct indices and no name/id.
                    # The name arrives later on its own chunk. Detect two cases:
                    #   1. Duplicate args (same as last entry) → skip
                    #   2. New args (different from last entry) → append to last
                    if (
                        not tc.id
                        and not (tc.function and tc.function.name)
                        and tool_calls_buffer
                    ):
                        last_idx = max(tool_calls_buffer)
                        last_buf = tool_calls_buffer[last_idx]
                        new_args = tc.function.arguments if tc.function else ""
                        if new_args and new_args != last_buf["function"]["arguments"]:
                            last_buf["function"]["arguments"] += new_args
                        continue
                    tool_calls_buffer[idx] = {
                        "id": tc.id or "",
                        "function": {
                            "name": tc.function.name
                            if tc.function and tc.function.name
                            else "",
                            "arguments": tc.function.arguments
                            if tc.function and tc.function.arguments
                            else "",
                            "thought": tc.function.thought
                            if tc.function and tc.function.thought
                            else None,
                            "thought_signature": tc.function.thought_signature
                            if tc.function and tc.function.thought_signature
                            else None,
                        },
                    }
                else:
                    # Only update id if not already set — first id wins
                    if tc.id and not tool_calls_buffer[idx]["id"]:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            if not tool_calls_buffer[idx]["function"]["name"]:
                                tool_calls_buffer[idx]["function"]["name"] = (
                                    tc.function.name
                                )
                            # Copilot may send name at a new index when the
                            # last entry already has args but no name.
                            elif (
                                tool_calls_buffer
                                and max(tool_calls_buffer) == idx
                                and idx > 0
                                and idx - 1 in tool_calls_buffer
                                and not tool_calls_buffer[idx - 1]["function"]["name"]
                            ):
                                tool_calls_buffer[idx - 1]["function"]["name"] = (
                                    tc.function.name
                                )
                        if tc.function.arguments:
                            buf = tool_calls_buffer[idx]["function"]["arguments"]
                            if not buf:
                                tool_calls_buffer[idx]["function"]["arguments"] = (
                                    tc.function.arguments
                                )
                            else:
                                try:
                                    json.loads(buf)
                                except json.JSONDecodeError:
                                    tool_calls_buffer[idx]["function"]["arguments"] += (
                                        tc.function.arguments
                                    )
                        if tc.function.thought:
                            tool_calls_buffer[idx]["function"]["thought"] = (
                                tc.function.thought
                            )
                        if tc.function.thought_signature:
                            tool_calls_buffer[idx]["function"]["thought_signature"] = (
                                tool_calls_buffer[idx]["function"]["thought_signature"]
                                or ""
                            ) + tc.function.thought_signature

    tail_content, is_sleep = content_filter.finish()
    if tail_content:
        full_content += tail_content
        if last_choice_chunk is not None:
            tail_delta = ChatCompletionDelta(content=tail_content)
            tail_choice = last_choice_chunk.choices[0].model_copy(
                update={"delta": tail_delta, "finish_reason": None}
            )
            tail_chunk = last_choice_chunk.model_copy(
                update={"choices": [tail_choice], "usage": None}
            )
            for hook in hooks:
                await hook.on_model_delta(ctx, state, tail_chunk)

    if is_sleep:
        full_content = full_content.rstrip()

    # Drop tool calls left half-formed by a mid-stream interrupt: missing
    # name (OpenAI Responses only emits it on the final ``done`` event) or
    # invalid JSON args. Empty ``arguments`` is a valid no-arg call.
    tc_list: list[ToolCall] = []
    for i in sorted(tool_calls_buffer):
        buf = tool_calls_buffer[i]
        fn_name = buf["function"]["name"]
        fn_args = buf["function"]["arguments"]
        if not fn_name:
            logger.warning(
                "drop_partial_tool_call_no_name agent={} idx={} args_prefix={!r}",
                agent_name,
                i,
                fn_args[:80],
            )
            continue
        if fn_args:
            try:
                json.loads(fn_args)
            except (json.JSONDecodeError, ValueError):
                logger.warning(
                    "drop_partial_tool_call_bad_json agent={} idx={} name={} args_prefix={!r}",
                    agent_name,
                    i,
                    fn_name,
                    fn_args[:80],
                )
                continue
        tc_list.append(ToolCall(**buf))
    # Me attach usage to `extra` immediately so `wrap_model_call` hooks
    # (e.g. OtelHook) can read it from the returned message inside the
    # chain.  The run loop re-asserts the same mapping — that
    # assignment is now idempotent but kept for clarity and to cover the
    # rare case of a hook replacing `assistant_msg` wholesale.
    extra: dict | None = {"lifecycle": SLEEP_LIFECYCLE} if is_sleep else None
    if last_usage is not None:
        model_id = state.metadata.get("effective_model") or primary_label
        extra = {**(extra or {}), "usage": usage_to_dict(last_usage, model_id)}
    if reasoning_items:
        # Into ``extra`` because that column is persisted and the field is
        # not: history is reloaded from the database at the start of every
        # turn, so an in-memory-only item would survive the turn that made
        # it and vanish before the next one — taking the cached prefix with
        # it, since the replayed turn then differs from the one the model
        # produced.
        extra = {
            **(extra or {}),
            "reasoning_items": [
                item.model_dump(exclude_none=True) for item in reasoning_items
            ],
        }

    msg = AssistantMessage(
        content=full_content or None,
        reasoning_content=reasoning or None,
        reasoning_items=reasoning_items or None,
        tool_calls=tc_list or None,
        agent_id=agent_id,
        agent_name=agent_name,
        extra=extra,
    )
    return msg, last_usage
