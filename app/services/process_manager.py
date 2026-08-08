"""Unified view of user-visible long-running processes.

The agent command runner, preview tool, and interactive terminal each retain
their own lifecycle registry.  This module deliberately composes those
registries instead of creating a second source of truth.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from app.agent.tools.builtin.preview import (
    preview_servers,
    terminate_preview_server,
)
from app.agent.tools.builtin.process import (
    terminate_tracked_process,
    tracked_processes,
)
from app.services.terminal_service import terminal_manager

ProcessKind = Literal["command", "preview", "terminal"]


@dataclass(frozen=True, slots=True)
class ActiveProcess:
    id: str
    kind: ProcessKind
    label: str
    command: str
    session_id: str | None
    pid: int | None
    cwd: str | None
    elapsed_seconds: float
    killable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def _opaque_id(kind: ProcessKind, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]
    return f"{kind}_{digest}"


def _session_from_scope(scope: str) -> str | None:
    if scope.startswith("session:"):
        return scope.removeprefix("session:") or None
    return None


def list_active_processes() -> list[ActiveProcess]:
    """Collect every live process that is meaningful to an EvoFlux user."""

    processes: list[ActiveProcess] = []
    for tracked in tracked_processes():
        processes.append(
            ActiveProcess(
                id=tracked.process_id,
                kind="command",
                label=tracked.command,
                command=tracked.command,
                session_id=_session_from_scope(tracked.scope),
                pid=tracked.pid,
                cwd=str(tracked.cwd),
                elapsed_seconds=tracked.elapsed_seconds,
            )
        )

    for (workspace, name), server in preview_servers():
        if not server.running:
            continue
        processes.append(
            ActiveProcess(
                id=_opaque_id("preview", workspace, name),
                kind="preview",
                label=name,
                command=server.command,
                session_id=server.session_id,
                pid=server.pid,
                cwd=server.workdir,
                elapsed_seconds=max(0.0, server.elapsed_seconds),
                killable=not server.reused,
                metadata={
                    "port": server.port,
                    "url": f"http://localhost:{server.port}",
                    "reused": server.reused,
                    "workspace": workspace,
                },
            )
        )

    for terminal in terminal_manager.list_sessions():
        processes.append(
            ActiveProcess(
                id=_opaque_id("terminal", terminal.session_id, terminal.terminal_id),
                kind="terminal",
                label=f"Terminal {terminal.terminal_id}",
                command="Interactive shell",
                session_id=terminal.session_id,
                pid=terminal.backend.pid,
                cwd=terminal.cwd or None,
                elapsed_seconds=max(0.0, time.monotonic() - terminal.started_at),
                metadata={"terminal_id": terminal.terminal_id},
            )
        )

    order = {"preview": 0, "command": 1, "terminal": 2}
    return sorted(processes, key=lambda process: (order[process.kind], process.label))


async def terminate_active_process(process_id: str) -> bool:
    """Terminate a process returned by :func:`list_active_processes`."""

    if process_id.startswith("proc_"):
        return await terminate_tracked_process(process_id)

    for (workspace, name), _server in preview_servers():
        if process_id == _opaque_id("preview", workspace, name):
            return await terminate_preview_server(workspace, name)

    for terminal in terminal_manager.list_sessions():
        expected = _opaque_id("terminal", terminal.session_id, terminal.terminal_id)
        if process_id == expected:
            await terminal_manager.close(
                terminal.session_id, terminal_id=terminal.terminal_id
            )
            return True
    return False
