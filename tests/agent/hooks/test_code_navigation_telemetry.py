"""Regression coverage for Coding graph-first telemetry."""

from __future__ import annotations

from app.agent.hooks.code_navigation_telemetry import (
    CodeNavigationTelemetryHook,
    estimate_graph_savings,
)
from app.agent.sandbox import SandboxConfig, set_sandbox
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
    await hook.wrap_tool_call(ctx, state, _call("code_search"), _ok_handler)
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
    await hook.wrap_tool_call(ctx, state, _call("code_graph"), _ok_handler)

    after = _counter("EVOFLUX_code_navigation_turns_total", strategy="fallback_first")
    assert after - before == 1


def test_saving_estimate_uses_unique_graph_result_locations(tmp_path) -> None:
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("x" * 4_000, encoding="utf-8")
    sandbox = SandboxConfig(workspace=str(tmp_path), denied_roots=[])
    token = set_sandbox(sandbox)
    try:
        reads, saved_tokens, result_tokens = estimate_graph_savings(
            "[function] service — src/service.py:1-20\n"
            "[method] run — src/service.py:25-40"
        )
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)

    assert reads == 1
    assert saved_tokens > 900
    assert result_tokens > 0


async def test_graph_query_records_latency_and_saving_counters(tmp_path) -> None:
    source = tmp_path / "service.py"
    source.write_text("x" * 2_000, encoding="utf-8")
    sandbox = SandboxConfig(workspace=str(tmp_path), denied_roots=[])
    token = set_sandbox(sandbox)
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = AgentState(messages=[])
    query_before = _counter(
        "EVOFLUX_code_graph_queries_total", tool="code_search", status="ok"
    )
    reads_before = _counter(
        "EVOFLUX_code_graph_estimated_file_reads_saved_total", tool="code_search"
    )

    async def handler(_ctx, _state, _tool_call) -> str:
        return "[function] service — service.py:1-20"

    try:
        await hook.before_agent(ctx, state)
        await hook.wrap_tool_call(ctx, state, _call("code_search"), handler)
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)

    assert (
        _counter("EVOFLUX_code_graph_queries_total", tool="code_search", status="ok")
        - query_before
        == 1
    )
    assert (
        _counter(
            "EVOFLUX_code_graph_estimated_file_reads_saved_total",
            tool="code_search",
        )
        - reads_before
        == 1
    )
    duration_count = _counter(
        "EVOFLUX_code_graph_query_duration_seconds_count", tool="code_search"
    )
    assert duration_count >= 1
