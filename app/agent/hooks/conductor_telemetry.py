"""Capture privacy-safe model/tool counters for the Conductor control plane."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.agent.hooks.base import BaseAgentHook
from app.conductor.constants.telemetry import (
    MCP_TOOL_PREFIX,
    CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY,
    CONDUCTOR_REQUEST_STATUS_METADATA_KEY,
    CONDUCTOR_REQUEST_TERMINAL_RECORDED_METADATA_KEY,
    PLUGIN_MCP_GRANTS_METADATA_KEY,
    TELEMETRY_ELAPSED_MS_MULTIPLIER,
    TELEMETRY_MAX_LABEL_LENGTH,
    TELEMETRY_TOOL_CATEGORY_RULES,
    TELEMETRY_USD_MICROS_MULTIPLIER,
    TelemetryCollectionLevel,
    TelemetryCostSource,
    TelemetryEventStatus,
    TelemetryEventType,
    TelemetryField,
    TelemetryResourceField,
    TelemetryResourceRelation,
    TelemetryToolCategory,
)
from app.conductor.telemetry import TelemetryOutbox, telemetry_outbox
from app.core.version import VERSION
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
        self._run_started = 0.0

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        del ctx
        self._sequence = 0
        self._run_started = time.monotonic()
        state.metadata[CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY] = []
        state.metadata[CONDUCTOR_REQUEST_STATUS_METADATA_KEY] = (
            TelemetryEventStatus.SUCCESS
        )
        state.metadata[CONDUCTOR_REQUEST_TERMINAL_RECORDED_METADATA_KEY] = False

    async def after_agent(
        self,
        ctx: "RunContext",
        state: "AgentState",
        response: "AssistantMessage",
    ) -> None:
        del response
        self._record_terminal_request(ctx, state)

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        started = time.monotonic()
        try:
            response = await handler(request)
        except asyncio.CancelledError:
            self._promote_request_status(state, TelemetryEventStatus.CANCELLED)
            self._record_terminal_request(ctx, state)
            raise
        except Exception as exc:
            self._promote_request_status(state, TelemetryEventStatus.ERROR)
            self._record(
                ctx,
                state,
                event_type=TelemetryEventType.MODEL_CALL,
                duration_ms=_elapsed_ms(started),
                status=TelemetryEventStatus.ERROR,
                error_category=type(exc).__name__,
                provider=self._provider,
                model=self._model,
            )
            self._record_terminal_request(ctx, state)
            raise

        extra = response.extra or {}
        usage_value = extra.get("usage")
        usage: dict[str, Any] = usage_value if isinstance(usage_value, dict) else {}
        response_model_id = extra.get("model")
        if not isinstance(response_model_id, str):
            response_model_id = None
        response_provider, response_model = _split_model_id(response_model_id)
        self._record(
            ctx,
            state,
            event_type=TelemetryEventType.MODEL_CALL,
            duration_ms=_elapsed_ms(started),
            status=TelemetryEventStatus.SUCCESS,
            provider=response_provider or self._provider,
            model=response_model or self._model,
            response_model=(
                response_model_id[:TELEMETRY_MAX_LABEL_LENGTH]
                if response_model_id
                else None
            ),
            tokens_in=_counter(usage.get("input")),
            tokens_out=_counter(usage.get("output")),
            cache_read_tokens=_counter(usage.get("cache")),
            reasoning_tokens=_counter(usage.get("thoughts")),
            tool_use_tokens=_counter(usage.get("tool_use")),
            estimated_cost_usd_micros=_cost_micros(usage),
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
        resource_refs = _tool_resource_refs(state, tool_call)
        _remember_used_resources(state, resource_refs)
        try:
            result = await handler(ctx, state, tool_call)
        except asyncio.CancelledError:
            self._promote_request_status(state, TelemetryEventStatus.CANCELLED)
            self._record(
                ctx,
                state,
                event_type=TelemetryEventType.TOOL_CALL,
                duration_ms=_elapsed_ms(started),
                status=TelemetryEventStatus.CANCELLED,
                tool_name=tool_name,
                tool_category=_tool_category(tool_name),
                additional_resources=resource_refs,
            )
            self._record_terminal_request(ctx, state)
            raise
        except Exception as exc:
            self._promote_request_status(state, TelemetryEventStatus.ERROR)
            self._record(
                ctx,
                state,
                event_type=TelemetryEventType.TOOL_CALL,
                duration_ms=_elapsed_ms(started),
                status=TelemetryEventStatus.ERROR,
                error_category=type(exc).__name__,
                tool_name=tool_name,
                tool_category=_tool_category(tool_name),
                additional_resources=resource_refs,
            )
            raise
        self._record(
            ctx,
            state,
            event_type=TelemetryEventType.TOOL_CALL,
            duration_ms=_elapsed_ms(started),
            status=TelemetryEventStatus.SUCCESS,
            tool_name=tool_name,
            tool_category=_tool_category(tool_name),
            additional_resources=resource_refs,
        )
        _remember_used_resources(state, resource_refs)
        return result

    async def on_tool_blocked(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        reason: str,
    ) -> None:
        del reason
        tool_name = tool_call.function.name
        resource_refs = _tool_resource_refs(state, tool_call)
        _remember_used_resources(state, resource_refs)
        self._promote_request_status(state, TelemetryEventStatus.BLOCKED)
        self._record(
            ctx,
            state,
            event_type=TelemetryEventType.TOOL_CALL,
            duration_ms=0,
            status=TelemetryEventStatus.BLOCKED,
            tool_name=tool_name,
            tool_category=_tool_category(tool_name),
            additional_resources=resource_refs,
        )

    def _record_terminal_request(
        self,
        ctx: "RunContext",
        state: "AgentState",
    ) -> None:
        if state.metadata.get(CONDUCTOR_REQUEST_TERMINAL_RECORDED_METADATA_KEY):
            return
        status = state.metadata.get(
            CONDUCTOR_REQUEST_STATUS_METADATA_KEY,
            TelemetryEventStatus.SUCCESS,
        )
        if not isinstance(status, TelemetryEventStatus):
            status = TelemetryEventStatus.SUCCESS
        self._record(
            ctx,
            state,
            event_type=TelemetryEventType.REQUEST,
            duration_ms=_elapsed_ms(self._run_started),
            status=status,
        )
        state.metadata[CONDUCTOR_REQUEST_TERMINAL_RECORDED_METADATA_KEY] = True

    @staticmethod
    def _promote_request_status(
        state: "AgentState",
        status: TelemetryEventStatus,
    ) -> None:
        current = state.metadata.get(
            CONDUCTOR_REQUEST_STATUS_METADATA_KEY,
            TelemetryEventStatus.SUCCESS,
        )
        if status == TelemetryEventStatus.ERROR:
            state.metadata[CONDUCTOR_REQUEST_STATUS_METADATA_KEY] = status
        elif (
            status == TelemetryEventStatus.CANCELLED
            and current != TelemetryEventStatus.ERROR
        ):
            state.metadata[CONDUCTOR_REQUEST_STATUS_METADATA_KEY] = status
        elif (
            status == TelemetryEventStatus.BLOCKED
            and current == TelemetryEventStatus.SUCCESS
        ):
            state.metadata[CONDUCTOR_REQUEST_STATUS_METADATA_KEY] = status

    def _record(
        self,
        ctx: "RunContext",
        state: "AgentState",
        *,
        event_type: TelemetryEventType,
        duration_ms: int,
        status: TelemetryEventStatus,
        error_category: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        response_model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        tool_use_tokens: int = 0,
        tool_name: str | None = None,
        tool_category: TelemetryToolCategory | None = None,
        estimated_cost_usd_micros: int | None = None,
        additional_resources: list[dict[str, str]] | None = None,
    ) -> None:
        config = load_runtime_settings().conductor
        if (
            not config.enabled
            or not config.installation_id
            or config.collection_level in {None, TelemetryCollectionLevel.OFF}
        ):
            return
        self._sequence += 1
        resources = _resource_refs_for_state(state, self._agent_name)
        resources.extend(additional_resources or [])
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
                TelemetryField.RESPONSE_MODEL: response_model,
                TelemetryField.TOKENS_IN: tokens_in,
                TelemetryField.TOKENS_OUT: tokens_out,
                TelemetryField.CACHE_READ_TOKENS: cache_read_tokens,
                TelemetryField.REASONING_TOKENS: reasoning_tokens,
                TelemetryField.TOOL_USE_TOKENS: tool_use_tokens,
                TelemetryField.TOOL_NAME: tool_name,
                TelemetryField.TOOL_CATEGORY: tool_category,
                TelemetryField.ESTIMATED_COST_USD_MICROS: estimated_cost_usd_micros,
                TelemetryField.COST_SOURCE: (
                    TelemetryCostSource.EVOFLUX_CATALOG
                    if estimated_cost_usd_micros is not None
                    else None
                ),
                TelemetryField.EVOFLUX_VERSION: VERSION,
                TelemetryField.RESOURCES: _deduplicate_resource_refs(resources),
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


def _cost_micros(usage: dict[str, Any]) -> int | None:
    cost = usage.get("cost")
    estimated = cost.get("estimated_usd") if isinstance(cost, dict) else None
    if isinstance(estimated, bool) or not isinstance(estimated, int | float):
        return None
    return max(0, round(float(estimated) * TELEMETRY_USD_MICROS_MULTIPLIER))


def _resource_refs_for_state(
    state: "AgentState", agent_name: str
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for record in _managed_resources():
        if record.kind == "agent" and record.slug == agent_name and record.version_id:
            references.append(
                _resource_ref(
                    record.resource_id,
                    record.version_id,
                    TelemetryResourceRelation.EXECUTING_AGENT,
                )
            )
    active = state.metadata.get(CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY, [])
    if isinstance(active, list):
        references.extend(item for item in active if isinstance(item, dict))
    return references


def _tool_resource_refs(
    state: "AgentState", tool_call: "ToolCall"
) -> list[dict[str, str]]:
    if tool_call.function.name == "skill":
        reference = _skill_resource_ref(tool_call.function.arguments)
        return [reference] if reference else []

    references: list[dict[str, str]] = []
    grants = state.metadata.get(PLUGIN_MCP_GRANTS_METADATA_KEY, set())
    if not isinstance(grants, (set, list, tuple)):
        return references
    try:
        from app.plugin_platform.registry import get_installation
        from app.plugin_platform.runtime import plugin_mcp_runtime

        for installation_id in grants:
            if not isinstance(installation_id, str):
                continue
            installation = get_installation(installation_id)
            if (
                installation is None
                or installation.managed_by != "conductor"
                or not installation.managed_resource_id
                or not installation.managed_version_id
            ):
                continue
            if any(
                tool.name == tool_call.function.name
                for tool in plugin_mcp_runtime.get_tools_for_installation(
                    installation_id
                )
            ):
                references.append(
                    _resource_ref(
                        installation.managed_resource_id,
                        installation.managed_version_id,
                        TelemetryResourceRelation.PLUGIN_CONTRIBUTED_TOOL,
                        installation_id,
                    )
                )
    except (OSError, ValueError):
        return []
    return references


def _skill_resource_ref(arguments: str) -> dict[str, str] | None:
    try:
        payload = json.loads(arguments)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("action", "load") != "load":
        return None
    skill_name = payload.get("skill_name")
    if not isinstance(skill_name, str) or not skill_name:
        return None
    try:
        from app.agent.tools.builtin.skill import discover_skill_records_runtime

        record = discover_skill_records_runtime().get(skill_name)
        if record and record.source.startswith("plugin:"):
            from app.plugin_platform.registry import get_installation

            installation_id = record.source.removeprefix("plugin:").strip()
            installation = get_installation(installation_id)
            if (
                installation
                and installation.managed_by == "conductor"
                and installation.managed_resource_id
                and installation.managed_version_id
            ):
                return _resource_ref(
                    installation.managed_resource_id,
                    installation.managed_version_id,
                    TelemetryResourceRelation.PLUGIN_CONTRIBUTED_SKILL,
                    installation_id,
                )
    except (OSError, ValueError):
        return None
    for managed in _managed_resources():
        if (
            managed.kind == "skill"
            and managed.slug == skill_name
            and managed.version_id
        ):
            return _resource_ref(
                managed.resource_id,
                managed.version_id,
                TelemetryResourceRelation.ACTIVATED_SKILL,
            )
    return None


def _managed_resources():
    try:
        from app.conductor.managed_state import ManagedResourceStore

        return ManagedResourceStore().load().resources
    except (OSError, ValueError):
        return []


def _resource_ref(
    resource_id: str,
    version_id: str,
    relation: TelemetryResourceRelation,
    plugin_installation_id: str | None = None,
) -> dict[str, str]:
    reference: dict[str, str] = {
        TelemetryResourceField.RESOURCE_ID.value: resource_id,
        TelemetryResourceField.VERSION_ID.value: version_id,
        TelemetryResourceField.RELATION.value: relation.value,
    }
    if plugin_installation_id:
        reference[TelemetryResourceField.PLUGIN_INSTALLATION_ID.value] = (
            plugin_installation_id
        )
    return reference


def _remember_used_resources(
    state: "AgentState", references: list[dict[str, str]]
) -> None:
    active = state.metadata.setdefault(CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY, [])
    if not isinstance(active, list):
        active = []
        state.metadata[CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY] = active
    for reference in references:
        if reference.get(TelemetryResourceField.RELATION) in {
            TelemetryResourceRelation.ACTIVATED_SKILL,
            TelemetryResourceRelation.PLUGIN_CONTRIBUTED_SKILL,
            TelemetryResourceRelation.PLUGIN_CONTRIBUTED_TOOL,
        }:
            active.append(reference)
    state.metadata[CONDUCTOR_ACTIVE_RESOURCE_REFS_METADATA_KEY] = (
        _deduplicate_resource_refs(active)
    )


def _deduplicate_resource_refs(
    references: list[dict[str, str]],
) -> list[dict[str, str]]:
    seen: set[tuple[str | None, str | None, str | None]] = set()
    result: list[dict[str, str]] = []
    for reference in references:
        key = (
            reference.get(TelemetryResourceField.RESOURCE_ID),
            reference.get(TelemetryResourceField.VERSION_ID),
            reference.get(TelemetryResourceField.RELATION),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(reference)
    return result
