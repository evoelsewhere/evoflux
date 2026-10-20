"""Tests for shell foreground/background execution and the process registry."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

from app.agent import background_tasks
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


class _FakeTeam:
    """Records what the lead would be told, in order."""

    def __init__(self) -> None:
        self.notices: list[tuple[str, dict]] = []
        self.arrived = asyncio.Event()

    async def deliver_background_task_event(self, content: str, event: dict) -> None:
        self.notices.append((content, event))
        self.arrived.set()

    async def next_notice(self, timeout: float = 5.0) -> tuple[str, dict]:
        await asyncio.wait_for(self.arrived.wait(), timeout=timeout)
        self.arrived.clear()
        return self.notices[-1]


@pytest.fixture(autouse=True)
async def clear_processes():
    background_tasks.reset_task_notice_budget()
    yield
    for tracked in list(_processes.values()):
        await tracked.terminate()
    _processes.clear()


@pytest.fixture
def team(monkeypatch) -> _FakeTeam:
    fake = _FakeTeam()
    monkeypatch.setattr(
        "app.services.team_manager.find_team_for_session",
        lambda session_id: fake if session_id == "process-test" else None,
    )
    return fake


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


# ── Foreground ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_foreground_command_is_waited_for_not_yielded(process_sandbox, team):
    state = AgentState(messages=[])
    result = await shell_tool.arun(
        command="sleep 1.2; printf 'done\\n'",
        timeout_seconds=30,
        _injected={"_state": state, "tool_call_id": "call-fg"},
    )

    assert "Succeeded" in result
    assert "done" in result
    assert not _processes
    assert not team.notices
    assert state.metadata["_tool_result_metadata"]["call-fg"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_foreground_command_is_killed_at_its_timeout(process_sandbox, team):
    result = await shell_tool.arun(
        command=f'{Path(sys.executable).as_posix()} -c "import time; time.sleep(30)"',
        timeout_seconds=1,
    )

    assert "Timed out" in result
    assert not _processes
    assert not team.notices


@pytest.mark.asyncio
async def test_cancelling_a_foreground_command_leaves_no_process(process_sandbox):
    task = asyncio.create_task(shell_tool.arun(command="sleep 30", timeout_seconds=60))
    await asyncio.sleep(0.6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── Background ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_background_returns_at_once_and_never_asks_to_poll(process_sandbox, team):
    state = AgentState(messages=[])
    result = await shell_tool.arun(
        command="sleep 30",
        background=True,
        timeout_seconds=60,
        _injected={"_state": state, "tool_call_id": "call-bg"},
    )

    process_id = _process_id(result)
    assert process_id in _processes
    assert "[Started in background]" in result
    assert "notified" in result
    assert "poll" in result.lower() and "do not poll" in result.lower()
    metadata = state.metadata["_tool_result_metadata"]["call-bg"]
    assert metadata["process_id"] == process_id
    assert metadata["status"] == "running"


@pytest.mark.asyncio
async def test_background_task_announces_its_exit_with_output(process_sandbox, team):
    result = await shell_tool.arun(
        command="sleep 1.5; printf 'build ok\\n'",
        background=True,
        timeout_seconds=30,
    )
    process_id = _process_id(result)

    content, event = await team.next_notice()

    assert f"Background task {process_id} finished" in content
    assert "Succeeded" in content
    assert "build ok" in content
    assert event["kind"] == "task_event"
    assert event["task_event"] == "exited"
    assert event["process_id"] == process_id
    assert event["status"] == "succeeded"
    assert event["exit_code"] == 0


@pytest.mark.asyncio
async def test_background_failure_is_announced_with_its_exit_code(
    process_sandbox, team
):
    await shell_tool.arun(
        command="sleep 1.5; printf 'boom\\n'; exit 3",
        background=True,
        timeout_seconds=30,
    )

    content, event = await team.next_notice()

    assert "Failed" in content and "exit code 3" in content
    assert "boom" in content
    assert event["status"] == "failed"
    assert event["exit_code"] == 3


@pytest.mark.asyncio
async def test_background_command_that_ends_at_once_is_returned_not_announced(
    process_sandbox, team
):
    result = await shell_tool.arun(
        command="printf 'quick\\n'", background=True, timeout_seconds=30
    )
    await asyncio.sleep(0.3)

    assert "Succeeded" in result and "quick" in result
    assert not _processes
    assert not team.notices


@pytest.mark.asyncio
async def test_notify_on_announces_matching_lines_while_it_keeps_running(
    process_sandbox, team
):
    result = await shell_tool.arun(
        command="sleep 1.3; printf 'compiling\\n'; printf 'listening on 8000\\n'; sleep 30",
        background=True,
        notify_on="listening on \\d+",
        timeout_seconds=60,
    )
    process_id = _process_id(result)
    assert "listening on" in result

    content, event = await team.next_notice()

    assert event["task_event"] == "matched"
    assert event["matched_line"] == "listening on 8000"
    assert "still running" in content
    assert _processes[process_id].running
    assert len(team.notices) == 1


@pytest.mark.asyncio
async def test_matches_are_capped_per_task(process_sandbox, team, monkeypatch):
    monkeypatch.setattr(background_tasks, "_MIN_SECONDS_BETWEEN_MATCHES", 0.0)
    await shell_tool.arun(
        command=(
            "sleep 1.3; for i in 1 2 3 4 5 6 7 8 9 10; do printf 'hit\\n'; done; "
            "sleep 30"
        ),
        background=True,
        notify_on="hit",
        timeout_seconds=60,
    )
    await asyncio.sleep(2.0)

    assert len(team.notices) == background_tasks.MAX_MATCH_NOTICES_PER_TASK


@pytest.mark.asyncio
async def test_stopping_a_task_is_not_announced(process_sandbox, team):
    result = await shell_tool.arun(
        command="sleep 30", background=True, timeout_seconds=60
    )
    process_id = _process_id(result)

    stopped = await process_tool.arun(action="stop", process_id=process_id)
    await asyncio.sleep(0.3)

    assert process_id in stopped
    assert process_id not in _processes
    assert not team.notices


@pytest.mark.asyncio
async def test_shutdown_stops_all_tasks_without_announcing(process_sandbox, team):
    first = await shell_tool.arun(
        command="sleep 30", background=True, timeout_seconds=60
    )
    second = await shell_tool.arun(
        command="sleep 30", background=True, timeout_seconds=60
    )
    tracked = [_processes[_process_id(first)], _processes[_process_id(second)]]

    await stop_all_processes()
    await asyncio.sleep(0.3)

    assert not _processes
    assert all(not item.running for item in tracked)
    assert not team.notices


@pytest.mark.asyncio
async def test_a_background_task_is_killed_at_the_hard_lifetime_and_announced(
    process_sandbox, team, monkeypatch
):
    from importlib import import_module

    process_module = import_module("app.agent.tools.builtin.process")
    monkeypatch.setattr(process_module, "_MAX_PROCESS_LIFETIME_SECONDS", 2)
    result = await shell_tool.arun(
        command=f'{Path(sys.executable).as_posix()} -c "import time; time.sleep(30)"',
        background=True,
        timeout_seconds=600,
    )
    process_id = _process_id(result)
    assert _processes[process_id].timeout_seconds == 2

    content, event = await team.next_notice(timeout=10)

    assert "Timed out" in content
    assert event["status"] == "timed_out"


@pytest.mark.asyncio
async def test_no_notice_when_the_session_has_no_live_team(process_sandbox):
    result = await shell_tool.arun(
        command="sleep 1.2; printf 'x\\n'", background=True, timeout_seconds=30
    )
    process_id = _process_id(result)

    await asyncio.wait_for(_processes[process_id].proc.wait(), timeout=5)
    await asyncio.sleep(0.3)

    assert _processes[process_id].status == "succeeded"


# ── Argument validation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_on_needs_background(process_sandbox):
    result = await shell_tool.arun(command="true", notify_on="x")
    assert result.startswith("Error:") and "background" in result


@pytest.mark.asyncio
async def test_notify_on_must_be_a_valid_regular_expression(process_sandbox):
    result = await shell_tool.arun(
        command="true", background=True, notify_on="(unclosed"
    )
    assert result.startswith("Error:") and "regular expression" in result
    assert not _processes


@pytest.mark.asyncio
async def test_background_needs_a_session(tmp_path):
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            denied_roots=[],
            denied_patterns=[],
            load_shell_profile=False,
        )
    )
    try:
        result = await shell_tool.arun(command="sleep 5", background=True)
    finally:
        _sandbox_ctx.reset(token)
    assert result.startswith("Error:") and "session" in result
    assert not _processes


# ── The process tool ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_output_shows_the_tail_without_consuming_it(
    process_sandbox, team
):
    result = await shell_tool.arun(
        command="printf 'one\\ntwo\\n'; sleep 1.5; printf 'three\\n'; sleep 30",
        background=True,
        timeout_seconds=60,
    )
    process_id = _process_id(result)
    await asyncio.sleep(2.0)

    first = await process_tool.arun(action="output", process_id=process_id)
    second = await process_tool.arun(action="output", process_id=process_id)
    last_one = await process_tool.arun(
        action="output", process_id=process_id, last_lines=1
    )

    assert "[Running]" in first
    for text in (first, second):
        assert "one" in text and "two" in text and "three" in text
    assert "three" in last_one and "one" not in last_one


@pytest.mark.asyncio
async def test_process_has_no_poll_or_wait():
    text = str(
        process_tool.definition["function"]["parameters"]["properties"]["action"]
    )
    assert "poll" not in text and "wait" not in text and "terminate" not in text


@pytest.mark.asyncio
async def test_process_unknown_and_list(process_sandbox):
    assert "not found" in (
        await process_tool.arun(action="output", process_id="proc_0000000000")
    )
    assert "No background tasks" in await process_tool.arun(action="list")


@pytest.mark.asyncio
async def test_process_registry_is_isolated_by_session(process_sandbox, team):
    result = await shell_tool.arun(
        command="sleep 30", background=True, timeout_seconds=60
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
        assert "No background tasks" in await process_tool.arun(action="list")
        assert "not found" in await process_tool.arun(
            action="output", process_id=process_id
        )
    finally:
        _sandbox_ctx.reset(other)
