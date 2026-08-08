"""Regression coverage for Coding graph-first telemetry."""

from __future__ import annotations

from app.agent.code_context_observation import (
    CodeContextObservation,
    publish_code_context_observation,
)
from app.agent.hooks.code_navigation_telemetry import (
    CodeNavigationTelemetryHook,
)
from app.agent.schemas.chat import FunctionCall, ToolCall
from app.agent.state import AgentState, RunContext
from app.core.metrics import REGISTRY


def _ctx() -> RunContext:
    return RunContext(session_id="session", run_id="run", agent_name="coder")


def _state() -> AgentState:
    return AgentState(
        messages=[],
        metadata={
            "_tool_capabilities": {
                "code_context": ("code_context_navigation",),
                "grep": ("source_navigation",),
                "read": ("workspace_read",),
            }
        },
    )


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
    state = _state()
    before = _counter("EVOFLUX_code_navigation_turns_total", strategy="graph_first")

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(ctx, state, _call("code_context"), _ok_handler)
    await hook.wrap_tool_call(ctx, state, _call("grep"), _ok_handler)

    after = _counter("EVOFLUX_code_navigation_turns_total", strategy="graph_first")
    assert after - before == 1


async def test_source_read_before_graph_is_counted_as_fallback_first() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    before = _counter("EVOFLUX_code_navigation_turns_total", strategy="fallback_first")

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(
        ctx,
        state,
        _call("read", '{"path":"app/service.py"}'),
        _ok_handler,
    )
    await hook.wrap_tool_call(ctx, state, _call("code_context"), _ok_handler)

    after = _counter("EVOFLUX_code_navigation_turns_total", strategy="fallback_first")
    assert after - before == 1


async def test_graph_query_records_structured_observation() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    query_before = _counter(
        "EVOFLUX_code_context_queries_total", tool="code_context", status="ok"
    )

    async def handler(_ctx, _state, _tool_call) -> str:
        publish_code_context_observation(
            CodeContextObservation(
                strategy="native-exact-symbol-graph",
                freshness="fresh",
                result_tokens=200,
            )
        )
        return "rendered output whose wording is irrelevant to metrics"

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(ctx, state, _call("code_context"), handler)

    assert (
        _counter("EVOFLUX_code_context_queries_total", tool="code_context", status="ok")
        - query_before
        == 1
    )
    duration_count = _counter(
        "EVOFLUX_code_context_query_duration_seconds_count", tool="code_context"
    )
    assert duration_count >= 1


async def test_telemetry_never_blocks_source_navigation() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    fallback_executed = False

    async def graph_handler(_ctx, _state, _tool_call) -> str:
        publish_code_context_observation(
            CodeContextObservation(
                strategy="native-exact-symbol-graph",
                freshness="fresh",
                result_tokens=100,
            )
        )
        return "complete graph evidence"

    async def fallback_handler(_ctx, _state, _tool_call) -> str:
        nonlocal fallback_executed
        fallback_executed = True
        return "fallback evidence"

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(ctx, state, _call("code_context"), graph_handler)
    result = await hook.wrap_tool_call(
        ctx,
        state,
        _call("read", '{"path":"app/service.py"}'),
        fallback_handler,
    )

    assert fallback_executed is True
    assert result == "fallback evidence"


async def test_distinct_graph_queries_are_all_executed() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    executed_arguments: list[str] = []

    async def handler(_ctx, _state, tool_call) -> str:
        executed_arguments.append(tool_call.function.arguments)
        return "evidence"

    await hook.before_agent(ctx, state)
    first = await hook.wrap_tool_call(
        ctx,
        state,
        _call("code_context", '{"symbol":"authenticate","depth":1}'),
        handler,
    )
    second = await hook.wrap_tool_call(
        ctx,
        state,
        _call("code_context", '{"symbol":"bill_account","depth":1}'),
        handler,
    )

    assert first == "evidence"
    assert second == "evidence"
    assert executed_arguments == [
        '{"symbol":"authenticate","depth":1}',
        '{"symbol":"bill_account","depth":1}',
    ]


async def test_duplicate_graph_query_is_measured_but_not_blocked() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    executions = 0
    duplicate_before = _counter(
        "EVOFLUX_code_navigation_duplicate_calls_total", tool="code_context"
    )

    async def handler(_ctx, _state, _tool_call) -> str:
        nonlocal executions
        executions += 1
        return "evidence"

    await hook.before_agent(ctx, state)
    await hook.wrap_tool_call(
        ctx,
        state,
        _call("code_context", '{"symbol":"authenticate","operation":"impact"}'),
        handler,
    )
    result = await hook.wrap_tool_call(
        ctx,
        state,
        _call("code_context", '{"operation":"impact","symbol":"authenticate"}'),
        handler,
    )

    assert executions == 2
    assert result == "evidence"
    assert (
        _counter("EVOFLUX_code_navigation_duplicate_calls_total", tool="code_context")
        - duplicate_before
        == 1
    )


async def test_failed_graph_query_can_be_retried_with_identical_arguments() -> None:
    hook = CodeNavigationTelemetryHook()
    ctx = _ctx()
    state = _state()
    executions = 0

    async def handler(_ctx, _state, _tool_call) -> str:
        nonlocal executions
        executions += 1
        if executions == 1:
            raise RuntimeError("temporary failure")
        return "recovered evidence"

    call = _call("code_context", '{"symbol":"authenticate"}')
    await hook.before_agent(ctx, state)
    try:
        await hook.wrap_tool_call(ctx, state, call, handler)
    except RuntimeError:
        pass
    result = await hook.wrap_tool_call(ctx, state, call, handler)

    assert executions == 2
    assert result == "recovered evidence"
