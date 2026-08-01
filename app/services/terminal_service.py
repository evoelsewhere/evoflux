"""Interactive PTY terminal sessions — the backend for EvoFlux's AI Terminal.

Unlike the one-shot ``!command`` runner (:mod:`app.services.shell_service`),
this manages *persistent pseudo-terminals*: a real login shell on a PTY so
interactive TUIs (vim, htop, less), colors, arrow keys, tab-completion and job
control (Ctrl-C) all work. Output is mirrored to a bounded ring buffer so a
reconnecting client can replay the recent scrollback.

A single chat session may hold **multiple** terminals (tabs), keyed by an
opaque ``terminal_id`` alongside the session id — so every method takes both
(``terminal_id`` defaults to ``"1"``, the primary tab the agent drives).

The shell is spawned with the session's mode-aware cwd and a few ``EVOFLUX_*``
context env vars. Note this is a *real* shell for the human at the keyboard —
the per-command sandbox that cages the agent's ``shell`` tool does not
constrain a user at a live PTY; on a local desktop app (the user's own
machine) that is the accepted model.

Cross-platform: POSIX uses ``os.openpty`` + ``termios``/``fcntl``; Windows
drives ConPTY through ``pywinpty`` — imported lazily when a terminal is
first spawned, so this module imports cleanly everywhere without it.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import struct
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

if sys.platform != "win32":
    # POSIX-only PTY plumbing; the Windows path (ConPTY via pywinpty) uses
    # none of these. Gated so the module imports cleanly on Windows.
    import fcntl
    import termios

#: Bytes of recent output kept per terminal for replay on reconnect.
_SCROLLBACK_CAP = 256 * 1024
#: Read chunk size from the PTY master.
_READ_SIZE = 64 * 1024
#: Kill a shell with no attached client after this many seconds idle.
_IDLE_TIMEOUT_S = 30 * 60
#: The primary terminal a session always has (and the one the agent drives).
DEFAULT_TERMINAL_ID = "1"


def _key(session_id: str, terminal_id: str) -> str:
    return f"{session_id}\x00{terminal_id}"


class _PtyBackend:
    """Platform-specific PTY handle behind a :class:`TerminalSession`.

    The manager owns buffering, broadcast, idle timers and ``run_command``;
    the backend owns the mechanics of reading output in, plus write, resize
    and teardown.
    """

    #: Child shell pid where the platform exposes one (logging only).
    pid: int | None = None

    def start_reading(self, manager: TerminalManager, session: TerminalSession) -> None:
        """Hook the PTY's output into the manager's buffer/broadcast path."""
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def resize(self, rows: int, cols: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class _PosixPty(_PtyBackend):
    """``os.openpty`` master fd + subprocess; read via ``loop.add_reader``."""

    def __init__(self, master_fd: int, proc: subprocess.Popen) -> None:
        self.master_fd = master_fd
        self._proc = proc
        self.pid = proc.pid

    def start_reading(self, manager: TerminalManager, session: TerminalSession) -> None:
        loop = asyncio.get_running_loop()
        loop.add_reader(self.master_fd, manager._on_readable, session)

    def write(self, data: bytes) -> None:
        os.write(self.master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        _set_winsize(self.master_fd, rows, cols)

    def close(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            loop.remove_reader(self.master_fd)
        except (OSError, ValueError):
            pass
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGHUP)
        except (ProcessLookupError, OSError):
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


class _ConPty(_PtyBackend):
    """Windows ConPTY via ``pywinpty``.

    pywinpty offers no asyncio integration, so a daemon thread pumps the
    blocking ``read()`` and forwards chunks into the event loop with
    ``call_soon_threadsafe`` — from there the same buffer/broadcast path as
    POSIX takes over. Written against the pywinpty 3.x low-level API; the
    small 2.x differences (a ``close()`` method, ``length`` first read arg)
    are handled where they diverge.
    """

    def __init__(self, proc: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._proc = proc  # a winpty.PTY; typed Any — pywinpty is Windows-only
        self._loop = loop

    @property
    def pid(self) -> int | None:
        try:
            return self._proc.pid
        except Exception:  # pywinpty raises WinptyError before spawn/after exit
            return None

    def start_reading(self, manager: TerminalManager, session: TerminalSession) -> None:
        threading.Thread(
            target=self._pump,
            args=(manager, session),
            daemon=True,
            name=f"terminal-pump-{session.session_id}-{session.terminal_id}",
        ).start()

    def _pump(self, manager: TerminalManager, session: TerminalSession) -> None:
        while True:
            try:
                # blocking=True — pywinpty 3.x defaults to a NON-blocking
                # read, which would busy-spin this thread.
                chunk = self._proc.read(blocking=True)  # str; blocks till data
            except Exception:
                # Child exit surfaces as EOFError/OSError or pywinpty's own
                # WinptyError (a plain Exception subclass) — all mean EOF.
                break
            if not chunk:
                if not self._proc.isalive():
                    break
                continue
            data = chunk.encode("utf-8", "replace")
            try:
                self._loop.call_soon_threadsafe(manager._handle_data, session, data)
            except RuntimeError:  # loop already closed — nothing left to notify
                return
        try:
            self._loop.call_soon_threadsafe(manager._handle_eof, session)
        except RuntimeError:  # loop already closed
            pass

    def write(self, data: bytes) -> None:
        # pywinpty's write takes str, not bytes. ConPTY / cmd.exe treat CR
        # as Enter; a bare LF often echoes without submitting the line.
        text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\n", "\r")
        self._proc.write(text)

    def resize(self, rows: int, cols: int) -> None:
        self._proc.set_size(cols, rows)

    def close(self) -> None:
        try:
            close = getattr(self._proc, "close", None)
            if close is not None:  # pywinpty 2.x
                close()
                return
            # pywinpty 3.x dropped PTY.close() — terminate the child and
            # cancel pending I/O instead (what ptyprocess.close() does).
            # SIGTERM via os.kill maps to TerminateProcess on Windows.
            if self._proc.isalive():
                pid = self._proc.pid
                if pid:
                    os.kill(pid, signal.SIGTERM)
            self._proc.cancel_io()
        except Exception:  # never let teardown fail session cleanup
            pass


@dataclass
class TerminalSession:
    """One live PTY + its shell process, shared by any attached clients."""

    session_id: str
    terminal_id: str
    backend: _PtyBackend
    cols: int
    rows: int
    buffer: bytearray = field(default_factory=bytearray)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    closed: bool = False
    _idle_handle: asyncio.TimerHandle | None = None


class TerminalManager:
    """Process-wide registry of PTY sessions, keyed by (session, terminal)."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}

    # -- lifecycle ------------------------------------------------------------
    def attach(
        self,
        session_id: str,
        terminal_id: str = DEFAULT_TERMINAL_ID,
        *,
        cwd: str,
        env: dict[str, str] | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> TerminalSession:
        """Return the terminal's live shell, spawning one if needed.

        Reuses an existing, still-running shell (so a reconnecting client
        keeps its scrollback and running processes); respawns if it exited.
        """
        existing = self._sessions.get(_key(session_id, terminal_id))
        if existing is not None and not existing.closed:
            self._cancel_idle_timer(existing)
            return existing
        return self._spawn(
            session_id, terminal_id, cwd=cwd, env=env, cols=cols, rows=rows
        )

    def _spawn(
        self,
        session_id: str,
        terminal_id: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        cols: int,
        rows: int,
    ) -> TerminalSession:
        if sys.platform == "win32":
            return self._spawn_windows(
                session_id, terminal_id, cwd=cwd, env=env, cols=cols, rows=rows
            )
        return self._spawn_posix(
            session_id, terminal_id, cwd=cwd, env=env, cols=cols, rows=rows
        )

    def _spawn_posix(
        self,
        session_id: str,
        terminal_id: str,
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

        child_env = self._child_env(session_id, env)

        def _child_setup() -> None:
            # New session + make the slave our controlling terminal so job
            # control works (Ctrl-C delivers SIGINT to the foreground group).
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        proc = subprocess.Popen(  # noqa: S603 — a deliberate interactive shell
            _shell_argv(shell),
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

        backend = _PosixPty(master_fd, proc)
        session = TerminalSession(
            session_id=session_id,
            terminal_id=terminal_id,
            backend=backend,
            cols=cols,
            rows=rows,
        )
        self._sessions[_key(session_id, terminal_id)] = session
        backend.start_reading(self, session)
        logger.info(
            "terminal_spawned session_id={} terminal_id={} pid={} shell={} cwd={}",
            session_id,
            terminal_id,
            proc.pid,
            shell,
            cwd,
        )
        return session

    def _spawn_windows(
        self,
        session_id: str,
        terminal_id: str,
        *,
        cwd: str,
        env: dict[str, str] | None,
        cols: int,
        rows: int,
    ) -> TerminalSession:
        try:
            from winpty import PTY
        except ImportError as exc:
            raise RuntimeError(
                "terminal on Windows requires the 'pywinpty' package "
                "(pip install pywinpty)"
            ) from exc

        shell = os.environ.get("COMSPEC") or "cmd.exe"
        # Same fallback as POSIX: never let a missing workspace dir keep the
        # terminal from opening.
        if not os.path.isdir(cwd):
            cwd = os.path.expanduser("~")

        proc = PTY(cols, rows)
        proc.spawn(
            shell,
            cwd=cwd,
            # pywinpty's low-level spawn takes the raw CreateProcessW
            # environment string, not a dict.
            env=_env_block(self._child_env(session_id, env)),
        )

        backend = _ConPty(proc, asyncio.get_running_loop())
        session = TerminalSession(
            session_id=session_id,
            terminal_id=terminal_id,
            backend=backend,
            cols=cols,
            rows=rows,
        )
        self._sessions[_key(session_id, terminal_id)] = session
        backend.start_reading(self, session)
        logger.info(
            "terminal_spawned session_id={} terminal_id={} shell={} cwd={}",
            session_id,
            terminal_id,
            shell,
            cwd,
        )
        return session

    @staticmethod
    def _child_env(session_id: str, env: dict[str, str] | None) -> dict[str, str]:
        child_env = os.environ.copy()
        child_env["TERM"] = "xterm-256color"
        child_env["EVOFLUX_SESSION"] = session_id
        if env:
            child_env.update(env)
        return child_env

    # -- io -------------------------------------------------------------------
    def _on_readable(self, session: TerminalSession) -> None:
        """Loop-reader callback (POSIX): drain the PTY, buffer + broadcast."""
        backend = session.backend
        assert isinstance(backend, _PosixPty)  # add_reader is only wired there
        try:
            data = os.read(backend.master_fd, _READ_SIZE)
        except BlockingIOError:
            return
        except OSError:
            data = b""  # child exited / fd gone → EOF
        if not data:
            self._handle_eof(session)
            return
        self._handle_data(session, data)

    def _handle_data(self, session: TerminalSession, data: bytes) -> None:
        """Buffer fresh PTY output and broadcast it to subscribers."""
        session.buffer.extend(data)
        if len(session.buffer) > _SCROLLBACK_CAP:
            del session.buffer[: len(session.buffer) - _SCROLLBACK_CAP]
        for queue in list(session.subscribers):
            _offer(queue, data)

    def write(
        self, session_id: str, data: bytes, *, terminal_id: str = DEFAULT_TERMINAL_ID
    ) -> None:
        session = self._sessions.get(_key(session_id, terminal_id))
        if session is None or session.closed:
            return
        try:
            session.backend.write(data)
        except Exception as exc:  # OSError on POSIX, WinptyError on Windows
            logger.debug(
                "terminal_write_failed session_id={} error={}", session_id, exc
            )

    def resize(
        self,
        session_id: str,
        cols: int,
        rows: int,
        *,
        terminal_id: str = DEFAULT_TERMINAL_ID,
    ) -> None:
        session = self._sessions.get(_key(session_id, terminal_id))
        if session is None or session.closed:
            return
        session.cols, session.rows = cols, rows
        try:
            session.backend.resize(rows, cols)
        except Exception as exc:  # OSError on POSIX, WinptyError on Windows
            logger.debug(
                "terminal_resize_failed session_id={} error={}", session_id, exc
            )

    async def run_command(
        self,
        session_id: str,
        command: str,
        *,
        terminal_id: str = DEFAULT_TERMINAL_ID,
        timeout_s: float = 60.0,
        idle_s: float = 0.6,
    ) -> str:
        """Run *command* in the terminal's LIVE shared shell and return the
        output the user also sees (broadcast to any attached client).

        Capture is idle-based: after sending the command, output is collected
        until the shell goes quiet for *idle_s* (back at a prompt) or the
        *timeout_s* deadline. Best-effort — the returned text is raw terminal
        output (includes the echoed command and the trailing prompt),
        ANSI-stripped. Assumes the shell is at a prompt (not mid-TUI); a
        long-running command returns partial output at timeout.
        """
        session = self._sessions.get(_key(session_id, terminal_id))
        if session is None or session.closed:
            raise RuntimeError("no live terminal for this session")

        queue = self.subscribe(session_id, terminal_id=terminal_id)
        try:
            self.write(
                session_id,
                command.rstrip("\n").encode("utf-8") + b"\n",
                terminal_id=terminal_id,
            )
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
            self.unsubscribe(session_id, queue, terminal_id=terminal_id)

    # -- subscriptions --------------------------------------------------------
    def subscribe(
        self, session_id: str, *, terminal_id: str = DEFAULT_TERMINAL_ID
    ) -> asyncio.Queue:
        session = self._sessions[_key(session_id, terminal_id)]
        self._cancel_idle_timer(session)
        queue: asyncio.Queue = asyncio.Queue()
        session.subscribers.add(queue)
        return queue

    def unsubscribe(
        self,
        session_id: str,
        queue: asyncio.Queue,
        *,
        terminal_id: str = DEFAULT_TERMINAL_ID,
    ) -> None:
        session = self._sessions.get(_key(session_id, terminal_id))
        if session is None:
            return
        session.subscribers.discard(queue)
        if not session.subscribers and not session.closed:
            self._arm_idle_timer(session)

    def snapshot(
        self, session_id: str, terminal_id: str = DEFAULT_TERMINAL_ID
    ) -> bytes:
        session = self._sessions.get(_key(session_id, terminal_id))
        return bytes(session.buffer) if session is not None else b""

    def is_running(
        self, session_id: str, terminal_id: str = DEFAULT_TERMINAL_ID
    ) -> bool:
        session = self._sessions.get(_key(session_id, terminal_id))
        return session is not None and not session.closed

    def list_terminals(self, session_id: str) -> list[str]:
        """Live terminal ids for *session_id* — lets a client restore its tab
        bar after a reload."""
        return sorted(
            s.terminal_id
            for s in self._sessions.values()
            if s.session_id == session_id and not s.closed
        )

    # -- teardown -------------------------------------------------------------
    def _handle_eof(self, session: TerminalSession) -> None:
        if session.closed:
            return
        self._teardown(session)
        for queue in list(session.subscribers):
            _offer(queue, None)  # sentinel: shell exited

    async def close(
        self, session_id: str, terminal_id: str = DEFAULT_TERMINAL_ID
    ) -> None:
        session = self._sessions.get(_key(session_id, terminal_id))
        if session is not None:
            self._teardown(session)
            for queue in list(session.subscribers):
                _offer(queue, None)

    def _teardown(self, session: TerminalSession) -> None:
        session.closed = True
        self._cancel_idle_timer(session)
        session.backend.close()
        self._sessions.pop(_key(session.session_id, session.terminal_id), None)
        logger.info(
            "terminal_closed session_id={} terminal_id={} pid={}",
            session.session_id,
            session.terminal_id,
            session.backend.pid,
        )

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


def _shell_argv(shell: str) -> list[str]:
    """Interactive-shell argv: bash/sh/zsh get ``-i`` to force a prompt."""
    if os.path.basename(shell) in ("bash", "sh", "zsh"):
        return [shell, "-i"]
    return [shell]


def _env_block(env: dict[str, str]) -> str:
    """NUL-joined ``name=value`` environment block — the raw string
    ``CreateProcessW`` (and therefore pywinpty's low-level ``spawn``)
    expects; the same shape pywinpty's own ``PtyProcess`` builds."""
    return "\0".join(f"{key}={value}" for key, value in env.items()) + "\0"


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
