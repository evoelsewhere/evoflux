"""Regression coverage for Coding graph-first telemetry."""

from __future__ import annotations

from app.agent.code_query_observation import (
    CodeQueryObservation,
    publish_code_query_observation,
)
from app.agent.hooks.code_navigation_telemetry import (
    CodeNavigationTelemetryHook,
)
from app.agent.schemas.chat import FunctionCall, ToolCall
from app.agent.state import AgentState, RunContext
from app.core.metrics import REGISTRY


def _ctx() -> RunContext:
    return RunContext(session_id="session", run_id="run", agent_name="coder")


def _call(name: str, arguments: str = "{}") -> ToolCall:
    return ToolCall(
        id=f"call-{name}", function=FunctionCall(name=name, arguments=arguments)
    )


def _counter(metric_name: str, **labels: str) -> float:
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return 0.0


async def _ok_handler(_ctx, _state, _tool_call) -> str:
    return "ok"


async def test_graph_first_strategy_is_counted_once_per_run() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = AgentState(messages=[])
    before = _counter("EVOFLUX_code_navigation_turns_total", strategy="graph_first")

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(ctx, state, _call("code_query"), _ok_handler)
    await hook.wrap_tool_call(ctx, state, _call("grep"), _ok_handler)

    after = _counter("EVOFLUX_code_navigation_turns_total", strategy="graph_first")
    assert after - before == 1


async def test_source_read_before_graph_is_counted_as_fallback_first() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = AgentState(messages=[])
    before = _counter("EVOFLUX_code_navigation_turns_total", strategy="fallback_first")

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(
        ctx,
        state,
        _call("read", '{"path":"app/service.py"}'),
        _ok_handler,
    )
    await hook.wrap_tool_call(ctx, state, _call("code_query"), _ok_handler)

    after = _counter("EVOFLUX_code_navigation_turns_total", strategy="fallback_first")
    assert after - before == 1


async def test_graph_query_records_structured_observation() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = AgentState(messages=[])
    query_before = _counter(
        "EVOFLUX_code_graph_queries_total", tool="code_query", status="ok"
    )
    reads_before = _counter(
        "EVOFLUX_code_graph_estimated_file_reads_saved_total", tool="code_query"
    )

    async def handler(_ctx, _state, _tool_call) -> str:
        publish_code_query_observation(
            CodeQueryObservation(
                strategy="graph+overlay",
                freshness="fresh",
                cache_hit=False,
                file_reads=2,
                source_tokens=1000,
                result_tokens=200,
            )
        )
        return "rendered output whose wording is irrelevant to metrics"

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(ctx, state, _call("code_query"), handler)

    assert (
        _counter("EVOFLUX_code_graph_queries_total", tool="code_query", status="ok")
        - query_before
        == 1
    )
    assert (
        _counter(
            "EVOFLUX_code_graph_estimated_file_reads_saved_total",
            tool="code_query",
        )
        - reads_before
        == 2
    )
    duration_count = _counter(
        "EVOFLUX_code_graph_query_duration_seconds_count", tool="code_query"
    )
    assert duration_count >= 1
