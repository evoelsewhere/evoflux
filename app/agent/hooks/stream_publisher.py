"""StreamPublisherHook — publishes agent events to the shared stream store.

Reuses the same stream_store.push_event() / mark_done() infrastructure as the
single-agent chat route, so the team SSE stream is identical in shape to the
single-agent stream.  The frontend can subscribe to GET /team/{session_id}/stream
and receive exactly the same event types it already handles.

All events carry an ``agent`` field so the frontend can distinguish who is
speaking when multiple members are active simultaneously.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

from app.agent.hooks.base import BaseAgentHook
from app.agent.lifecycle import SLEEP_LIFECYCLE
from app.agent.tool_id_resolver import ToolIdResolver
from app.services import memory_stream_store as stream_store
from app.agent.schemas.events import (
    MessageEvent,
    ProviderStatusEvent,
    RateLimitEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolEndEvent,
    ToolOutputDeltaEvent,
    ToolStartEvent,
    UsageEvent,
)
from app.agent.schemas.chat import Usage
from app.agent.turn_usage import record_turn_usage
from app.services.stream_envelope import AnyStreamEvent, StreamEnvelope


def _fold_call_usage(previous: Usage | None, current: Usage) -> Usage:
    """Fold one more usage block into the one this model call has so far.

    A usage block on a streaming chunk states the call's totals *to date*,
    not that chunk's share, so the call's usage is the last block — with one
    correction. Providers drop detail lines between blocks: StepFun reports
    ``cached_tokens`` on its first block and omits it from its last, and a
    call that read 4,224 tokens from cache would otherwise be recorded as
    having read none. Every detail line is monotonic within a call, so the
    largest value seen is the one that happened.
    """
    if previous is None:
        return current

    def _widest(name: str) -> int | None:
        values = [
            value
            for value in (getattr(previous, name, None), getattr(current, name, None))
            if isinstance(value, int)
        ]
        return max(values) if values else None

    return current.model_copy(
        update={
            "cached_tokens": _widest("cached_tokens"),
            "cache_write_tokens": _widest("cache_write_tokens"),
            "thoughts_tokens": _widest("thoughts_tokens"),
            "tool_use_tokens": _widest("tool_use_tokens"),
        }
    )


def _catalog_model_id(model: Any, state: "AgentState") -> str | None:
    """The id the catalog prices, not the one the provider says.

    A stream chunk reports the provider's own name for the model — Xiaomi
    sends ``mimo-v2.5``, not ``xiaomi:mimo-v2.5``. Nothing in the catalog
    matches that, so a turn priced from it comes back free, and the main
    call is where nearly all of a turn's tokens are. Borrow the provider
    from the model the agent is running, preferring a fallback's model over
    the configured one when the provider substituted mid-run.
    """
    if not isinstance(model, str) or not model:
        return None
    configured = state.metadata.get("effective_model") or state.metadata.get(
        "active_model"
    )
    provider = configured.partition(":")[0] if isinstance(configured, str) else ""
    if not provider:
        return model
    from app.agent.providers.model_metadata import qualified_model_id

    # A colon is not the signal that an id is already qualified: Bedrock
    # model ids carry one of their own (``us.anthropic.claude-...-v1:0``).
    return qualified_model_id(provider, model)


if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage, ChatCompletionChunk, ToolCall
    from app.agent.state import AgentState, ModelRequest, RunContext, ToolCallHandler

_IMPORTANT_ACTION_TOOLS = frozenset({"merge_code_review", "close_code_review"})


class StreamPublisherHook(BaseAgentHook):
    """Publishes every agent event to the stream store via stream_store.push_event().

    Designed for team members: each member gets its own instance bound to the
    shared lead session_id so all agents write to the same stream key,
    and the frontend receives a unified event feed tagged by agent name.

    ``mark_done`` is intentionally NOT called here — the team coordinator
    (AgentTeam) calls it once after all members are idle, not per-member.

    Args:
        session_id: The stream key suffix (team lead's session_id).
        agent_name: Name of the agent this hook is attached to.
        publish_reasoning: When false, suppress live ``thinking`` events while
            still allowing reasoning content to be assembled and persisted.
    """

    def __init__(
        self,
        session_id: str,
        agent_name: str,
        *,
        publish_reasoning: bool = True,
    ) -> None:
        self._session_id = session_id
        self._agent_name = agent_name
        self._publish_reasoning = publish_reasoning
        self._resolver = ToolIdResolver()
        self._turn_started: float | None = None
        self._model_started: float | None = None
        # Me track per-turn usage for turn-total summary
        self._total_prompt = 0
        self._total_completion = 0
        self._total_cached: int | None = None
        self._total_cache_write: int | None = None
        self._total_thoughts: int | None = None
        self._total_tool_use: int | None = None
        self._usage_count = 0
        self._used_models: set[str] = set()
        self._current_model: str | None = None
        # The in-flight model call's usage, folded across its chunks and
        # recorded once when the call ends. See ``_fold_call_usage``.
        self._pending_usage: Usage | None = None
        self._pending_usage_model: str | None = None

    async def _push(self, event: AnyStreamEvent) -> None:
        """Fire-and-forget push to stream store. Never raises."""
        with contextlib.suppress(Exception):
            await stream_store.push_event(
                self._session_id, StreamEnvelope.from_event(event)
            )

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        self._turn_started = time.monotonic()
        pending = tuple(state.pending_tool_lifecycles)
        state.pending_tool_lifecycles.clear()
        for lifecycle in pending:
            await self._push(
                ToolCallEvent(
                    agent=self._agent_name,
                    tool_call_id=lifecycle.tool_call_id,
                    name=lifecycle.name,
                    metadata=lifecycle.metadata,
                )
            )
            await self._push(
                ToolStartEvent(
                    agent=self._agent_name,
                    tool_call_id=lifecycle.tool_call_id,
                    name=lifecycle.name,
                    arguments=lifecycle.arguments,
                    metadata=lifecycle.metadata,
                )
            )
            await self._push(
                ToolEndEvent(
                    agent=self._agent_name,
                    tool_call_id=lifecycle.tool_call_id,
                    name=lifecycle.name,
                    result=lifecycle.result,
                    metadata=lifecycle.metadata,
                )
            )

    async def before_model(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
    ) -> None:
        self._model_started = time.monotonic()
        self._pending_usage = None
        self._pending_usage_model = None

    async def _flush_call_usage(self) -> None:
        """Record the finished model call's usage, once.

        Called at the end of a model call rather than per chunk, so a
        provider that repeats the call's totals on every chunk is counted
        once. A call that produced no usage block records nothing.
        """
        usage = self._pending_usage
        if usage is None:
            return
        self._pending_usage = None
        model_id = self._pending_usage_model
        self._pending_usage_model = None

        snapshot = await record_turn_usage(usage, phase="main", model_id=model_id)
        # Standalone hook tests and third-party integrations may invoke this
        # hook without the team turn tracker. Preserve the historical
        # main-call-only aggregate as a compatibility fallback.
        if snapshot is not None:
            return
        self._total_prompt += usage.prompt_tokens or 0
        self._total_completion += usage.completion_tokens or 0
        for name, attribute in (
            ("cached_tokens", "_total_cached"),
            ("cache_write_tokens", "_total_cache_write"),
            ("thoughts_tokens", "_total_thoughts"),
            ("tool_use_tokens", "_total_tool_use"),
        ):
            value = getattr(usage, name, None)
            if value is not None:
                setattr(self, attribute, (getattr(self, attribute) or 0) + value)
        self._usage_count += 1

    async def after_model(
        self, ctx: "RunContext", state: "AgentState", response: "AssistantMessage"
    ) -> None:
        await self._flush_call_usage()
        started = (
            self._turn_started
            if self._turn_started is not None
            else self._model_started
        )
        if started is not None:
            response.extra = dict(response.extra or {})
            response.extra["duration_ms"] = round(
                (time.monotonic() - started) * 1000,
                3,
            )
        if response.extra and response.extra.get("lifecycle") == SLEEP_LIFECYCLE:
            await self._push(
                MessageEvent(
                    agent=self._agent_name,
                    text="",
                    metadata={"lifecycle": SLEEP_LIFECYCLE},
                )
            )

    async def on_model_delta(
        self, ctx: "RunContext", state: "AgentState", chunk: "ChatCompletionChunk"
    ) -> None:
        metadata: dict[str, Any] = {}
        model = (
            chunk.model or self._current_model or state.metadata.get("effective_model")
        )
        if isinstance(model, str) and model:
            metadata["model"] = model
        if chunk.usage:
            u = chunk.usage
            pt = u.prompt_tokens or 0
            ct = u.completion_tokens or 0
            metadata = {"agent": self._agent_name, **metadata}
            if chunk.model:
                self._current_model = chunk.model
                self._used_models.add(chunk.model)
                metadata["model"] = chunk.model
            await self._push(
                UsageEvent(
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    total_tokens=u.total_tokens or (pt + ct),
                    cached_tokens=getattr(u, "cached_tokens", None),
                    cache_write_tokens=getattr(u, "cache_write_tokens", None),
                    thoughts_tokens=getattr(u, "thoughts_tokens", None),
                    tool_use_tokens=getattr(u, "tool_use_tokens", None),
                    metadata=metadata,
                )
            )
            # Held, not recorded: the turn total adds one *completed call*,
            # and a provider may state that call's totals on every chunk it
            # sends. StepFun does, so recording here counted a 200K prompt
            # once per chunk and reported a turn in the billions of tokens.
            # ``after_model`` flushes what this fold arrives at.
            self._pending_usage = _fold_call_usage(self._pending_usage, u)
            self._pending_usage_model = _catalog_model_id(model, state)

        if not chunk.choices:
            return

        delta = chunk.choices[0].delta

        if self._publish_reasoning and delta.reasoning_content:
            await self._push(
                ThinkingEvent(
                    agent=self._agent_name,
                    text=delta.reasoning_content,
                    metadata=metadata,
                )
            )

        if delta.content:
            await self._push(
                MessageEvent(
                    agent=self._agent_name, text=delta.content, metadata=metadata
                )
            )

        for tc in delta.tool_calls or []:
            fn_name = tc.function.name if tc.function and tc.function.name else ""
            if not fn_name:
                continue
            tc_id = tc.id or f"{self._agent_name}:{fn_name}:{tc.index}"
            if not self._resolver.register(fn_name, tc_id):
                continue
            await self._push(
                ToolCallEvent(
                    agent=self._agent_name,
                    tool_call_id=tc_id,
                    name=fn_name,
                )
            )

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler: "ToolCallHandler",
    ) -> str:
        import json as _json

        from app.agent.permission import (
            command_always_pattern,
            get_permission_service,
        )

        fn_name = tool_call.function.name if tool_call.function else ""
        tc_id = self._resolver.resolve_start(fn_name, tool_call.id)

        # ── Permission check before tool execution ────────────────────
        # Extract a human-readable "command pattern" from the tool arguments
        # so the permission system can show the user what the agent wants to do.
        try:
            args_dict: dict = (
                _json.loads(tool_call.function.arguments or "{}")
                if tool_call.function
                else {}
            )
        except Exception:
            args_dict = {}

        # Build patterns: use the command/path argument if present, else tool
        # name.  ``always_patterns`` is the broader glob whitelisted when the
        # user replies "always allow" (e.g. "git status -sb" → "git status *").
        patterns: list[str] = []
        always_patterns: list[str] = []
        needs_permission = True
        if fn_name == "computer_app":
            # One entry per action ("type "hi" (2 chars)", "key ctrl+s"), so
            # the user sees what is about to be done to the app, and a
            # refusal only blocks those same actions later in the run.
            from app.agent.tools.builtin.computer_app_tool import (
                permission_patterns,
            )

            described = permission_patterns(args_dict)
            needs_permission = described is not None
            patterns = described or []
            always_patterns = [fn_name]
        elif "command" in args_dict:
            cmd_str = str(args_dict["command"]).strip()
            patterns.append(cmd_str[:200] if cmd_str else fn_name)
            always_patterns.append(
                command_always_pattern(cmd_str) if cmd_str else fn_name
            )
        elif "path" in args_dict or "file_path" in args_dict:
            p = args_dict.get("path") or args_dict.get("file_path") or fn_name
            patterns.append(str(p))
            always_patterns.append(str(p))
        else:
            patterns.append(fn_name)
            always_patterns.append(fn_name)

        # The service owns the whole flow: rule evaluation, mode handling,
        # SSE publishing, and blocking on the user's reply.  A deny/reject
        # raises here and surfaces to the LLM as a tool error result.
        if needs_permission:
            await get_permission_service().ask(
                tool=fn_name,
                patterns=patterns,
                always_patterns=always_patterns,
                metadata={
                    "tool_call_id": tc_id,
                    "agent": self._agent_name,
                    "important": fn_name in _IMPORTANT_ACTION_TOOLS,
                },
                important=fn_name in _IMPORTANT_ACTION_TOOLS,
            )

        # ── Execute tool ──────────────────────────────────────────────
        started = time.monotonic()
        await self._push(
            ToolStartEvent(
                agent=self._agent_name,
                tool_call_id=tc_id,
                name=fn_name,
                arguments=tool_call.function.arguments if tool_call.function else None,
            )
        )

        callbacks: dict[str, object] = state.metadata.setdefault(
            "_tool_output_callbacks", {}
        )
        sequence = 0

        async def _emit_output_delta(text: str) -> None:
            nonlocal sequence
            if not text:
                return
            sequence += 1
            await self._push(
                ToolOutputDeltaEvent(
                    agent=self._agent_name,
                    tool_call_id=tc_id,
                    name=fn_name,
                    text=text,
                    sequence=sequence,
                )
            )

        callbacks[tool_call.id] = _emit_output_delta
        try:
            result = await handler(ctx, state, tool_call)
        finally:
            callbacks.pop(tool_call.id, None)

        duration_ms = round((time.monotonic() - started) * 1000, 3)
        state.metadata.setdefault("_tool_duration_ms", {})[tool_call.id] = duration_ms
        event_metadata = {"duration_ms": duration_ms}
        mcp_app = state.metadata.get("_mcp_apps", {}).get(tool_call.id)
        if mcp_app:
            event_metadata["mcp_app"] = mcp_app
        attachments = state.metadata.get("_tool_attachments", {}).get(tool_call.id)
        if attachments:
            event_metadata["attachments"] = attachments
        result_metadata = state.metadata.get("_tool_result_metadata", {}).get(
            tool_call.id
        )
        if result_metadata:
            event_metadata.update(result_metadata)
        end_tc_id = self._resolver.resolve_end(tool_call.id)
        await self._push(
            ToolEndEvent(
                agent=self._agent_name,
                tool_call_id=end_tc_id,
                name=fn_name,
                result=result or None,
                metadata=event_metadata,
            )
        )
        return result

    async def on_tool_blocked(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        reason: str,
    ) -> None:
        """Close the pending UI action without executing or authorizing it."""
        fn_name = tool_call.function.name if tool_call.function else ""
        tc_id = self._resolver.resolve_start(fn_name, tool_call.id)
        await self._push(
            ToolStartEvent(
                agent=self._agent_name,
                tool_call_id=tc_id,
                name=fn_name,
                arguments=(
                    tool_call.function.arguments if tool_call.function else None
                ),
                metadata={"blocked": True},
            )
        )
        state.metadata.setdefault("_tool_duration_ms", {})[tool_call.id] = 0.0
        await self._push(
            ToolEndEvent(
                agent=self._agent_name,
                tool_call_id=self._resolver.resolve_end(tool_call.id),
                name=fn_name,
                result=reason,
                metadata={"blocked": True, "duration_ms": 0.0},
            )
        )

    async def on_rate_limit(
        self,
        ctx: "RunContext",
        state: "AgentState",
        retry_after: int,
        attempt: int,
        max_attempts: int,
    ) -> None:
        await self._push(
            RateLimitEvent(
                retry_after=retry_after,
                attempt=attempt,
                max_attempts=max_attempts,
            )
        )

    async def on_provider_retry(
        self,
        ctx: "RunContext",
        state: "AgentState",
        model: str,
        attempt: int,
        max_attempts: int,
        delay_seconds: float,
        error_type: str,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        await self._push(
            ProviderStatusEvent(
                agent=self._agent_name,
                status="retrying",
                model=model,
                attempt=attempt,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
                error_type=error_type,
                status_code=status_code,
                retry_after=retry_after,
            )
        )

    async def on_provider_exhausted(
        self,
        ctx: "RunContext",
        state: "AgentState",
        model: str,
        max_attempts: int,
        error_type: str,
        status_code: int | None = None,
    ) -> None:
        await self._push(
            ProviderStatusEvent(
                agent=self._agent_name,
                status="exhausted",
                model=model,
                max_attempts=max_attempts,
                error_type=error_type,
                status_code=status_code,
            )
        )

    async def on_provider_fallback(
        self,
        ctx: "RunContext",
        state: "AgentState",
        primary: str,
        fallback: str,
    ) -> None:
        self._current_model = fallback
        await self._push(
            ProviderStatusEvent(
                agent=self._agent_name,
                status="fallback",
                primary=primary,
                fallback=fallback,
            )
        )

    async def after_agent(
        self, ctx: "RunContext", state: "AgentState", response: "AssistantMessage"
    ) -> None:
        # A call whose ``after_model`` never ran — an abort, or a caller that
        # drives the hook without that boundary — still had usage worth
        # recording.
        await self._flush_call_usage()
        # Me emit turn-total usage summary when multiple model calls were made
        if self._usage_count > 1 and (self._total_prompt or self._total_completion):
            await self._push(
                UsageEvent(
                    prompt_tokens=self._total_prompt,
                    completion_tokens=self._total_completion,
                    total_tokens=self._total_prompt + self._total_completion,
                    cached_tokens=self._total_cached,
                    cache_write_tokens=self._total_cache_write,
                    thoughts_tokens=self._total_thoughts,
                    tool_use_tokens=self._total_tool_use,
                    metadata={
                        "turn_total": True,
                        "agent": self._agent_name,
                        "models": sorted(self._used_models) or None,
                    },
                )
            )
        # Me reset counters so hook can be reused across turns
        self._total_prompt = 0
        self._total_completion = 0
        self._total_cached = None
        self._total_cache_write = None
        self._total_thoughts = None
        self._total_tool_use = None
        self._usage_count = 0
        self._used_models = set()
        self._current_model = None
        self._pending_usage = None
        self._pending_usage_model = None
