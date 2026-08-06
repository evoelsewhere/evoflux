"""Background shell task tools — non-blocking subprocess management.

Three tools that let the agent run long commands without blocking:

- ``shell_bg_start``  — launch a command in the background; returns a
  ``task_id`` immediately.
- ``shell_bg_status`` — non-blocking poll: running state, exit code, tail.
- ``shell_bg_wait``   — block until the task finishes (with timeout).

These are a friendlier alternative to ``shell(background=True)`` which
returns a PID that is hard for the agent to track across turns.  Task IDs
are stable string handles that survive context compression.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

from loguru import logger
from pydantic import Field

from app.agent.process_sandbox import sandboxed_process_argv
from app.agent.tools.registry import InjectedArg, Tool

# ── Output / timeout constants ────────────────────────────────────────────────

_STATUS_TAIL_LINES = 50  # lines returned by shell_bg_status
_WAIT_TAIL_LINES = 200  # lines returned by shell_bg_wait
_MAX_WAIT_SECONDS = 600  # hard cap on shell_bg_wait timeout (10 min)
_REGISTRY_CAP = 100  # max tasks kept before pruning finished ones


# ── Task record ───────────────────────────────────────────────────────────────


@dataclass
class BgTask:
    """One background subprocess tracked by the registry."""

    task_id: str
    command: str
    workdir: str
    session_id: str | None
    started_at: float  # time.monotonic()
    # _bg is a _BgProcess instance from shell.py (typed Any to avoid circular).
    _bg: Any = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return bool(self._bg and self._bg.alive)

    @property
    def exit_code(self) -> int | None:
        if self._bg is None:
            return None
        return self._bg.proc.returncode

    @property
    def pid(self) -> int | None:
        return self._bg.pid if self._bg else None

    def tail(self, n: int = _STATUS_TAIL_LINES) -> str:
        return self._bg.read_output(last_n=n) if self._bg else ""


# ── Module-level registry ─────────────────────────────────────────────────────

_registry: dict[str, BgTask] = {}


def _new_task_id() -> str:
    return "bg_" + uuid.uuid4().hex[:8]


def _prune_registry() -> None:
    """Remove the oldest completed tasks when the registry hits capacity."""
    if len(_registry) < _REGISTRY_CAP:
        return
    done = sorted(
        ((tid, t) for tid, t in _registry.items() if not t.running),
        key=lambda x: x[1].started_at,
    )
    for tid, _ in done[: max(1, len(done) // 2)]:
        del _registry[tid]


# ── Tool implementations ──────────────────────────────────────────────────────


async def _shell_bg_start(
    command: Annotated[
        str,
        Field(
            description=(
                "Shell command to run in the background. Supports &&, ||, pipes, "
                "$VAR, subshells. The command starts immediately; this tool returns "
                "a task_id without waiting for the command to finish."
            )
        ),
    ],
    workdir: Annotated[
        str | None,
        Field(
            description=(
                "Working directory. Null = session workspace root. "
                "Relative paths resolve inside the session workspace."
            )
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Start a shell command in the background and return a task_id immediately.

    Use this for long-running commands (builds, test suites, servers) where
    you don't want to block the agent.  After calling this tool you can
    continue other work and check progress with shell_bg_status or block
    until done with shell_bg_wait.

    Returns a ``task_id`` string (e.g. ``bg_a1b2c3d4``) that you pass to
    shell_bg_status and shell_bg_wait.
    """
    # Lazy imports from shell.py to avoid circular imports at module level.
    from app.agent.tools.builtin import shell_runtime as _shell_mod
    from app.agent.tools.builtin.shell import (
        _BgProcess,
        _resolve_workdir,
        _scrubbed_env,
    )
    from app.agent.sandbox import get_sandbox
    import subprocess

    sandbox = get_sandbox()

    hit = sandbox.check_command(command)
    if hit is not None:
        resolved, denied = hit
        raise PermissionError(
            f"Sandbox blocked 'shell_bg_start': command touches "
            f"'{resolved}' (denied by '{denied}')."
        )

    cwd = _resolve_workdir(workdir)
    shell_bin = _shell_mod.acceptable()
    argv = _shell_mod.build_argv(
        shell_bin,
        command,
        load_profile=sandbox.load_shell_profile,
    )
    exec_bin, exec_argv = sandboxed_process_argv(
        shell_bin,
        argv,
        sandbox=sandbox,
        cwd=cwd,
    )

    _extra: dict[str, Any] = {}
    if sys.platform == "win32":
        _extra["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        _extra["start_new_session"] = True

    try:
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
            **_extra,
        )
    except NotImplementedError:
        return (
            "[Failed] Background processes require an asyncio ProactorEventLoop "
            "(Windows) or POSIX. Use shell() with a timeout instead."
        )

    bg = _BgProcess(proc, command)
    task_id = _new_task_id()
    session_id = _state.metadata.get("session_id") if _state else None

    _prune_registry()
    _registry[task_id] = BgTask(
        task_id=task_id,
        command=command,
        workdir=str(cwd),
        session_id=session_id,
        started_at=time.monotonic(),
        _bg=bg,
    )

    logger.info(
        "shell_bg_started task_id={} pid={} command={}",
        task_id,
        bg.pid,
        command[:200],
    )

    return (
        f"[Background started]\n"
        f"task_id: {task_id}   pid: {bg.pid}\n"
        f"command: {command}\n"
        f"workdir: {cwd}\n\n"
        f"Check progress : shell_bg_status(task_id='{task_id}')\n"
        f"Wait for result: shell_bg_wait(task_id='{task_id}')"
    )


