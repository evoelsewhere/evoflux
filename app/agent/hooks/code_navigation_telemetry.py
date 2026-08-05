"""Coding-mode telemetry for graph-first navigation and query efficiency."""

from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from app.agent.code_query_observation import consume_code_query_observation
from app.agent.hooks.base import BaseAgentHook
from app.core.metrics import (
    CODE_GRAPH_ESTIMATED_FILE_READS_SAVED,
    CODE_GRAPH_ESTIMATED_TOKENS_SAVED,
    CODE_GRAPH_QUERIES,
    CODE_GRAPH_QUERY_DURATION,
    CODE_GRAPH_RESULT_TOKENS,
    CODE_NAVIGATION_DUPLICATE_CALLS,
    CODE_NAVIGATION_TOOL_CALLS,
    CODE_NAVIGATION_TURNS,
    CODE_QUERY_CACHE,
    CODE_QUERY_ROUTING,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext, ToolCallHandler


CODE_GRAPH_TOOLS = frozenset({"code_query"})
_FALLBACK_NAVIGATION_TOOLS = frozenset(
    {
        "grep",
        "glob",
        "lsp_definition",
        "lsp_references",
    }
)
@lru_cache(maxsize=1)
def _source_extensions() -> frozenset[str]:
    from app.services.code_graph.parsers.registry import default_registry

    return default_registry().supported_extensions()


def _read_is_source_navigation(tool_call: "ToolCall") -> bool:
    if tool_call.function.name != "read":
        return False
    try:
        arguments = json.loads(tool_call.function.arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return False
    path = arguments.get("path")
    return isinstance(path, str) and Path(path).suffix.lower() in _source_extensions()


def _strategy_for(tool_call: "ToolCall") -> str | None:
    name = tool_call.function.name
    if name in CODE_GRAPH_TOOLS:
        return "graph_first"
    if name in _FALLBACK_NAVIGATION_TOOLS or _read_is_source_navigation(tool_call):
        return "fallback_first"
    return None


class CodeNavigationTelemetryHook(BaseAgentHook):
    """Measure graph-first adoption and graph-query efficiency in Coding mode."""

    def __init__(self) -> None:
        self._first_strategy: str | None = None
        self._seen_calls: set[tuple[str, str]] = set()

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        self._first_strategy = None
        self._seen_calls.clear()

    async def wrap_tool_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        tool_call: "ToolCall",
        handler: "ToolCallHandler",
    ) -> str:
        strategy = _strategy_for(tool_call)
        if strategy is not None and self._first_strategy is None:
            self._first_strategy = strategy
            CODE_NAVIGATION_TURNS.labels(strategy=strategy).inc()

        tool_name = tool_call.function.name
        if strategy is not None:
            CODE_NAVIGATION_TOOL_CALLS.labels(tool=tool_name).inc()
            fingerprint = (tool_name, tool_call.function.arguments or "{}")
            if fingerprint in self._seen_calls:
                CODE_NAVIGATION_DUPLICATE_CALLS.labels(tool=tool_name).inc()
            self._seen_calls.add(fingerprint)

        if tool_name not in CODE_GRAPH_TOOLS:
            return await handler(ctx, state, tool_call)

        if tool_name == "code_query":
            consume_code_query_observation()
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
        observation = (
            consume_code_query_observation() if tool_name == "code_query" else None
        )
        result_tokens = (
            observation.result_tokens
            if observation is not None
            else (len(result.encode("utf-8")) + 3) // 4
        )
        CODE_GRAPH_RESULT_TOKENS.labels(tool=tool_name).inc(result_tokens)
        if observation is not None:
            CODE_GRAPH_ESTIMATED_FILE_READS_SAVED.labels(tool=tool_name).inc(
                observation.file_reads
            )
            CODE_GRAPH_ESTIMATED_TOKENS_SAVED.labels(tool=tool_name).inc(
                max(0, observation.source_tokens - observation.result_tokens)
            )
            CODE_QUERY_ROUTING.labels(
                strategy=observation.strategy,
                freshness=observation.freshness,
            ).inc()
            CODE_QUERY_CACHE.labels(
                outcome="hit" if observation.cache_hit else "miss"
            ).inc()
        return result
