"""Tracked command processes and the background-task registry.

``shell`` owns process creation.  This module owns what happens to a command
that is allowed to outlive its tool call: it is registered under an opaque
``process_id``, its output is journalled to a session artifact, and it
announces its own exit (and any ``notify_on`` match) to the agent through
:mod:`app.agent.background_tasks`.  The model never polls.  The ``process`` tool
only lists, shows the latest output of, or stops a background task.
"""

from __future__ import annotations

import asyncio
import codecs
import os
import re
import signal
import subprocess
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.artifacts import shell_output_dir
from app.agent.background_tasks import MAX_MATCH_NOTICES_PER_TASK, announce_task_event
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool

_OUTPUT_PREVIEW_MAX_BYTES = 262_144
_MATCH_LINE_MAX_CHARS = 8_192
_MODEL_SUCCESS_MAX_BYTES = 6_000
_MODEL_FAILURE_MAX_BYTES = 12_000
_PROCESS_REGISTRY_CAP = 100
_MAX_PROCESS_LIFETIME_SECONDS = 30 * 60
_FORCE_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def command_process_scope(session_id: str | None, workspace: Path) -> str:
    """Return the isolation key used by the command-process registry."""

    return f"session:{session_id}" if session_id else f"workspace:{workspace.resolve()}"


def _taskkill_path() -> str:
    """Resolve taskkill from System32 so a PATH entry cannot shadow it."""

    root = os.environ.get("SystemRoot")
    return str(Path(root) / "System32" / "taskkill.exe") if root else "taskkill.exe"