async def _shell_bg_status(
    task_id: Annotated[
        str,
        Field(description="task_id returned by shell_bg_start."),
    ],
) -> str:
    """Check the status of a background task without blocking.

    Returns the running state, exit code (if finished), and the last 50 lines
    of captured output.  Call this repeatedly to monitor a long-running task.
    """
    task = _registry.get(task_id)
    if task is None:
        return (
            f"[Error] Task '{task_id}' not found.  It may have finished and been "
            f"cleaned up, or the task_id is wrong."
        )

    elapsed = time.monotonic() - task.started_at
    running = task.running
    exit_code = task.exit_code
    tail = task.tail(n=_STATUS_TAIL_LINES)

    status = "running" if running else f"finished  exit_code={exit_code}"
    result = "[Succeeded]" if (not running and exit_code == 0) else ""
    if not running and exit_code != 0:
        result = f"[Failed — exit code {exit_code}]"

    lines = [
        f"task_id={task_id}  status={status}  elapsed={elapsed:.0f}s  pid={task.pid}",
        f"command: {task.command}",
    ]
    if result:
        lines.append(result)
    lines.append("")
    if tail:
        lines.append(f"Last output ({_STATUS_TAIL_LINES} lines max):\n{tail}")
    else:
        lines.append("(no output captured yet)")

    return "\n".join(lines)


async def _shell_bg_wait(
    task_id: Annotated[
        str,
        Field(description="task_id returned by shell_bg_start."),
    ],
    timeout_seconds: Annotated[
        int,
        Field(
            description=(
                "Maximum seconds to wait before returning even if still running. "
                "Default 300 (5 min); max 600 (10 min)."
            )
        ),
    ] = 300,
) -> str:
    """Block until a background task finishes and return its full output.

    If the task is still running after ``timeout_seconds``, returns the
    current output tail with a timeout notice — the task keeps running.
    On success or failure, the task is removed from the registry.
    """
    task = _registry.get(task_id)
    if task is None:
        return f"[Error] Task '{task_id}' not found."

    # Already done — no need to wait
    if not task.running:
        return _format_done(task)

    timeout = float(min(max(1, timeout_seconds), _MAX_WAIT_SECONDS))

    try:
        # _BgProcess.wait() awaits proc.wait() + reader task drain
        await asyncio.wait_for(task._bg.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        tail = task.tail(n=_WAIT_TAIL_LINES)
        return (
            f"[Timeout — still running after {timeout:.0f}s]\n"
            f"task_id={task_id}   pid={task.pid}\n"
            f"command: {task.command}\n\n"
            f"Last output:\n{tail}\n\n"
            f"Use shell_bg_status('{task_id}') to check again."
        )

    return _format_done(task, remove=True)


def _format_done(task: BgTask, *, remove: bool = False) -> str:
    exit_code = task.exit_code
    elapsed = time.monotonic() - task.started_at
    tail = task.tail(n=_WAIT_TAIL_LINES)
    status = "[Succeeded]" if exit_code == 0 else f"[Failed — exit code {exit_code}]"

    if remove:
        _registry.pop(task.task_id, None)

    lines = [
        f"{status}",
        f"task_id={task.task_id}  elapsed={elapsed:.0f}s  pid={task.pid}",
        f"command: {task.command}",
        "",
    ]
    if tail:
        lines.append(tail)
    return "\n".join(lines)


# ── Tool objects ──────────────────────────────────────────────────────────────

shell_bg_start = Tool(
    _shell_bg_start,
    name="shell_bg_start",
    deferred=True,
    deferred_summary="Start a tracked shell command in the background.",
    description=(
        "Start a shell command in the background; returns a task_id immediately "
        "without waiting. Use for builds, test suites, or dev servers."
    ),
)

shell_bg_status = Tool(
    _shell_bg_status,
    name="shell_bg_status",
    description=(
        "Check a background task's status without blocking. "
        "Returns running state, exit code, and last 50 lines of output."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Check a tracked background shell task without blocking.",
)

shell_bg_wait = Tool(
    _shell_bg_wait,
    name="shell_bg_wait",
    deferred=True,
    deferred_summary="Wait for a tracked background shell task and return its output.",
    description=(
        "Block until a background task finishes (with timeout) and return its output. "
        "Cleans up the task on completion."
    ),
)
