"""Coding-mode telemetry for graph-first navigation and query efficiency.

The saving counters are intentionally named as estimates.  Their baseline is
simple and reproducible: each unique source file location returned by a graph
tool represents one otherwise-full file read, and UTF-8 bytes / 4 estimates
tokens.  This is a regression signal, not a claim about provider billing.
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from app.agent.hooks.base import BaseAgentHook
from app.agent.sandbox import get_sandbox
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


CODE_GRAPH_TOOLS = frozenset(
    {"code_query", "code_search", "code_graph", "code_overview", "code_path"}
)
_FALLBACK_NAVIGATION_TOOLS = frozenset(
    {
        "grep",
        "glob",
        "lsp_definition",
        "lsp_references",
        "code_definition",
        "code_references",
    }
)
_LOCATION_RE = re.compile(r"(?P<path>[^\n`():]+?\.[A-Za-z][A-Za-z0-9]*):\d+(?:-\d+)?")
_QUERY_HEADER_RE = re.compile(
    r"strategy=(?P<strategy>[^;]+); freshness=(?P<freshness>[^;]+);"
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


def _clean_location_path(raw: str) -> str:
    value = raw.strip()
    for marker in (" — ", "← ", "→ "):
        if marker in value:
            value = value.rsplit(marker, 1)[-1].strip()
    return value.lstrip("- ")


def _resolve_source_file(raw: str, roots: tuple[Path, ...]) -> Path | None:
    value = _clean_location_path(raw)
    path = Path(value)
    if path.is_absolute():
        try:
            resolved = path.resolve()
        except OSError:
            return None
        if resolved.is_file() and any(
            resolved == root or root in resolved.parents for root in roots
        ):
            return resolved
        return None

    for root in roots:
        variants = [path]
        if path.parts and path.parts[0] == root.name:
            variants.append(Path(*path.parts[1:]))
        for variant in variants:
            try:
                candidate = (root / variant).resolve()
            except OSError:
                continue
            if root not in candidate.parents or not candidate.is_file():
                continue
            return candidate
    return None


def estimate_graph_savings(result: str) -> tuple[int, int, int]:
    """Return ``(file_reads, saved_tokens, result_tokens)`` for one result."""
    result_tokens = (len(result.encode("utf-8")) + 3) // 4
    try:
        sandbox = get_sandbox()
        roots = tuple(
            dict.fromkeys(
                [
                    sandbox.workspace_root.resolve(),
                    *(Path(path).resolve() for path in sandbox.extra_workspace_paths),
                ]
            )
        )
    except (OSError, RuntimeError, ValueError):
        return 0, 0, result_tokens

    files: set[Path] = set()
    for match in _LOCATION_RE.finditer(result):
        source_file = _resolve_source_file(match.group("path"), roots)
        if source_file is not None:
            files.add(source_file)

    source_tokens = 0
    for source_file in files:
        try:
            source_tokens += (source_file.stat().st_size + 3) // 4
        except OSError:
            continue
    return len(files), max(0, source_tokens - result_tokens), result_tokens


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
        file_reads, saved_tokens, result_tokens = estimate_graph_savings(result)
        CODE_GRAPH_RESULT_TOKENS.labels(tool=tool_name).inc(result_tokens)
        CODE_GRAPH_ESTIMATED_FILE_READS_SAVED.labels(tool=tool_name).inc(file_reads)
        CODE_GRAPH_ESTIMATED_TOKENS_SAVED.labels(tool=tool_name).inc(saved_tokens)
        if tool_name == "code_query":
            match = _QUERY_HEADER_RE.search(result)
            if match:
                CODE_QUERY_ROUTING.labels(
                    strategy=match.group("strategy"),
                    freshness=match.group("freshness"),
                ).inc()
            CODE_QUERY_CACHE.labels(
                outcome="hit" if "\n\nCache: hit" in result else "miss"
            ).inc()
        return result
