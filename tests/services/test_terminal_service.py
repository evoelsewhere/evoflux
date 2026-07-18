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
