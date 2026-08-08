"""Tracked command processes with delta-only output consumption.

``shell`` owns process creation.  This module owns the continuation protocol:
commands that outlive the shell tool's yield window receive an opaque
``process_id`` and can then be polled, waited for, listed, or terminated through
one compact tool.  Output is journalled once to a session artifact; model-facing
polls consume only bytes not returned by an earlier observation.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.artifacts import shell_output_dir
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool

_PENDING_OUTPUT_MAX_BYTES = 262_144
_MODEL_SUCCESS_MAX_BYTES = 6_000
_MODEL_FAILURE_MAX_BYTES = 12_000
_PROCESS_REGISTRY_CAP = 100
_MAX_WAIT_SECONDS = 60
_FORCE_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


def command_process_scope(session_id: str | None, workspace: Path) -> str:
    """Return the isolation key used by the command-process registry."""

    return f"session:{session_id}" if session_id else f"workspace:{workspace.resolve()}"


def _kill_process_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    """Signal a spawned command's process group, falling back to the process."""

    pid = proc.pid
    if pid is None:
        return
    if os.name == "nt":
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
    """A subprocess whose raw output is journalled and consumed incrementally."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        *,
        command: str,
        cwd: Path,
        timeout_seconds: float | None,
        scope: str,
        output_callback: Callable[[str], Awaitable[None]] | None = None,
        process_id: str | None = None,
    ) -> None:
        self.proc = proc
        self.command = command
        self.cwd = cwd
        self.process_id = process_id or f"proc_{uuid.uuid4().hex[:10]}"
        self.started_at = time.monotonic()
        self.timeout_seconds = timeout_seconds
        self.scope = scope
        self.timed_out = False
        self.output_path = shell_output_dir() / f"{self.process_id}.txt"
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"")
        self._pending: deque[bytes] = deque()
        self._pending_bytes = 0
        self._dropped_pending_bytes = 0
        self._activity = asyncio.Event()
        self._output_callback = output_callback
        self._reader_task = asyncio.create_task(self._drain())
        self._timeout_task = (
            asyncio.create_task(self._enforce_timeout())
            if timeout_seconds is not None
            else None
        )

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
                    self._pending.append(chunk)
                    self._pending_bytes += len(chunk)
                    while self._pending_bytes > _PENDING_OUTPUT_MAX_BYTES:
                        dropped = self._pending.popleft()
                        self._pending_bytes -= len(dropped)
                        self._dropped_pending_bytes += len(dropped)
                    self._activity.set()
                    if self._output_callback is not None:
                        emit_buffer.append(chunk.decode("utf-8", errors="replace"))
                        if emit_task is None or emit_task.done():
                            emit_task = asyncio.create_task(flush_later())
        finally:
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
            self._activity.set()

    async def _enforce_timeout(self) -> None:
        assert self.timeout_seconds is not None
        try:
            await asyncio.sleep(self.timeout_seconds)
            if self.running:
                self.timed_out = True
                _kill_process_group(self.proc, _FORCE_KILL)
                await self.proc.wait()
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

    async def wait_for_activity(self, timeout_seconds: float) -> None:
        """Wait until unread output arrives or the process exits."""

        if self._pending_bytes or not self.running or timeout_seconds <= 0:
            return
        self._activity.clear()
        if self._pending_bytes or not self.running:
            return
        try:
            await asyncio.wait_for(self._activity.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            pass

    def consume_delta(self) -> tuple[bytes, int]:
        raw = b"".join(self._pending)
        dropped = self._dropped_pending_bytes
        self._pending.clear()
        self._pending_bytes = 0
        self._dropped_pending_bytes = 0
        self._activity.clear()
        return raw, dropped

    async def terminate(self) -> None:
        if self.running:
            _kill_process_group(self.proc, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                _kill_process_group(self.proc, _FORCE_KILL)
                await self.proc.wait()
        await self._reader_task
        await self._cancel_timeout_task()

    def read_output(self, *, last_n: int | None = None) -> str:
        """Read a bounded log view without participating in delta consumption."""

        preview, _total, _omitted = _read_artifact_preview(
            self.output_path, _PENDING_OUTPUT_MAX_BYTES
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


def activate_process_tool(state: Any) -> None:
    if state is not None:
        state.metadata.setdefault("activated_deferred_tools", set()).add("process")


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


def format_running_process(
    tracked: TrackedProcess,
    *,
    initial: bytes,
    dropped_bytes: int,
    output_limit: int,
) -> tuple[str, dict[str, Any]]:
    limit = min(output_limit, _MODEL_SUCCESS_MAX_BYTES)
    output, omitted = _clip_bytes(initial, limit)
    omitted += dropped_bytes
    lines = [
        "[Running]",
        f"process_id: {tracked.process_id}",
        f"pid: {tracked.pid}",
        f"command: {tracked.command}",
        f"artifact: {tracked.output_path}",
    ]
    if output:
        lines.extend(["", "Initial output:", output])
    if omitted:
        lines.extend(["", f"{omitted:,} earlier bytes are available in the artifact."])
    lines.extend(
        ["", f"Use process(action='poll', process_id='{tracked.process_id}')."]
    )
    metadata = _result_metadata(
        tracked,
        shown_bytes=min(len(initial), limit),
        omitted_bytes=omitted,
    )
    return "\n".join(lines), metadata


def _format_delta(
    tracked: TrackedProcess,
    *,
    raw: bytes,
    dropped: int,
) -> tuple[str, dict[str, Any]]:
    failed = not tracked.running and (tracked.timed_out or tracked.exit_code != 0)
    limit = _MODEL_FAILURE_MAX_BYTES if failed else _MODEL_SUCCESS_MAX_BYTES
    output, omitted = _clip_bytes(raw, limit)
    omitted += dropped
    label = _status_label(
        exit_code=tracked.exit_code,
        timed_out=tracked.timed_out,
        running=tracked.running,
    )
    lines = [
        f"[{label}]",
        f"process_id: {tracked.process_id}",
        f"duration: {tracked.elapsed_seconds:.2f}s",
    ]
    if output:
        lines.extend(["", "New output:", output])
    else:
        lines.extend(["", "(No new output)"])
    if omitted:
        lines.extend(
            ["", f"Full output: {tracked.output_path} ({tracked.output_bytes:,} bytes)"]
        )
    metadata = _result_metadata(
        tracked,
        shown_bytes=min(len(raw), limit),
        omitted_bytes=omitted,
    )
    return "\n".join(lines), metadata


async def _process(
    action: Annotated[
        Literal["list", "poll", "wait", "terminate"],
        Field(
            description="List processes, consume new output, wait briefly, or terminate."
        ),
    ],
    process_id: Annotated[
        str | None,
        Field(description="Opaque process_id returned by shell. Omit only for list."),
    ] = None,
    wait_seconds: Annotated[
        int,
        Field(
            description="For wait: seconds to await new output or completion (max 60).",
            ge=1,
            le=60,
        ),
    ] = 10,
    _state: Annotated[Any, InjectedArg()] = None,
    tool_call_id: Annotated[str | None, InjectedArg()] = None,
) -> str:
    """Continue a command returned by shell without replaying old output."""

    if action == "list":
        sandbox = get_sandbox()
        scope = command_process_scope(sandbox.session_id, sandbox.workspace_root)
        visible = [item for item in _processes.values() if item.scope == scope]
        if not visible:
            return "No tracked command processes."
        return "\n".join(
            f"{item.process_id}  {item.status}  pid={item.pid}  {item.command[:100]}"
            for item in sorted(visible, key=lambda value: value.started_at)
        )

    if not process_id:
        return "Error: process_id is required."
    tracked = _processes.get(process_id)
    sandbox = get_sandbox()
    scope = command_process_scope(sandbox.session_id, sandbox.workspace_root)
    if tracked is None or tracked.scope != scope:
        return f"Error: process '{process_id}' was not found."

    if action == "wait":
        await tracked.wait_for_activity(float(min(wait_seconds, _MAX_WAIT_SECONDS)))
        if tracked.running:
            # A command's final stdout bytes can become readable a scheduling
            # tick before its exit status. Briefly coalesce that edge so the
            # model does not spend another tool call observing completion.
            await tracked.wait(timeout_seconds=0.05)
        if not tracked.running:
            # Completion and the final pipe read are separate events. Join the
            # reader before consuming the last delta.
            await tracked.wait()
    elif action == "terminate":
        await tracked.terminate()
    elif not tracked.running:
        # The OS may report completion before the stdout reader has consumed
        # the final pipe bytes. Join it before the last delta and registry exit.
        await tracked.wait()

    raw, dropped = tracked.consume_delta()
    result, metadata = _format_delta(tracked, raw=raw, dropped=dropped)
    stash_result_metadata(_state, tool_call_id, metadata)
    if not tracked.running:
        _processes.pop(tracked.process_id, None)
    logger.info(
        "command_process_observed process_id={} action={} status={} delta_bytes={} dropped_bytes={}",
        tracked.process_id,
        action,
        tracked.status,
        len(raw),
        dropped,
    )
    return result


process_tool = Tool(
    _process,
    name="process",
    deferred=True,
    deferred_summary="Poll, wait for, list, or terminate a command process returned by shell.",
    description=(
        "Continue a command process returned by shell. Poll and wait return only new "
        "output since the previous observation, preventing repeated log content."
    ),
)
