"""Interactive PTY terminal manager (app/services/terminal_service.py)."""

from __future__ import annotations

import asyncio

import pytest

from app.services.terminal_service import TerminalManager


async def _drain_until(queue: asyncio.Queue, needle: bytes, *, timeout: float = 3.0) -> bytes:
    got = b""
    try:
        while needle not in got:
            chunk = await asyncio.wait_for(queue.get(), timeout=timeout)
            if chunk is None:
                break
            got += chunk
    except asyncio.TimeoutError:
        pass
    return got


@pytest.mark.asyncio
async def test_spawn_run_command_and_capture_output(tmp_path):
    tm = TerminalManager()
    sid = "s1"
    tm.attach(sid, cwd=str(tmp_path), env={"EVOFLUX_MODE": "forge"})
    queue = tm.subscribe(sid)
    await asyncio.sleep(0.2)
    tm.write(sid, b"echo TERM_OK_$((3*4))\n")
    got = await _drain_until(queue, b"TERM_OK_12")
    assert b"TERM_OK_12" in got
    await tm.close(sid)
    assert not tm.is_running(sid)


@pytest.mark.asyncio
async def test_snapshot_replays_scrollback(tmp_path):
    tm = TerminalManager()
    sid = "s2"
    tm.attach(sid, cwd=str(tmp_path))
    queue = tm.subscribe(sid)
    await asyncio.sleep(0.2)
    tm.write(sid, b"echo REPLAY_MARKER\n")
    await _drain_until(queue, b"REPLAY_MARKER")
    assert b"REPLAY_MARKER" in tm.snapshot(sid)
    await tm.close(sid)


@pytest.mark.asyncio
async def test_reattach_reuses_live_shell(tmp_path):
    tm = TerminalManager()
    sid = "s3"
    first = tm.attach(sid, cwd=str(tmp_path))
    second = tm.attach(sid, cwd=str(tmp_path))
    assert first is second  # same live shell, not a respawn
    assert tm.is_running(sid)
    await tm.close(sid)


@pytest.mark.asyncio
async def test_resize_is_safe(tmp_path):
    tm = TerminalManager()
    sid = "s4"
    tm.attach(sid, cwd=str(tmp_path), cols=80, rows=24)
    tm.resize(sid, 120, 40)  # must not raise
    session = tm._sessions[sid]
    assert (session.cols, session.rows) == (120, 40)
    await tm.close(sid)


@pytest.mark.asyncio
async def test_run_command_returns_output_and_is_seen_live(tmp_path):
    """Agent→terminal: run_command executes in the shared shell, returns the
    output to the caller, AND broadcasts it to an attached client (the user)."""
    tm = TerminalManager()
    sid = "s6"
    tm.attach(sid, cwd=str(tmp_path))
    watcher = tm.subscribe(sid)  # stands in for the user's live terminal
    await asyncio.sleep(0.2)

    output = await tm.run_command(sid, "echo AGENT_DROVE_$((7*8))", timeout_s=10)
    assert "AGENT_DROVE_56" in output  # returned to the agent

    # The same output reached the live client too (shared terminal).
    seen = b""
    try:
        while b"AGENT_DROVE_56" not in seen:
            chunk = await asyncio.wait_for(watcher.get(), timeout=1.0)
            if chunk is None:
                break
            seen += chunk
    except asyncio.TimeoutError:
        pass
    assert b"AGENT_DROVE_56" in seen
    await tm.close(sid)


@pytest.mark.asyncio
async def test_run_command_without_session_raises(tmp_path):
    tm = TerminalManager()
    with pytest.raises(RuntimeError):
        await tm.run_command("nope", "echo hi")


@pytest.mark.asyncio
async def test_exit_notifies_subscribers(tmp_path):
    tm = TerminalManager()
    sid = "s5"
    tm.attach(sid, cwd=str(tmp_path))
    queue = tm.subscribe(sid)
    await asyncio.sleep(0.2)
    tm.write(sid, b"exit\n")
    # The shell exiting should push the None sentinel to subscribers.
    sentinel_seen = False
    try:
        for _ in range(200):
            chunk = await asyncio.wait_for(queue.get(), timeout=3.0)
            if chunk is None:
                sentinel_seen = True
                break
    except asyncio.TimeoutError:
        pass
    assert sentinel_seen
    assert not tm.is_running(sid)


def test_terminal_run_tool_is_lead_only_all_modes():
    from app.agent.builtin_prompts import tier_tools
    from app.agent.loader import _default_tool_registry

    registry = _default_tool_registry()
    assert "terminal_run" in registry
    for mode in ("forge", "coding", "aim"):
        assert "terminal_run" in tier_tools(registry, mode=mode, role="lead")
        assert "terminal_run" not in tier_tools(registry, mode=mode, role="member")
