"""Tests for the shell + process continuation contract."""

from __future__ import annotations

import asyncio
import re
import sys

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.state import AgentState
from app.agent.tools.builtin.process import (
    _processes,
    process_tool,
    stop_all_processes,
)
from app.agent.tools.builtin.shell import shell_tool


def _process_id(result: str) -> str:
    match = re.search(r"\bproc_[0-9a-f]{10}\b", result)
    assert match is not None
    return match.group(0)


@pytest.fixture(autouse=True)
async def clear_processes():
    yield
    for tracked in list(_processes.values()):
        await tracked.terminate()
    _processes.clear()


@pytest.fixture
def process_sandbox(tmp_path):
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            session_id="process-test",
            denied_roots=[],
            denied_patterns=[],
            load_shell_profile=False,
        )
    )
    yield tmp_path
    _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_shell_yields_process_and_activates_continuation(process_sandbox):
    state = AgentState(messages=[])
    result = await shell_tool.arun(
        command=f"{sys.executable} -c \"import time; print('ready', flush=True); time.sleep(30)\"",
        yield_time_ms=250,
        timeout_seconds=60,
        _injected={"_state": state, "tool_call_id": "call-shell"},
    )

    process_id = _process_id(result)
    assert process_id in _processes
    assert "ready" in result
    assert "process" in state.metadata["activated_deferred_tools"]
    metadata = state.metadata["_tool_result_metadata"]["call-shell"]
    assert metadata["process_id"] == process_id
    assert metadata["artifact"]


@pytest.mark.asyncio
async def test_process_poll_returns_only_new_output(process_sandbox):
    result = await shell_tool.arun(
        command="printf 'first\\n'; sleep 0.5; printf 'second\\n'; sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    process_id = _process_id(result)
    assert "first" in result

    await _processes[process_id].wait_for_activity(2)
    first_poll = await process_tool.arun(action="poll", process_id=process_id)
    second_poll = await process_tool.arun(action="poll", process_id=process_id)

    assert "second" in first_poll
    assert "first" not in first_poll
    assert "second" not in second_poll
    assert "No new output" in second_poll


@pytest.mark.asyncio
async def test_process_wait_finishes_and_removes_registry_entry(process_sandbox):
    result = await shell_tool.arun(
        command="sleep 0.4; printf 'done\\n'",
        yield_time_ms=250,
        timeout_seconds=10,
    )
    process_id = _process_id(result)

    waited = await process_tool.arun(
        action="wait", process_id=process_id, wait_seconds=5
    )

    assert "Succeeded" in waited
    assert "done" in waited
    assert process_id not in _processes


@pytest.mark.asyncio
async def test_process_wait_ignores_progress_until_timeout_without_replay(
    process_sandbox,
):
    result = await shell_tool.arun(
        command="sleep 0.4; printf 'progress\\n'; sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    process_id = _process_id(result)

    started = asyncio.get_running_loop().time()
    waited = await process_tool.arun(
        action="wait", process_id=process_id, wait_seconds=1
    )
    elapsed = asyncio.get_running_loop().time() - started
    polled = await process_tool.arun(action="poll", process_id=process_id)

    assert elapsed >= 0.8
    assert "progress" in waited
    assert "Running" in waited
    assert "progress" not in polled
    assert process_id in _processes


@pytest.mark.asyncio
async def test_final_poll_joins_stdout_reader_before_removal(process_sandbox):
    result = await shell_tool.arun(
        command="sleep 0.35; printf 'final-byte\\n'",
        yield_time_ms=250,
        timeout_seconds=10,
    )
    process_id = _process_id(result)
    await _processes[process_id].proc.wait()

    final = await process_tool.arun(action="poll", process_id=process_id)

    assert "final-byte" in final
    assert process_id not in _processes


@pytest.mark.asyncio
async def test_process_terminate_stops_and_removes(process_sandbox):
    result = await shell_tool.arun(
        command="sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    process_id = _process_id(result)

    stopped = await process_tool.arun(action="terminate", process_id=process_id)

    assert "process_id" in stopped
    assert process_id not in _processes


@pytest.mark.asyncio
async def test_shutdown_stops_all_processes_and_clears_registry(process_sandbox):
    first = await shell_tool.arun(
        command="sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    second = await shell_tool.arun(
        command="sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    tracked = [_processes[_process_id(first)], _processes[_process_id(second)]]

    await stop_all_processes()

    assert not _processes
    assert all(not item.running for item in tracked)


@pytest.mark.asyncio
async def test_process_unknown_and_list(process_sandbox):
    assert "not found" in (
        await process_tool.arun(action="poll", process_id="proc_0000000000")
    )
    assert "No tracked" in await process_tool.arun(action="list")


@pytest.mark.asyncio
async def test_process_registry_is_isolated_by_session(process_sandbox):
    result = await shell_tool.arun(
        command="sleep 30",
        yield_time_ms=250,
        timeout_seconds=60,
    )
    process_id = _process_id(result)

    other = set_sandbox(
        SandboxConfig(
            workspace=str(process_sandbox),
            session_id="another-session",
            denied_roots=[],
            denied_patterns=[],
        )
    )
    try:
        assert "No tracked" in await process_tool.arun(action="list")
        assert "not found" in await process_tool.arun(
            action="poll", process_id=process_id
        )
    finally:
        _sandbox_ctx.reset(other)
