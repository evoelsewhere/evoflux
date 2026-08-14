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
from app.services.stream_envelope import AnyStreamEvent, StreamEnvelope

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
        self._total_thoughts: int | None = None
        self._total_tool_use: int | None = None
        self._usage_count = 0
        self._used_models: set[str] = set()
        self._current_model: str | None = None

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

    async def after_model(
        self, ctx: "RunContext", state: "AgentState", response: "AssistantMessage"
    ) -> None:
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
                    thoughts_tokens=getattr(u, "thoughts_tokens", None),
                    tool_use_tokens=getattr(u, "tool_use_tokens", None),
                    metadata=metadata,
                )
            )
            # Me accumulate for turn-total summary
            self._total_prompt += pt
            self._total_completion += ct
            cached = getattr(u, "cached_tokens", None)
            if cached is not None:
                self._total_cached = (self._total_cached or 0) + cached
            thoughts = getattr(u, "thoughts_tokens", None)
            if thoughts is not None:
                self._total_thoughts = (self._total_thoughts or 0) + thoughts
            tool_use = getattr(u, "tool_use_tokens", None)
            if tool_use is not None:
                self._total_tool_use = (self._total_tool_use or 0) + tool_use
            self._usage_count += 1

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
        if "command" in args_dict:
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
        # Me emit turn-total usage summary when multiple model calls were made
        if self._usage_count > 1 and (self._total_prompt or self._total_completion):
            await self._push(
                UsageEvent(
                    prompt_tokens=self._total_prompt,
                    completion_tokens=self._total_completion,
                    total_tokens=self._total_prompt + self._total_completion,
                    cached_tokens=self._total_cached,
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
        self._total_thoughts = None
        self._total_tool_use = None
        self._usage_count = 0
        self._used_models = set()
        self._current_model = None
