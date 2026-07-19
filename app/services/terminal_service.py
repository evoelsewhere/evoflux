"""Interactive PTY terminal sessions — the backend for EvoFlux's AI Terminal.

Unlike the one-shot ``!command`` runner (:mod:`app.services.shell_service`),
this manages a *persistent pseudo-terminal* per chat session: a real login
shell attached to a PTY so interactive TUIs (vim, htop, less), colors, arrow
keys, tab-completion and job control (Ctrl-C) all work. Output is mirrored to
a bounded ring buffer so a reconnecting client can replay the recent
scrollback ("shell reconnected — replaying buffered output").

The shell is spawned with the session's mode-aware cwd (the coding/aim
workspace, or the forge session dir) and a few ``EVOFLUX_*`` context env vars.
Note this is a *real* shell for the human at the keyboard — the per-command
sandbox that cages the agent's ``shell`` tool does not constrain a user at a
live PTY; on a local desktop app (the user's own machine) that is the
accepted model.

Unix-only (``pty``/``termios``/``fcntl``). Windows would need ConPTY.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass, field

from loguru import logger

#: Bytes of recent output kept per session for replay on reconnect.
_SCROLLBACK_CAP = 256 * 1024
#: Read chunk size from the PTY master.
_READ_SIZE = 64 * 1024
#: Kill a shell with no attached client after this many seconds idle.
_IDLE_TIMEOUT_S = 30 * 60


@dataclass
class TerminalSession:
    """One live PTY + its shell process, shared by any attached clients."""

    session_id: str
    master_fd: int
    pid: int
    cols: int
    rows: int
    buffer: bytearray = field(default_factory=bytearray)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    closed: bool = False
    _idle_handle: asyncio.TimerHandle | None = None


class TerminalManager:
    """Process-wide registry of PTY sessions, keyed by chat session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}

    # -- lifecycle ------------------------------------------------------------
    def attach(
        self,
        session_id: str,
        *,
        cwd: str,
        env: dict[str, str] | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> TerminalSession:
        """Return the session's live shell, spawning one if needed.

        Reuses an existing, still-running shell (so a reconnecting client
        keeps its scrollback and running processes); respawns if the previous
        shell exited.
        """
        existing = self._sessions.get(session_id)
        if existing is not None and not existing.closed:
            self._cancel_idle_timer(existing)
            return existing
        return self._spawn(session_id, cwd=cwd, env=env, cols=cols, rows=rows)

    def _spawn(
        self,
        session_id: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        cols: int,
        rows: int,
    ) -> TerminalSession:
        shell = os.environ.get("SHELL") or "/bin/bash"
        # A missing cwd would make the shell spawn raise — fall back to $HOME
        # so a terminal always opens even if the workspace dir isn't there yet.
        if not os.path.isdir(cwd):
            cwd = os.path.expanduser("~")
        master_fd, slave_fd = os.openpty()
        _set_winsize(master_fd, rows, cols)

        child_env = os.environ.copy()
        child_env["TERM"] = "xterm-256color"
        child_env["EVOFLUX_SESSION"] = session_id
        if env:
            child_env.update(env)

        def _child_setup() -> None:
            # New session + make the slave our controlling terminal so job
            # control works (Ctrl-C delivers SIGINT to the foreground group).
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        argv = [shell, "-i"] if os.path.basename(shell) in ("bash", "sh", "zsh") else [shell]
        proc = subprocess.Popen(  # noqa: S603 — a deliberate interactive shell
            argv,
            preexec_fn=_child_setup,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=child_env,
            close_fds=True,
        )
        os.close(slave_fd)  # the child holds its own dup; parent only needs master
        os.set_blocking(master_fd, False)

        session = TerminalSession(
            session_id=session_id,
            master_fd=master_fd,
            pid=proc.pid,
            cols=cols,
            rows=rows,
        )
        self._sessions[session_id] = session

        loop = asyncio.get_running_loop()
        loop.add_reader(master_fd, self._on_readable, session)
        logger.info(
            "terminal_spawned session_id={} pid={} shell={} cwd={}",
            session_id,
            proc.pid,
            shell,
            cwd,
        )
        return session

    # -- io -------------------------------------------------------------------
    def _on_readable(self, session: TerminalSession) -> None:
        """Loop-reader callback: drain the PTY, buffer + broadcast, handle EOF."""
        try:
            data = os.read(session.master_fd, _READ_SIZE)
        except BlockingIOError:
            return
        except OSError:
            data = b""  # child exited / fd gone → EOF
        if not data:
            self._handle_eof(session)
            return
        session.buffer.extend(data)
        if len(session.buffer) > _SCROLLBACK_CAP:
            del session.buffer[: len(session.buffer) - _SCROLLBACK_CAP]
        for queue in list(session.subscribers):
            _offer(queue, data)

    def write(self, session_id: str, data: bytes) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.closed:
            return
        try:
            os.write(session.master_fd, data)
        except OSError as exc:
            logger.debug("terminal_write_failed session_id={} error={}", session_id, exc)

    def resize(self, session_id: str, cols: int, rows: int) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.closed:
            return
        session.cols, session.rows = cols, rows
        _set_winsize(session.master_fd, rows, cols)

    async def run_command(
        self,
        session_id: str,
        command: str,
        *,
        timeout_s: float = 60.0,
        idle_s: float = 0.6,
    ) -> str:
        """Run *command* in the session's LIVE shared shell and return the
        output the user also sees (broadcast to any attached client).

        Capture is idle-based: after sending the command, output is collected
        until the shell goes quiet for *idle_s* (back at a prompt) or the
        *timeout_s* deadline. Best-effort — the returned text is raw terminal
        output (includes the echoed command line and the trailing prompt),
        ANSI-stripped for readability. Assumes the shell is at a prompt (not
        mid-TUI); a long-running command returns partial output at timeout.
        """
        session = self._sessions.get(session_id)
        if session is None or session.closed:
            raise RuntimeError("no live terminal for this session")

        queue = self.subscribe(session_id)
        try:
            self.write(session_id, command.rstrip("\n").encode("utf-8") + b"\n")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout_s
            chunks: list[bytes] = []
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=min(idle_s, remaining)
                    )
                except asyncio.TimeoutError:
                    if chunks:  # quiet after output → command done
                        break
                    continue  # nothing yet → keep waiting until the deadline
                if item is None:  # shell exited
                    break
                chunks.append(item)
            return _strip_ansi(b"".join(chunks).decode("utf-8", "replace"))
        finally:
            self.unsubscribe(session_id, queue)

    # -- subscriptions --------------------------------------------------------
    def subscribe(self, session_id: str) -> asyncio.Queue:
        session = self._sessions[session_id]
        self._cancel_idle_timer(session)
        queue: asyncio.Queue = asyncio.Queue()
        session.subscribers.add(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.subscribers.discard(queue)
        if not session.subscribers and not session.closed:
            self._arm_idle_timer(session)

    def snapshot(self, session_id: str) -> bytes:
        session = self._sessions.get(session_id)
        return bytes(session.buffer) if session is not None else b""

    def is_running(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        return session is not None and not session.closed

    # -- teardown -------------------------------------------------------------
    def _handle_eof(self, session: TerminalSession) -> None:
        if session.closed:
            return
        self._teardown(session)
        for queue in list(session.subscribers):
            _offer(queue, None)  # sentinel: shell exited

    async def close(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            self._teardown(session)
            for queue in list(session.subscribers):
                _offer(queue, None)

    def _teardown(self, session: TerminalSession) -> None:
        session.closed = True
        self._cancel_idle_timer(session)
        loop = asyncio.get_running_loop()
        try:
            loop.remove_reader(session.master_fd)
        except (OSError, ValueError):
            pass
        try:
            os.killpg(os.getpgid(session.pid), signal.SIGHUP)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.close(session.master_fd)
        except OSError:
            pass
        self._sessions.pop(session.session_id, None)
        logger.info("terminal_closed session_id={} pid={}", session.session_id, session.pid)

    def _arm_idle_timer(self, session: TerminalSession) -> None:
        loop = asyncio.get_running_loop()
        session._idle_handle = loop.call_later(
            _IDLE_TIMEOUT_S, lambda: self._teardown(session)
        )

    def _cancel_idle_timer(self, session: TerminalSession) -> None:
        if session._idle_handle is not None:
            session._idle_handle.cancel()
            session._idle_handle = None


#: CSI/OSC/single-char ANSI escapes — stripped from captured output so the
#: agent reads plain text (the live xterm client still gets the raw bytes).
_ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "")


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _offer(queue: asyncio.Queue, item: bytes | None) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:  # pragma: no cover — unbounded queue
        pass


#: Process singleton.
terminal_manager = TerminalManager()
