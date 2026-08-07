"""Token-bounded shell execution with tracked process continuation."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

from loguru import logger
from pydantic import Field

from app.agent.process_sandbox import sandboxed_process_argv
from app.agent.sandbox import get_sandbox
from app.agent.tools.builtin import shell_runtime as _shell_mod
from app.agent.tools.builtin.process import (
    TrackedProcess,
    _kill_process_group as _kill_process_group,
    activate_process_tool,
    command_process_scope,
    completed_metadata,
    format_completed_process,
    format_running_process,
    register_process,
    stash_result_metadata,
)
from app.agent.tools.registry import InjectedArg, Tool

# ── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT_SECONDS = (
    120  # 2 min default (opencode parity) — test suites and builds routinely
    # exceed 60 s; yielded processes handle longer-running commands.
)
# Compatibility helpers retained for callers/tests that import ``_tail_text``.
_OUTPUT_MAX_LINES = 300
_OUTPUT_MAX_BYTES = 12_000


# ── Helpers ───────────────────────────────────────────────────────────────────

# Environment variables that point at *our* Python runtime (the bundled
# sidecar's site-packages, the daemon's virtualenv, etc.).  Leaking these
# into a user-spawned subprocess is dangerous: another Python interpreter
# the agent invokes — ``pipx`` tools, ``uv tool`` shims, project CLIs
# installed under a different Python version — will find *our* pure-Python
# packages on ``sys.path`` and then crash when it tries to load a
# native extension built for our Python ABI (e.g. ``pydantic_core``
# compiled for cpython-3.14 vs. the tool's cpython-3.12).
_PYTHON_ENV_LEAK_KEYS: frozenset[str] = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONEXECUTABLE",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        # uv injects these when it activates a tool venv; they steer
        # uv invocations to *our* cache/python and break user tools.
        "UV_PYTHON",
        "UV_PROJECT_ENVIRONMENT",
    }
)

_SAFE_SHELL_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TERM",
        "COLORTERM",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "NO_COLOR",
        "FORCE_COLOR",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        # Windows process discovery/runtime. Names are matched
        # case-insensitively on win32 (hosts often expose SYSTEMROOT).
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
    }
)
_SAFE_SHELL_ENV_KEYS_UPPER: frozenset[str] = frozenset(
    key.upper() for key in _SAFE_SHELL_ENV_KEYS
)
_PYTHON_ENV_LEAK_KEYS_UPPER: frozenset[str] = frozenset(
    key.upper() for key in _PYTHON_ENV_LEAK_KEYS
)


def _scrubbed_env(*, inherit: bool = False) -> dict[str, str]:
    """Return the environment exposed to an agent shell.

    The secure default is an allowlist of process-discovery and locale values,
    which keeps provider API keys, OAuth tokens, SSH agent sockets and other
    host credentials out of model-controlled commands. Users may explicitly
    opt into full host inheritance in Sandbox settings. EvoFlux internal
    values are never inherited. Python/uv activation variables are removed
    only in the secure default; an explicit inheritance opt-in preserves the
    active Coding environment as advertised.
    """
    # Windows env names are case-insensitive; match allow/block lists that way
    # so ``SYSTEMROOT`` (common) is not dropped while ``SystemRoot`` is listed.
    if sys.platform == "win32":
        internal_upper = {
            key.upper() for key in os.environ if key.upper().startswith("EVOFLUX_")
        }
        if inherit:
            return {
                key: value
                for key, value in os.environ.items()
                if key.upper() not in internal_upper
            }
        blocked_upper = {*_PYTHON_ENV_LEAK_KEYS_UPPER, *internal_upper}
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() not in blocked_upper
            and (
                key.upper() in _SAFE_SHELL_ENV_KEYS_UPPER
                or key.upper().startswith("LC_")
            )
        }

    internal = {key for key in os.environ if key.startswith("EVOFLUX_")}
    if inherit:
        return {key: value for key, value in os.environ.items() if key not in internal}
    blocked = {*_PYTHON_ENV_LEAK_KEYS, *internal}
    return {
        key: value
        for key, value in os.environ.items()
        if key not in blocked and (key in _SAFE_SHELL_ENV_KEYS or key.startswith("LC_"))
    }


def _tail_text(text: str, max_lines: int, max_bytes: int) -> tuple[str, bool]:
    """Return first and last lines that fit within *max_lines* and *max_bytes*.

    Returns ``(tail_text, was_cut)`` where ``was_cut`` is True when not all
    output is included.
    """
    lines = text.split("\n")
    if len(lines) <= max_lines and len(text.encode()) <= max_bytes:
        return text, False

    head_limit = max_lines // 2
    tail_limit = max_lines - head_limit
    out = lines[:head_limit] + ["...output truncated..."] + lines[-tail_limit:]

    while len("\n".join(out).encode()) > max_bytes and len(out) > 1:
        if len(out) % 2 == 0:
            del out[-2]
        else:
            del out[0]

    return "\n".join(out), True


def _resolve_workdir(workdir: str | None) -> Path:
    """Resolve *workdir* to an absolute path anchored at the sandbox workspace.

    When *workdir* is None or a relative path, it resolves against the sandbox
    workspace root — keeping the agent confined to its session workspace.
    Absolute paths are passed through unchanged.
    """
    sandbox = get_sandbox()
    workspace = sandbox.workspace_root
    if workdir is None:
        return workspace
    return sandbox.validate_path(workdir)


# ── Foreground execute ────────────────────────────────────────────────────────


async def _shell(
    command: Annotated[
        str,
        Field(description="Shell command to run via the user's preferred POSIX shell."),
    ],
    description: Annotated[
        str,
        Field(description="Concise 5-10 word description of the command."),
    ] = "",
    workdir: Annotated[
        str | None,
        Field(
            description="Working directory; relative paths use the session workspace."
        ),
    ] = None,
    timeout_seconds: Annotated[
        int | None,
        Field(
            description="Hard command timeout in seconds; defaults to 120.",
            ge=1,
        ),
    ] = None,
    yield_time_ms: Annotated[
        int,
        Field(
            description=(
                "Return a process_id when the command is still running after this many "
                "milliseconds. Use process to continue it."
            ),
            ge=250,
            le=30000,
        ),
    ] = 10000,
    _tool_output: Annotated[
        Callable[[str], Awaitable[None]] | None,
        InjectedArg(),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
    tool_call_id: Annotated[str | None, InjectedArg()] = None,
) -> str:
    """Run a command, or yield a tracked process for long-running work."""

    sandbox = get_sandbox()
    hit = sandbox.check_command(command)
    if hit is not None:
        resolved, denied = hit
        raise PermissionError(
            f"Sandbox blocked 'shell': command would touch "
            f"'{resolved}' (denied by '{denied}')."
        )
    if not command.strip():
        return "[Succeeded]\n\n(No output)"

    cwd = _resolve_workdir(workdir)
    requested_timeout = (
        timeout_seconds if timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS
    )
    timeout = float(min(requested_timeout, sandbox.max_execution_seconds))
    output_limit = min(sandbox.max_output_bytes, _OUTPUT_MAX_BYTES)
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
    extra: dict[str, Any] = {}
    if sys.platform == "win32":
        extra["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        extra["start_new_session"] = True

    logger.debug(
        "shell_execute_start shell={} command={} cwd={} timeout={} yield_ms={} description={}",
        _shell_mod.name(shell_bin),
        command[:200],
        cwd,
        timeout,
        yield_time_ms,
        description,
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=_scrubbed_env(inherit=sandbox.inherit_shell_environment),
            **extra,
        )
    except NotImplementedError:
        raise RuntimeError(
            "Tracked shell processes require asyncio subprocess support on this system."
        ) from None
    except PermissionError:
        raise
    except Exception as exc:
        logger.error("shell_execute_error command={} error={}", command[:200], exc)
        raise RuntimeError(f"Command execution failed: {exc}") from exc

    tracked = TrackedProcess(
        proc,
        command=command,
        cwd=cwd,
        timeout_seconds=timeout,
        scope=command_process_scope(sandbox.session_id, sandbox.workspace_root),
        output_callback=_tool_output,
    )
    completed = await tracked.wait(timeout_seconds=yield_time_ms / 1000)
    if completed:
        result = format_completed_process(tracked, output_limit=output_limit)
        stash_result_metadata(
            _state,
            tool_call_id,
            completed_metadata(tracked, output_limit=output_limit),
        )
        logger.debug(
            "shell_execute_complete exit_code={} output_bytes={} duration={:.2f}",
            tracked.exit_code,
            tracked.output_bytes,
            tracked.elapsed_seconds,
        )
        return result

    initial, dropped = tracked.consume_delta()
    register_process(tracked)
    activate_process_tool(_state)
    result, metadata = format_running_process(
        tracked,
        initial=initial,
        dropped_bytes=dropped,
        output_limit=output_limit,
    )
    stash_result_metadata(_state, tool_call_id, metadata)
    logger.info(
        "shell_process_yielded process_id={} pid={} command={} output_bytes={}",
        tracked.process_id,
        tracked.pid,
        command[:200],
        tracked.output_bytes,
    )
    return result


shell_tool = Tool(
    _shell,
    name="shell",
    description=(
        "Run a non-interactive shell command in the session workspace. The tool "
        "returns a process_id when work outlives yield_time_ms; continue it with "
        "process. Full output is archived while the model receives a bounded view. "
        "Prefer file tools for file operations and always use non-interactive flags."
    ),
)
