"""Interactive PTY terminal manager (app/services/terminal_service.py)."""

from __future__ import annotations

import asyncio
import importlib
import os
import signal
import sys
import threading
import types
from unittest.mock import patch

import pytest

import app.services.terminal_service as ts
from app.services.terminal_service import TerminalManager, _key


async def _drain_until(
    queue: asyncio.Queue, needle: bytes, *, timeout: float = 3.0
) -> bytes:
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
    tm.attach(sid, cwd=str(tmp_path), env={"EVOFLUX_MODE": "work"})
    queue = tm.subscribe(sid)
    await asyncio.sleep(0.2)
    # cmd.exe on Windows does not evaluate bash arithmetic; use a literal.
    marker = b"TERM_OK_12"
    tm.write(
        sid,
        b"echo TERM_OK_12\n" if sys.platform == "win32" else b"echo TERM_OK_$((3*4))\n",
    )
    got = await _drain_until(queue, marker)
    assert marker in got
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
    session = tm._sessions[_key(sid, "1")]
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

    output = await tm.run_command(
        sid,
        "echo AGENT_DROVE_56"
        if sys.platform == "win32"
        else "echo AGENT_DROVE_$((7*8))",
        timeout_s=10,
    )
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
    # Windows ConPTY can take several seconds after ``exit`` before EOF;
    # keep waiting across quiet gaps instead of aborting on the first idle.
    sentinel_seen = False
    deadline = asyncio.get_running_loop().time() + 20.0
    while asyncio.get_running_loop().time() < deadline:
        try:
            chunk = await asyncio.wait_for(queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            if not tm.is_running(sid):
                break
            continue
        if chunk is None:
            sentinel_seen = True
            break
    assert sentinel_seen
    assert not tm.is_running(sid)


@pytest.mark.asyncio
async def test_multiple_terminals_per_session_are_independent(tmp_path):
    tm = TerminalManager()
    sid = "s7"
    tm.attach(sid, terminal_id="1", cwd=str(tmp_path))
    tm.attach(sid, terminal_id="2", cwd=str(tmp_path))
    assert sorted(tm.list_terminals(sid)) == ["1", "2"]

    q2 = tm.subscribe(sid, terminal_id="2")
    await asyncio.sleep(0.2)
    tm.write(sid, b"echo ONLY_ON_TWO\n", terminal_id="2")
    got = await _drain_until(q2, b"ONLY_ON_TWO")
    assert b"ONLY_ON_TWO" in got
    # Tab 1 never saw tab 2's output.
    assert b"ONLY_ON_TWO" not in tm.snapshot(sid, terminal_id="1")

    await tm.close(sid, terminal_id="2")
    assert tm.list_terminals(sid) == ["1"]  # closing one leaves the other
    await tm.close(sid, terminal_id="1")


# ── Windows import gating ─────────────────────────────────────────────────────


def test_module_imports_on_win32_and_attach_raises_clear_error_without_pywinpty():
    """With sys.platform=win32 and no winpty installed, the module must still
    import; attach() then raises an actionable RuntimeError."""
    try:
        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(
                sys.modules,
                {"winpty": None},  # import of winpty → ImportError
            ),
        ):
            reloaded = importlib.reload(ts)
            manager = reloaded.TerminalManager()
            with pytest.raises(RuntimeError, match="pywinpty"):
                manager.attach("s1", cwd="/")
    finally:
        importlib.reload(ts)  # restore the real (POSIX) module for other tests


# ── Windows ConPTY path (fake winpty — no real PTY is spawned) ────────────────


class _FakeConPtyProc:
    """Stand-in for ``winpty.PTY`` recording every interaction."""

    instances: list[_FakeConPtyProc] = []

    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.spawn_calls: list[tuple] = []
        self.writes: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.closed = False
        self.read_gate = threading.Event()
        _FakeConPtyProc.instances.append(self)

    def spawn(self, argv, cwd=None, env=None):
        self.spawn_calls.append((argv, cwd, env))

    def read(self, blocking=False):
        assert blocking is True, (
            "the pump must use a blocking read (3.x default is non-blocking)"
        )
        # Block (like the real blocking read) until the test releases us,
        # then report the child as gone.
        self.read_gate.wait()
        raise EOFError

    def write(self, text):
        assert isinstance(text, str), "pywinpty takes str, not bytes"
        self.writes.append(text)

    def set_size(self, cols, rows):
        self.sizes.append((cols, rows))

    def isalive(self):
        return not self.closed

    def close(self):
        self.closed = True
        self.read_gate.set()  # release the pump thread


@pytest.fixture
def fake_winpty(monkeypatch):
    """Patch in a fake winpty module and pretend to be on Windows."""
    _FakeConPtyProc.instances.clear()
    monkeypatch.setitem(
        sys.modules, "winpty", types.SimpleNamespace(PTY=_FakeConPtyProc)
    )
    monkeypatch.setattr(sys, "platform", "win32")
    return _FakeConPtyProc


