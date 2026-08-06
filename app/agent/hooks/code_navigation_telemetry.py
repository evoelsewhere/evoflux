"""Coding-mode telemetry for symbol-graph navigation efficiency."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from app.agent.code_graph_observation import consume_code_graph_observation
from app.agent.hooks.base import BaseAgentHook
from app.core.metrics import (
    CODE_GRAPH_QUERIES,
    CODE_GRAPH_QUERY_DURATION,
    CODE_GRAPH_RESULT_TOKENS,
    CODE_NAVIGATION_DUPLICATE_CALLS,
    CODE_NAVIGATION_CALLS_PER_TURN,
    CODE_NAVIGATION_TOOL_CALLS,
    CODE_NAVIGATION_TURNS,
    CODE_GRAPH_ROUTING,
    CODE_GRAPH_RESULT_TOKENS_PER_TURN,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext, ToolCallHandler


_GRAPH_CAPABILITY = "code_graph_navigation"
_SOURCE_NAVIGATION_CAPABILITY = "source_navigation"
_WORKSPACE_READ_CAPABILITY = "workspace_read"


@lru_cache(maxsize=1)
def _source_extensions() -> frozenset[str]:
    from app.services.code_graph.parsers.registry import default_registry

    return default_registry().supported_extensions()


def _capabilities_for(state: "AgentState", tool_name: str) -> frozenset[str]:
    by_tool = state.metadata.get("_tool_capabilities") or {}
    values = by_tool.get(tool_name) or ()
    return frozenset(str(value).casefold() for value in values)


def _read_is_source_navigation(
    tool_call: "ToolCall", capabilities: frozenset[str]
) -> bool:
    if _WORKSPACE_READ_CAPABILITY not in capabilities:
        return False
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    path = arguments.get("path")
    return isinstance(path, str) and Path(path).suffix.lower() in _source_extensions()


def _strategy_for(tool_call: "ToolCall", state: "AgentState") -> str | None:
    capabilities = _capabilities_for(state, tool_call.function.name)
    if _GRAPH_CAPABILITY in capabilities:
        return "graph_first"
    if _SOURCE_NAVIGATION_CAPABILITY in capabilities or _read_is_source_navigation(
        tool_call, capabilities
    ):
        return "fallback_first"
    return None


def _call_fingerprint(tool_call: "ToolCall") -> tuple[str, str]:
    """Return a stable identity for semantically identical tool arguments."""
    arguments = tool_call.function.arguments or "{}"
    try:
        parsed_arguments = json.loads(arguments)
        canonical_arguments = json.dumps(
            parsed_arguments, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        canonical_arguments = arguments
    return tool_call.function.name, canonical_arguments


class CodeNavigationTelemetryHook(BaseAgentHook):
    """Measure graph adoption without changing model or tool behavior."""

    def __init__(self) -> None:
        self._first_strategy: str | None = None
        self._seen_calls: set[tuple[str, str]] = set()
        self._graph_calls = 0
        self._fallback_calls = 0
        self._graph_result_tokens = 0

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        self._first_strategy = None
        self._seen_calls.clear()
        self._graph_calls = 0
        self._fallback_calls = 0
        self._graph_result_tokens = 0

    async def after_agent(self, ctx, state, response) -> None:  # noqa: ANN001
        CODE_NAVIGATION_CALLS_PER_TURN.labels(kind="graph").observe(self._graph_calls)
        CODE_NAVIGATION_CALLS_PER_TURN.labels(kind="fallback").observe(
            self._fallback_calls
        )
        CODE_GRAPH_RESULT_TOKENS_PER_TURN.observe(self._graph_result_tokens)

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler: "ToolCallHandler",
    ) -> str:
        strategy = _strategy_for(tool_call, state)
        tool_name = tool_call.function.name
        fingerprint = _call_fingerprint(tool_call)
        if strategy is not None:
            if fingerprint in self._seen_calls:
                CODE_NAVIGATION_DUPLICATE_CALLS.labels(tool=tool_name).inc()

        if strategy is not None:
            if self._first_strategy is None:
                self._first_strategy = strategy
                CODE_NAVIGATION_TURNS.labels(strategy=strategy).inc()
            CODE_NAVIGATION_TOOL_CALLS.labels(tool=tool_name).inc()
            if strategy == "graph_first":
                self._graph_calls += 1
            else:
                self._fallback_calls += 1

        if strategy != "graph_first":
            if strategy is not None:
                self._seen_calls.add(fingerprint)
            return await handler(ctx, state, tool_call)

        consume_code_graph_observation()
        started = time.perf_counter()
        try:
            result = await handler(ctx, state, tool_call)
        except Exception:
            CODE_GRAPH_QUERIES.labels(tool=tool_name, status="error").inc()
            raise
        finally:
            CODE_GRAPH_QUERY_DURATION.labels(tool=tool_name).observe(
                time.perf_counter() - started
            )

        CODE_GRAPH_QUERIES.labels(tool=tool_name, status="ok").inc()
        self._seen_calls.add(fingerprint)
        observation = consume_code_graph_observation()
        result_tokens = (
            observation.result_tokens
            if observation is not None
            else (len(result.encode("utf-8")) + 3) // 4
        )
        CODE_GRAPH_RESULT_TOKENS.labels(tool=tool_name).inc(result_tokens)
        self._graph_result_tokens += result_tokens
        if observation is not None:
            CODE_GRAPH_ROUTING.labels(
                strategy=observation.strategy,
                freshness=observation.freshness,
            ).inc()
        return result