async def _kill_process_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    """Signal a spawned command's process group, falling back to the process."""

    pid = proc.pid
    if pid is None:
        return
    if os.name == "nt":
        killer: asyncio.subprocess.Process | None = None
        try:
            try:
                killer = await asyncio.create_subprocess_exec(
                    _taskkill_path(),
                    "/PID",
                    str(pid),
                    "/T",
                    "/F",
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                await asyncio.wait_for(killer.wait(), timeout=5)
            except (OSError, asyncio.TimeoutError):
                if killer is not None and killer.returncode is None:
                    try:
                        killer.kill()
                    except (ProcessLookupError, OSError):
                        pass
                    await killer.wait()
        finally:
            # Also reached when the caller is cancelled mid-taskkill, so the
            # command is never left running.
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
        return
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


def _clip_bytes(raw: bytes, limit: int) -> tuple[str, int]:
    """Decode at most *limit* bytes, retaining useful head and tail context."""

    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace").rstrip(), 0
    head_size = max(1, limit // 3)
    tail_size = max(1, limit - head_size)
    omitted = len(raw) - head_size - tail_size
    head = raw[:head_size].decode("utf-8", errors="replace").rstrip()
    tail = raw[-tail_size:].decode("utf-8", errors="replace").lstrip()
    return f"{head}\n\n... {omitted:,} bytes omitted ...\n\n{tail}".rstrip(), omitted


def _read_artifact_preview(path: Path, limit: int) -> tuple[str, int, int]:
    """Return a bounded artifact preview, total bytes, and omitted bytes."""

    try:
        size = path.stat().st_size
        if size <= limit:
            raw = path.read_bytes()
        else:
            head_size = max(1, limit // 3)
            tail_size = max(1, limit - head_size)
            with path.open("rb") as handle:
                head = handle.read(head_size)
                handle.seek(max(0, size - tail_size))
                tail = handle.read(tail_size)
            raw = head + tail
            preview = (
                head.decode("utf-8", errors="replace").rstrip()
                + f"\n\n... {size - len(raw):,} bytes omitted ...\n\n"
                + tail.decode("utf-8", errors="replace").lstrip()
            ).rstrip()
            return preview, size, size - len(raw)
        preview, omitted = _clip_bytes(raw, limit)
        return preview, size, omitted
    except OSError:
        return "", 0, 0


def _status_label(*, exit_code: int | None, timed_out: bool, running: bool) -> str:
    if running:
        return "Running"
    if timed_out:
        return "Timed out"
    if exit_code == 0:
        return "Succeeded"
    return f"Failed — exit code {exit_code}"


def _result_metadata(
    tracked: "TrackedProcess",
    *,
    shown_bytes: int,
    omitted_bytes: int,
) -> dict[str, Any]:
    return {
        "command": True,
        "process_id": tracked.process_id,
        "pid": tracked.pid,
        "status": tracked.status,
        "exit_code": tracked.exit_code,
        "duration_ms": round(tracked.elapsed_seconds * 1000, 3),
        "artifact": str(tracked.output_path),
        "output_bytes": tracked.output_bytes,
        "shown_bytes": shown_bytes,
        "omitted_bytes": omitted_bytes,
    }


def stash_result_metadata(
    state: Any,
    tool_call_id: str | None,
    metadata: dict[str, Any],
) -> None:
    """Attach result metadata for the loop/SSE without embedding it in text."""

    if state is None or not tool_call_id:
        return
    state.metadata.setdefault("_tool_result_metadata", {})[tool_call_id] = metadata


class TrackedProcess:
    """A subprocess whose raw output is journalled to a session artifact.

    A *foreground* process is awaited by the ``shell`` call that started it. A
    *background* one (``announce=True``) is registered and reports for itself:
    it tells the agent when it exits, and when a line matches ``notify_on``.
    """

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        *,
        command: str,
        cwd: Path,
        timeout_seconds: float | None,
        scope: str,
        session_id: str | None = None,
        output_callback: Callable[[str], Awaitable[None]] | None = None,
        process_id: str | None = None,
        announce: bool = False,
        notify_on: re.Pattern[str] | None = None,
    ) -> None:
        self.proc = proc
        self.command = command
        self.cwd = cwd
        self.process_id = process_id or f"proc_{uuid.uuid4().hex[:10]}"
        self.started_at = time.monotonic()
        requested_lifetime = (
            timeout_seconds
            if timeout_seconds is not None
            else _MAX_PROCESS_LIFETIME_SECONDS
        )
        self.timeout_seconds = min(requested_lifetime, _MAX_PROCESS_LIFETIME_SECONDS)
        self.scope = scope
        self.session_id = session_id
        self.timed_out = False
        self.output_path = shell_output_dir() / f"{self.process_id}.txt"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"")
        self.announce = announce
        self.notify_on = notify_on
        # Set when the agent or the app ends the process on purpose: that is
        # not news, so no exit notice is sent for it.
        self._stopped = False
        self._match_notices = 0
        self._line_buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._announcements: set[asyncio.Task[Any]] = set()
        self._output_callback = output_callback
        self._reader_task = asyncio.create_task(self._drain())
        self._timeout_task = (
            asyncio.create_task(self._enforce_timeout())
            if timeout_seconds is not None
            else None
        )
        self._exit_task: asyncio.Task[None] | None = None
        if announce:
            self.begin_announcing()

    def begin_announcing(self) -> None:
        """Start telling the agent when this task exits (background tasks)."""

        self.announce = True
        if self._exit_task is None:
            self._exit_task = asyncio.create_task(self._announce_exit())

    @property
    def pid(self) -> int | None:
        return self.proc.pid

    @property
    def running(self) -> bool:
        return self.proc.returncode is None

    @property
    def exit_code(self) -> int | None:
        return self.proc.returncode

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def output_bytes(self) -> int:
        try:
            return self.output_path.stat().st_size
        except OSError:
            return 0

    @property
    def status(self) -> str:
        if self.running:
            return "running"
        if self.timed_out:
            return "timed_out"
        return "succeeded" if self.exit_code == 0 else "failed"

    async def _drain(self) -> None:
        assert self.proc.stdout is not None
        emit_buffer: list[str] = []
        emit_task: asyncio.Task[None] | None = None

        async def flush_later() -> None:
            await asyncio.sleep(0.1)
            if self._output_callback is not None and emit_buffer:
                text = "".join(emit_buffer)
                emit_buffer.clear()
                try:
                    await self._output_callback(text)
                except Exception:
                    pass

        try:
            with self.output_path.open("ab") as artifact:
                while True:
                    chunk = await self.proc.stdout.read(8192)
                    if not chunk:
                        break
                    artifact.write(chunk)
                    artifact.flush()
                    if self.notify_on is not None:
                        self._scan_for_matches(chunk)
                    if self._output_callback is not None:
                        emit_buffer.append(chunk.decode("utf-8", errors="replace"))
                        if emit_task is None or emit_task.done():
                            emit_task = asyncio.create_task(flush_later())
        finally:
            if self.notify_on is not None:
                self._scan_for_matches(b"", final=True)
            if emit_task is not None:
                try:
                    await emit_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._output_callback is not None and emit_buffer:
                try:
                    await self._output_callback("".join(emit_buffer))
                except Exception:
                    pass

    def _scan_for_matches(self, chunk: bytes, *, final: bool = False) -> None:
        """Announce each complete output line that matches ``notify_on``."""

        assert self.notify_on is not None
        text = self._decoder.decode(chunk, final=final)
        self._line_buffer += text
        lines = self._line_buffer.split("\n")
        # The unfinished tail waits for its newline, but is bounded so a task
        # that never prints one cannot grow it without limit.
        self._line_buffer = "" if final else lines.pop()[-_MATCH_LINE_MAX_CHARS:]
        if final and lines and not lines[-1]:
            lines.pop()
        for line in lines:
            if (
                not self.announce
                or self._match_notices >= MAX_MATCH_NOTICES_PER_TASK
                or self._stopped
            ):
                return
            if not self.notify_on.search(line):
                continue
            self._match_notices += 1
            self._spawn_announcement(
                announce_task_event(self, "matched", matched_line=line)
            )

    def _spawn_announcement(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)

    async def _announce_exit(self) -> None:
        """Tell the agent how this background task ended."""

        try:
            await self.proc.wait()
            await self._reader_task
            await self._cancel_timeout_task()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - the notice is best effort
            return
        if self._stopped:
            return
        await announce_task_event(self, "exited")

    async def _enforce_timeout(self) -> None:
        assert self.timeout_seconds is not None
        try:
            await asyncio.sleep(self.timeout_seconds)
            if self.running:
                self.timed_out = True
                logger.warning(
                    "command_process_timeout process_id={} pid={} timeout_seconds={}",
                    self.process_id,
                    self.proc.pid,
                    self.timeout_seconds,
                )
                await _kill_process_group(self.proc, _FORCE_KILL)
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    logger.error(
                        "command_process_timeout_kill_pending process_id={} pid={}",
                        self.process_id,
                        self.proc.pid,
                    )
                    await _kill_process_group(self.proc, _FORCE_KILL)
                    try:
                        await asyncio.wait_for(self.proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        logger.critical(
                            "command_process_timeout_kill_failed process_id={} pid={}",
                            self.process_id,
                            self.proc.pid,
                        )
        except asyncio.CancelledError:
            pass

    async def wait(self, timeout_seconds: float | None = None) -> bool:
        """Wait for completion. Return ``True`` if finished before timeout."""

        try:
            if timeout_seconds is None:
                await self.proc.wait()
            else:
                await asyncio.wait_for(self.proc.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return False
        await self._reader_task
        await self._cancel_timeout_task()
        return True

    async def _cancel_timeout_task(self) -> None:
        task = self._timeout_task
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def terminate(self) -> None:
        self._stopped = True
        if self.running:
            await _kill_process_group(self.proc, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                await _kill_process_group(self.proc, _FORCE_KILL)
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    logger.error(
                        "command_process_terminate_kill_failed process_id={} pid={}",
                        self.process_id,
                        self.proc.pid,
                    )
        try:
            await asyncio.wait_for(self._reader_task, timeout=5)
        except asyncio.TimeoutError:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        await self._cancel_timeout_task()
        if self._exit_task is not None and not self._exit_task.done():
            self._exit_task.cancel()
            await asyncio.gather(self._exit_task, return_exceptions=True)

    def read_output(self, *, last_n: int | None = None) -> str:
        """Read a bounded view of the output so far."""

        preview, _total, _omitted = _read_artifact_preview(
            self.output_path, _OUTPUT_PREVIEW_MAX_BYTES
        )
        if last_n is None:
            return preview
        return "\n".join(preview.splitlines()[-last_n:])


_processes: dict[str, TrackedProcess] = {}


def tracked_processes(*, running_only: bool = True) -> list[TrackedProcess]:
    """Return a stable snapshot for the app-level process manager."""

    processes = list(_processes.values())
    if running_only:
        processes = [process for process in processes if process.running]
    return sorted(processes, key=lambda process: process.started_at)


async def terminate_tracked_process(process_id: str) -> bool:
    """Terminate and forget one command process by its opaque id."""

    tracked = _processes.get(process_id)
    if tracked is None:
        return False
    await tracked.terminate()
    _processes.pop(process_id, None)
    return True


def register_process(tracked: TrackedProcess) -> None:
    if len(_processes) >= _PROCESS_REGISTRY_CAP:
        finished = sorted(
            (p for p in _processes.values() if not p.running),
            key=lambda item: item.started_at,
        )
        for item in finished[: max(1, len(finished) // 2)]:
            _processes.pop(item.process_id, None)
    _processes[tracked.process_id] = tracked


async def stop_all_processes() -> None:
    """Terminate every registered command process during application shutdown."""

    tracked = list(_processes.values())
    _processes.clear()
    if not tracked:
        return
    results = await asyncio.gather(
        *(item.terminate() for item in tracked),
        return_exceptions=True,
    )
    failures = sum(isinstance(result, BaseException) for result in results)
    logger.info(
        "command_processes_stopped count={} failures={}",
        len(tracked),
        failures,
    )


def format_completed_process(tracked: TrackedProcess, *, output_limit: int) -> str:
    failed = tracked.timed_out or tracked.exit_code != 0
    limit = min(
        output_limit,
        _MODEL_FAILURE_MAX_BYTES if failed else _MODEL_SUCCESS_MAX_BYTES,
    )
    output, total, omitted = _read_artifact_preview(tracked.output_path, limit)
    label = _status_label(
        exit_code=tracked.exit_code,
        timed_out=tracked.timed_out,
        running=False,
    )
    lines = [f"[{label}]", f"duration: {tracked.elapsed_seconds:.2f}s"]
    if output:
        lines.extend(["", output])
    else:
        lines.extend(["", "(No output)"])
    if omitted:
        lines.extend(["", f"Full output: {tracked.output_path} ({total:,} bytes)"])
    return "\n".join(lines)


def completed_metadata(tracked: TrackedProcess, *, output_limit: int) -> dict[str, Any]:
    failed = tracked.timed_out or tracked.exit_code != 0
    shown = min(
        tracked.output_bytes,
        output_limit,
        _MODEL_FAILURE_MAX_BYTES if failed else _MODEL_SUCCESS_MAX_BYTES,
    )
    return _result_metadata(
        tracked,
        shown_bytes=shown,
        omitted_bytes=max(0, tracked.output_bytes - shown),
    )


def format_started_process(tracked: TrackedProcess) -> tuple[str, dict[str, Any]]:
    """The result of ``shell(background=true)``: the task is running on its own."""

    lines = [
        "[Started in background]",
        f"process_id: {tracked.process_id}",
        f"pid: {tracked.pid}",
        f"command: {tracked.command}",
        f"output: {tracked.output_path}",
        "",
    ]
    if tracked.notify_on is not None:
        lines.append(
            "You will be notified when it exits, and when a line matches "
            f"/{tracked.notify_on.pattern}/. Do not poll it; carry on with other "
            "work or finish your turn."
        )
    else:
        lines.append(
            "You will be notified when it exits. Do not poll it; carry on with "
            "other work or finish your turn."
        )
    return "\n".join(lines), _result_metadata(tracked, shown_bytes=0, omitted_bytes=0)


def _format_snapshot(
    tracked: TrackedProcess, *, last_lines: int
) -> tuple[str, dict[str, Any]]:
    """A non-consuming view of a task's status and the end of its output."""

    label = _status_label(
        exit_code=tracked.exit_code,
        timed_out=tracked.timed_out,
        running=tracked.running,
    )
    output = tracked.read_output(last_n=last_lines)
    lines = [
        f"[{label}]",
        f"process_id: {tracked.process_id}",
        f"duration: {tracked.elapsed_seconds:.2f}s",
        "",
        output or "(No output yet)",
    ]
    if tracked.output_bytes > len(output.encode("utf-8", errors="ignore")):
        lines.extend(
            ["", f"Full output: {tracked.output_path} ({tracked.output_bytes:,} bytes)"]
        )
    shown = len(output.encode("utf-8", errors="ignore"))
    metadata = _result_metadata(
        tracked,
        shown_bytes=shown,
        omitted_bytes=max(0, tracked.output_bytes - shown),
    )
    return "\n".join(lines), metadata


async def _process(
    action: Annotated[
        Literal["list", "output", "stop"],
        Field(
            description=(
                "list background tasks, show the latest output of one, or stop one."
            )
        ),
    ],
    process_id: Annotated[
        str | None,
        Field(
            description=(
                "process_id returned by shell(background=true). Omit only for list."
            )
        ),
    ] = None,
    last_lines: Annotated[
        int,
        Field(description="For output: how many trailing lines to show.", ge=1, le=500),
    ] = 50,
    _state: Annotated[Any, InjectedArg()] = None,
    tool_call_id: Annotated[str | None, InjectedArg()] = None,
) -> str:
    """Inspect or stop a background command. Never needed to learn that it ended."""

    sandbox = get_sandbox()
    scope = command_process_scope(sandbox.session_id, sandbox.workspace_root)

    if action == "list":
        visible = [item for item in _processes.values() if item.scope == scope]
        if not visible:
            return "No background tasks."
        return "\n".join(
            f"{item.process_id}  {item.status}  pid={item.pid}  {item.command[:100]}"
            for item in sorted(visible, key=lambda value: value.started_at)
        )

    if not process_id:
        return "Error: process_id is required."
    tracked = _processes.get(process_id)
    if tracked is None or tracked.scope != scope:
        return f"Error: process '{process_id}' was not found."

    if action == "stop":
        await tracked.terminate()
        _processes.pop(tracked.process_id, None)
    result, metadata = _format_snapshot(tracked, last_lines=last_lines)
    stash_result_metadata(_state, tool_call_id, metadata)
    logger.info(
        "command_process_observed process_id={} action={} status={}",
        tracked.process_id,
        action,
        tracked.status,
    )
    return result


process_tool = Tool(
    _process,
    name="process",
    description=(
        "Manage background commands started with shell(background=true). A "
        "background command reports for itself when it exits, so use this only "
        "to list them, look at the latest output of one that is still running, "
        "or stop one. Never poll."
    ),
)