async def test_spawn_windows_uses_comspec_and_conpty(
    fake_winpty, monkeypatch, tmp_path
):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", r"C:\bundled\site-packages")

    manager = TerminalManager()
    session = manager.attach(
        "s1", cwd=str(tmp_path), env={"EVOFLUX_MODE": "work"}, cols=100, rows=40
    )

    assert len(fake_winpty.instances) == 1
    proc = fake_winpty.instances[0]
    assert (proc.cols, proc.rows) == (100, 40)
    argv, cwd, env = proc.spawn_calls[0]
    assert argv == r"C:\Windows\System32\cmd.exe"  # no -i on Windows
    assert cwd == str(tmp_path)
    # pywinpty's low-level spawn takes the raw NUL-joined env block.
    env_map = dict(pair.split("=", 1) for pair in env.rstrip("\0").split("\0"))
    assert env.endswith("\0")
    assert env_map["EVOFLUX_SESSION"] == "s1"
    assert env_map["EVOFLUX_MODE"] == "work"
    assert "EVOFLUX_DESKTOP_TOKEN" not in env_map
    assert "PYTHONPATH" not in env_map

    # write() encodes bytes → str and normalizes Enter to CR for ConPTY/cmd.
    manager.write("s1", b"dir\r\n")
    assert proc.writes == ["dir\r"]
    manager.write("s1", b"echo hi\n")
    assert proc.writes[-1] == "echo hi\r"

    # resize() maps to set_size(cols, rows).
    manager.resize("s1", 120, 50)
    assert proc.sizes == [(120, 50)]
    assert (session.cols, session.rows) == (120, 50)

    # EOF from the pump thread flows through the normal teardown path:
    # session closed, deregistered, subscribers get the None sentinel.
    queue = manager.subscribe("s1")
    proc.read_gate.set()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not manager.is_running("s1"):
            break
    assert not manager.is_running("s1")
    assert proc.closed
    assert queue.get_nowait() is None


async def test_spawn_windows_defaults_to_cmd_exe(fake_winpty, monkeypatch, tmp_path):
    monkeypatch.delenv("COMSPEC", raising=False)

    manager = TerminalManager()
    manager.attach("s1", cwd=str(tmp_path))

    proc = fake_winpty.instances[0]
    assert proc.spawn_calls[0][0] == "cmd.exe"
    proc.close()  # release the pump thread


async def test_spawn_windows_missing_cwd_falls_back_to_home(fake_winpty):
    manager = TerminalManager()
    manager.attach("s1", cwd=r"C:\no\such\dir\evoflux-test")

    proc = fake_winpty.instances[0]
    assert proc.spawn_calls[0][1] == os.path.expanduser("~")
    proc.close()  # release the pump thread


class _FakeConPty3Proc:
    """pywinpty 3.x shape: no ``close()``; teardown must go through
    ``os.kill(pid, SIGTERM)`` + ``cancel_io()`` (what ptyprocess does)."""

    instances: list[_FakeConPty3Proc] = []

    def __init__(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.spawn_calls: list[tuple] = []
        self.cancel_io_calls = 0
        self.pid = 4321
        self.read_gate = threading.Event()
        _FakeConPty3Proc.instances.append(self)

    def spawn(self, argv, cwd=None, env=None):
        self.spawn_calls.append((argv, cwd, env))

    def read(self, blocking=False):
        self.read_gate.wait()
        raise EOFError

    def isalive(self):
        return True

    def cancel_io(self):
        self.cancel_io_calls += 1
        self.read_gate.set()  # a real cancel_io unblocks the pending read


async def test_close_windows_pywinpty3_terminates_child(monkeypatch, tmp_path):
    _FakeConPty3Proc.instances.clear()
    monkeypatch.setitem(
        sys.modules, "winpty", types.SimpleNamespace(PTY=_FakeConPty3Proc)
    )
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "cmd.exe")
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    manager = TerminalManager()
    manager.attach("s1", cwd=str(tmp_path))
    await manager.close("s1")

    proc = _FakeConPty3Proc.instances[0]
    assert killed == [(4321, signal.SIGTERM)]
    assert proc.cancel_io_calls == 1
    assert not manager.is_running("s1")


# ── Shared manager logic (stub backend, no real PTY) ───────────────────────────


