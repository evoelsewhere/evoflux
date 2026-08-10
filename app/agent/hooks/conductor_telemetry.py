"""Capture privacy-safe model/tool counters for the Conductor control plane."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.agent.hooks.base import BaseAgentHook
from app.conductor.constants.telemetry import (
    MCP_TOOL_PREFIX,
    TELEMETRY_ELAPSED_MS_MULTIPLIER,
    TELEMETRY_MAX_LABEL_LENGTH,
    TELEMETRY_TOOL_CATEGORY_RULES,
    TelemetryCollectionLevel,
    TelemetryEventStatus,
    TelemetryEventType,
    TelemetryField,
    TelemetryToolCategory,
)
from app.conductor.telemetry import TelemetryOutbox, telemetry_outbox
from app.core.runtime_settings import load_runtime_settings

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage, ToolCall
    from app.agent.state import AgentState, ModelCallHandler, ModelRequest, RunContext


class ConductorTelemetryHook(BaseAgentHook):
    """Queue only allowlisted counters; never queue conversation or tool content."""

    def __init__(
        self,
        *,
        agent_name: str,
        model_id: str | None,
        outbox: TelemetryOutbox | None = None,
    ) -> None:
        self._agent_name = agent_name
        self._provider, self._model = _split_model_id(model_id)
        self._outbox = outbox or telemetry_outbox
        self._sequence = 0

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        del ctx, state
        self._sequence = 0

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        del state
        started = time.monotonic()
        try:
            response = await handler(request)
        except Exception as exc:
            self._record(
                ctx,
                event_type=TelemetryEventType.MODEL_CALL,
                duration_ms=_elapsed_ms(started),
                status=TelemetryEventStatus.ERROR,
                error_category=type(exc).__name__,
                provider=self._provider,
                model=self._model,
            )
            raise

        extra = response.extra or {}
        usage_value = extra.get("usage")
        usage: dict[str, Any] = usage_value if isinstance(usage_value, dict) else {}
        response_provider, response_model = _split_model_id(
            extra.get("model") if isinstance(extra.get("model"), str) else None
        )
        self._record(
            ctx,
            event_type=TelemetryEventType.MODEL_CALL,
            duration_ms=_elapsed_ms(started),
            status=TelemetryEventStatus.SUCCESS,
            provider=response_provider or self._provider,
            model=response_model or self._model,
            tokens_in=_counter(usage.get("input")),
            tokens_out=_counter(usage.get("output")),
            cache_read_tokens=_counter(usage.get("cache")),
            reasoning_tokens=_counter(usage.get("thoughts")),
            tool_use_tokens=_counter(usage.get("tool_use")),
        )
        return response

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler,
    ) -> str:
        started = time.monotonic()
        tool_name = tool_call.function.name
        try:
            result = await handler(ctx, state, tool_call)
        except Exception as exc:
            self._record(
                ctx,
                event_type=TelemetryEventType.TOOL_CALL,
                duration_ms=_elapsed_ms(started),
                status=TelemetryEventStatus.ERROR,
                error_category=type(exc).__name__,
                tool_name=tool_name,
                tool_category=_tool_category(tool_name),
            )
            raise
        self._record(
            ctx,
            event_type=TelemetryEventType.TOOL_CALL,
            duration_ms=_elapsed_ms(started),
            status=TelemetryEventStatus.SUCCESS,
            tool_name=tool_name,
            tool_category=_tool_category(tool_name),
        )
        return result

    async def on_tool_blocked(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        reason: str,
    ) -> None:
        del state, reason
        tool_name = tool_call.function.name
        self._record(
            ctx,
            event_type=TelemetryEventType.TOOL_CALL,
            duration_ms=0,
            status=TelemetryEventStatus.BLOCKED,
            tool_name=tool_name,
            tool_category=_tool_category(tool_name),
        )

    def _record(
        self,
        ctx: "RunContext",
        *,
        event_type: TelemetryEventType,
        duration_ms: int,
        status: TelemetryEventStatus,
        error_category: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        tool_use_tokens: int = 0,
        tool_name: str | None = None,
        tool_category: TelemetryToolCategory | None = None,
    ) -> None:
        config = load_runtime_settings().conductor
        if (
            not config.enabled
            or not config.installation_id
            or config.collection_level in {None, TelemetryCollectionLevel.OFF}
        ):
            return
        self._sequence += 1
        self._outbox.enqueue(
            {
                TelemetryField.EVENT_ID: str(uuid.uuid4()),
                TelemetryField.INSTALLATION_ID: config.installation_id,
                TelemetryField.REQUEST_ID: ctx.run_id,
                TelemetryField.SESSION_ID: ctx.session_id,
                TelemetryField.EVENT_TYPE: event_type,
                TelemetryField.SEQUENCE: self._sequence,
                TelemetryField.AGENT_NAME: self._agent_name,
                TelemetryField.REPORTED_AT: datetime.now(UTC).isoformat(),
                TelemetryField.DURATION_MS: duration_ms,
                TelemetryField.STATUS: status,
                TelemetryField.ERROR_CATEGORY: error_category,
                TelemetryField.PROVIDER: provider,
                TelemetryField.MODEL: model,
                TelemetryField.TOKENS_IN: tokens_in,
                TelemetryField.TOKENS_OUT: tokens_out,
                TelemetryField.CACHE_READ_TOKENS: cache_read_tokens,
                TelemetryField.REASONING_TOKENS: reasoning_tokens,
                TelemetryField.TOOL_USE_TOKENS: tool_use_tokens,
                TelemetryField.TOOL_NAME: tool_name,
                TelemetryField.TOOL_CATEGORY: tool_category,
            }
        )


def _split_model_id(model_id: str | None) -> tuple[str | None, str | None]:
    if not model_id:
        return None, None
    if ":" not in model_id:
        return None, model_id[:TELEMETRY_MAX_LABEL_LENGTH]
    provider, _, model = model_id.partition(":")
    return (
        provider[:TELEMETRY_MAX_LABEL_LENGTH] or None,
        model[:TELEMETRY_MAX_LABEL_LENGTH] or None,
    )


def _counter(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return max(0, int(value))


def _elapsed_ms(started: float) -> int:
    return max(
        0,
        round((time.monotonic() - started) * TELEMETRY_ELAPSED_MS_MULTIPLIER),
    )


def _tool_category(name: str) -> TelemetryToolCategory:
    lowered = name.lower()
    if lowered.startswith(MCP_TOOL_PREFIX):
        return TelemetryToolCategory.MCP
    for category, markers in TELEMETRY_TOOL_CATEGORY_RULES:
        if any(marker in lowered for marker in markers):
            return category
    return TelemetryToolCategory.OTHER
