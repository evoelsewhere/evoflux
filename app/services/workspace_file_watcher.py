"""Workspace filesystem watcher — emits change events over SSE.

Uses ``watchfiles`` (Rust-based ``notify`` backend) to detect file system
changes in real time. Events are debounced and broadcast to all subscribers
watching the same workspace.

The watcher starts lazily when the first subscriber connects and stops when
all subscribers disconnect. This avoids consuming resources for workspaces
nobody is observing.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any

from loguru import logger


class WorkspaceFileWatcher:
    """Manages per-workspace watch loops and fan-out to subscriber queues."""

    def __init__(self, debounce_ms: int = 300) -> None:
        self._debounce_ms = debounce_ms
        # workspace_path → list of subscriber asyncio.Queues
        self._subscribers: dict[str, list[asyncio.Queue[list[dict[str, str]]]]] = (
            defaultdict(list)
        )
        # workspace_path → running watch task
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(
        self, workspace: str
    ) -> asyncio.Queue[list[dict[str, str]]]:
        """Add a subscriber for a workspace. Starts the watcher if needed."""
        queue: asyncio.Queue[list[dict[str, str]]] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers[workspace].append(queue)
            if workspace not in self._tasks or self._tasks[workspace].done():
                self._tasks[workspace] = asyncio.create_task(
                    self._watch_loop(workspace),
                    name=f"fs-watcher:{workspace}",
                )
        return queue

    async def unsubscribe(
        self, workspace: str, queue: asyncio.Queue[list[dict[str, str]]]
    ) -> None:
        """Remove a subscriber. Stops the watcher if no subscribers remain."""
        async with self._lock:
            subs = self._subscribers.get(workspace, [])
            try:
                subs.remove(queue)
            except ValueError:
                pass
            if not subs:
                self._subscribers.pop(workspace, None)
                task = self._tasks.pop(workspace, None)
                if task and not task.done():
                    task.cancel()

    async def _watch_loop(self, workspace: str) -> None:
        """Run watchfiles for a workspace, broadcasting events to subscribers."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            logger.warning("fs_watcher_unavailable watchfiles not installed")
            return

        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            logger.warning(
                "fs_watcher_not_a_dir workspace={}", workspace
            )
            return

        logger.info("fs_watcher_started workspace={}", workspace)

        try:
            async for changes in awatch(
                str(workspace_path),
                debounce=self._debounce_ms,
                recursive=True,
            ):
                # Convert watchfiles changes to a list of {type, path} dicts
                events: list[dict[str, str]] = []
                for change_type, raw_path in changes:
                    try:
                        rel = str(
                            Path(raw_path).relative_to(workspace_path)
                        ).replace("\\", "/")
                    except ValueError:
                        continue

                    # Skip hidden/internal dirs
                    if any(
                        part.startswith(".")
                        for part in Path(rel).parts
                    ):
                        continue

                    kind = (
                        "added"
                        if change_type == Change.added
                        else "deleted"
                        if change_type == Change.deleted
                        else "modified"
                    )
                    events.append({"type": kind, "path": rel})

                if not events:
                    continue

                # Broadcast to all subscribers
                async with self._lock:
                    subs = self._subscribers.get(workspace, [])
                    dead: list[asyncio.Queue[Any]] = []
                    for q in subs:
                        try:
                            q.put_nowait(events)
                        except asyncio.QueueFull:
                            dead.append(q)
                    for q in dead:
                        subs.remove(q)

        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("fs_watcher_error workspace={} err={}", workspace, exc)
        finally:
            logger.info("fs_watcher_stopped workspace={}", workspace)


# Singleton instance — shared across the application
workspace_file_watcher = WorkspaceFileWatcher()