class _StubBackend(ts._PtyBackend):
    """In-memory backend: records writes/resizes, close() is a counted no-op."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.close_calls = 0

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def resize(self, rows: int, cols: int) -> None:
        self.resizes.append((rows, cols))

    def close(self) -> None:
        self.close_calls += 1


def _make_session(
    manager: TerminalManager,
    session_id: str = "s1",
    terminal_id: str = ts.DEFAULT_TERMINAL_ID,
) -> ts.TerminalSession:
    session = ts.TerminalSession(
        session_id=session_id,
        terminal_id=terminal_id,
        backend=_StubBackend(),
        cols=80,
        rows=24,
    )
    manager._sessions[_key(session_id, terminal_id)] = session
    return session


def test_attach_reuses_live_session():
    manager = TerminalManager()
    session = _make_session(manager)
    assert manager.attach("s1", cwd="/nonexistent-dir") is session


def test_handle_data_buffers_broadcasts_and_caps():
    manager = TerminalManager()
    session = _make_session(manager)
    queue: asyncio.Queue = asyncio.Queue()
    session.subscribers.add(queue)

    payload = b"x" * (ts._SCROLLBACK_CAP + 10)
    manager._handle_data(session, b"hello ")
    manager._handle_data(session, payload)

    assert bytes(session.buffer) == (b"hello " + payload)[-ts._SCROLLBACK_CAP :]
    assert queue.get_nowait() == b"hello "
    assert queue.get_nowait() == payload


def test_write_and_resize_delegate_to_backend():
    manager = TerminalManager()
    session = _make_session(manager)

    manager.write("s1", b"ls\n")
    manager.resize("s1", 120, 40)

    assert session.backend.writes == [b"ls\n"]
    assert session.backend.resizes == [(40, 120)]
    assert (session.cols, session.rows) == (120, 40)


def test_write_and_resize_missing_session_are_noops():
    manager = TerminalManager()
    manager.write("nope", b"x")
    manager.resize("nope", 80, 24)


def test_handle_eof_closes_notifies_and_is_idempotent():
    manager = TerminalManager()
    session = _make_session(manager)
    queue: asyncio.Queue = asyncio.Queue()
    session.subscribers.add(queue)

    manager._handle_eof(session)

    assert session.closed
    assert queue.get_nowait() is None
    assert not manager.is_running("s1")
    assert session.backend.close_calls == 1

    manager._handle_eof(session)  # second EOF must not double-tear-down
    assert session.backend.close_calls == 1


def test_snapshot_and_list_terminals():
    manager = TerminalManager()
    session = _make_session(manager, terminal_id="2")
    session.buffer.extend(b"abc")
    _make_session(manager, session_id="other-session")

    assert manager.snapshot("s1", "2") == b"abc"
    assert manager.snapshot("missing") == b""
    assert manager.list_terminals("s1") == ["2"]


async def test_run_command_collects_output_until_idle():
    manager = TerminalManager()
    session = _make_session(manager)

    async def feed():
        await asyncio.sleep(0.05)
        manager._handle_data(session, b"total 42\r\n")
        # quiet afterwards → the idle window ends the collection

    feeder = asyncio.create_task(feed())
    output = await manager.run_command("s1", "ls", timeout_s=5, idle_s=0.2)
    await feeder

    assert "total 42" in output
    assert session.backend.writes == [b"ls\n"]


async def test_run_command_does_not_treat_input_echo_as_completion():
    manager = TerminalManager()
    session = _make_session(manager)

    async def feed():
        manager._handle_data(session, b"echo delayed\r\n")
        await asyncio.sleep(0.15)  # longer than the collector's idle window
        manager._handle_data(session, b"delayed\r\nprompt> ")

    feeder = asyncio.create_task(feed())
    output = await manager.run_command("s1", "echo delayed", timeout_s=2, idle_s=0.05)
    await feeder

    assert "delayed\nprompt>" in output
    assert session.backend.writes == [b"echo delayed\n"]


@pytest.mark.parametrize(
    ("shell", "argv"),
    [
        ("/bin/bash", ["/bin/bash", "-il"]),
        ("/bin/sh", ["/bin/sh", "-i"]),
        ("/usr/bin/zsh", ["/usr/bin/zsh", "-il"]),
        ("/usr/bin/fish", ["/usr/bin/fish"]),
        ("pwsh", ["pwsh"]),
    ],
)
def test_shell_argv(shell, argv):
    assert ts._shell_argv(shell) == argv


def test_env_block_is_nul_joined_createprocess_format():
    block = ts._env_block({"A": "1", "B": "two"})
    assert block == "A=1\0B=two\0"
    # Round-trip: the block must parse back to the original mapping.
    assert dict(pair.split("=", 1) for pair in block.rstrip("\0").split("\0")) == {
        "A": "1",
        "B": "two",
    }


def test_child_env_scrubs_sidecar_runtime_and_keeps_terminal_context(monkeypatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/bundled/site-packages")
    monkeypatch.setenv("VIRTUAL_ENV", "/bundled/venv")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = TerminalManager._child_env(
        "session-1",
        {"EVOFLUX_MODE": "coding"},
        shell="/bin/zsh",
    )

    assert env["PATH"] == "/usr/bin:/bin"
    assert env["SHELL"] == "/bin/zsh"
    assert env["EVOFLUX_SESSION"] == "session-1"
    assert env["EVOFLUX_MODE"] == "coding"
    assert "EVOFLUX_DESKTOP_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env
