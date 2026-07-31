"""Workspace filesystem watcher — single source of FS events.

Uses ``watchfiles`` (Rust-based ``notify`` backend) to detect file system
changes in real time. Events are debounced and broadcast to all subscribers
watching the same workspace.

The watcher starts lazily when the first subscriber (SSE client or internal
hook like the code-graph indexer) connects and stops when all subscribers
disconnect.

Two subscription modes:
- **Queue subscribers** (SSE endpoints): receive batched events via asyncio.Queue.
- **Callbacks** (code-graph reindexer): invoked directly with the events list.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

# Type for change events: [{type: "added"|"modified"|"deleted", path: "rel/path"}]
FsChangeEvent = dict[str, str]
FsChangeCallback = Callable[[str, list[FsChangeEvent]], Awaitable[None]]


class WorkspaceFileWatcher:
    """Manages per-workspace watch loops and fan-out to subscriber queues + callbacks."""

    def __init__(self, debounce_ms: int = 300) -> None:
        self._debounce_ms = debounce_ms
        # workspace_path → list of subscriber asyncio.Queues
        self._subscribers: dict[str, list[asyncio.Queue[list[FsChangeEvent]]]] = (
            defaultdict(list)
        )
        # workspace_path → list of async callbacks
        self._callbacks: dict[str, list[FsChangeCallback]] = defaultdict(list)
        # workspace_path → running watch task
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Queue-based subscription (SSE endpoints)
    # ------------------------------------------------------------------

    async def subscribe(self, workspace: str) -> asyncio.Queue[list[FsChangeEvent]]:
        """Add a queue subscriber for a workspace. Starts the watcher if needed."""
        queue: asyncio.Queue[list[FsChangeEvent]] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers[workspace].append(queue)
            self._ensure_task(workspace)
        return queue

    async def unsubscribe(
        self, workspace: str, queue: asyncio.Queue[list[FsChangeEvent]]
    ) -> None:
        """Remove a queue subscriber. Stops the watcher if no subscribers remain."""
        async with self._lock:
            subs = self._subscribers.get(workspace, [])
            try:
                subs.remove(queue)
            except ValueError:
                pass
            self._maybe_stop(workspace)

    # ------------------------------------------------------------------
    # Callback-based subscription (code-graph, plugins)
    # ------------------------------------------------------------------

    async def add_callback(self, workspace: str, callback: FsChangeCallback) -> None:
        """Register an async callback for change events. Starts the watcher if needed."""
        async with self._lock:
            self._callbacks[workspace].append(callback)
            self._ensure_task(workspace)

    async def remove_callback(self, workspace: str, callback: FsChangeCallback) -> None:
        """Unregister a callback. Stops the watcher if no subscribers remain."""
        async with self._lock:
            cbs = self._callbacks.get(workspace, [])
            try:
                cbs.remove(callback)
            except ValueError:
                pass
            self._maybe_stop(workspace)

    # ------------------------------------------------------------------
    # Bulk lifecycle helpers (for code-graph watcher starting many at once)
    # ------------------------------------------------------------------

    async def add_callback_many(
        self, workspaces: list[str], callback: FsChangeCallback
    ) -> None:
        """Register a callback for multiple workspaces at once."""
        async with self._lock:
            for ws in workspaces:
                self._callbacks[ws].append(callback)
                self._ensure_task(ws)

    async def remove_callback_many(
        self, workspaces: list[str], callback: FsChangeCallback
    ) -> None:
        """Unregister a callback from multiple workspaces."""
        async with self._lock:
            for ws in workspaces:
                cbs = self._callbacks.get(ws, [])
                try:
                    cbs.remove(callback)
                except ValueError:
                    pass
                self._maybe_stop(ws)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_subscribers(self, workspace: str) -> bool:
        return bool(self._subscribers.get(workspace)) or bool(
            self._callbacks.get(workspace)
        )

    def _ensure_task(self, workspace: str) -> None:
        """Start the watch loop for workspace if not already running. Must hold _lock."""
        if workspace not in self._tasks or self._tasks[workspace].done():
            self._tasks[workspace] = asyncio.create_task(
                self._watch_loop(workspace),
                name=f"fs-watcher:{workspace}",
            )

    def _maybe_stop(self, workspace: str) -> None:
        """Stop the watcher if no subscribers remain. Must hold _lock."""
        if not self._has_subscribers(workspace):
            self._subscribers.pop(workspace, None)
            self._callbacks.pop(workspace, None)
            task = self._tasks.pop(workspace, None)
            if task and not task.done():
                task.cancel()

    # ------------------------------------------------------------------
    # Watch loop
    # ------------------------------------------------------------------

    async def _watch_loop(self, workspace: str) -> None:
        """Run watchfiles for a workspace, broadcasting events to subscribers."""
        try:
            from watchfiles import awatch, Change
        except ImportError:
            logger.warning("fs_watcher_unavailable watchfiles not installed")
            return

        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            logger.warning("fs_watcher_not_a_dir workspace={}", workspace)
            return

        # Pre-compute string prefix for fast relative-path extraction
        workspace_str = str(workspace_path)
        prefix_len = len(workspace_str) + 1  # +1 for trailing separator

        # Rust-layer filter: reject hidden directories before events reach Python
        def _watch_filter(change: Any, path: str) -> bool:  # noqa: ANN401
            # Fast check: reject any path segment starting with '.'
            rel = path[prefix_len:] if len(path) > prefix_len else path
            # Root .gitignore changes alter which files belong to the code
            # index, so keep that single metadata event while continuing to
            # suppress noisy hidden directories and their contents.
            if rel.replace("\\", "/") == ".gitignore":
                return True
            return not any(
                seg.startswith(".") for seg in rel.replace("\\", "/").split("/") if seg
            )

        # Map Change enum to strings once (avoid repeated comparisons per event)
        change_map = {
            Change.added: "added",
            Change.deleted: "deleted",
            Change.modified: "modified",
        }

        logger.debug("fs_watcher_started workspace={}", workspace)

        try:
            async for changes in awatch(
                workspace_str,
                debounce=self._debounce_ms,
                recursive=True,
                watch_filter=_watch_filter,
            ):
                # Convert watchfiles changes to event dicts
                events: list[FsChangeEvent] = []
                for change_type, raw_path in changes:
                    # Fast relative path via string slicing (no Path alloc)
                    rel = raw_path[prefix_len:].replace("\\", "/")
                    if not rel:
                        continue
                    events.append(
                        {
                            "type": change_map.get(change_type, "modified"),
                            "path": rel,
                        }
                    )

                if not events:
                    continue

                # Snapshot subscribers under lock, then fan-out without holding it
                async with self._lock:
                    subs = list(self._subscribers.get(workspace, []))
                    cbs = list(self._callbacks.get(workspace, []))

                # Queue fan-out (non-blocking put)
                dead: list[asyncio.Queue[Any]] = []
                for q in subs:
                    try:
                        q.put_nowait(events)
                    except asyncio.QueueFull:
                        dead.append(q)

                if dead:
                    async with self._lock:
                        live = self._subscribers.get(workspace, [])
                        for q in dead:
                            try:
                                live.remove(q)
                            except ValueError:
                                pass

                # Fire callbacks concurrently (one slow callback won't block others)
                if cbs:
                    results = await asyncio.gather(
                        *(cb(workspace, events) for cb in cbs),
                        return_exceptions=True,
                    )
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.warning(
                                "fs_watcher_callback_error workspace={} err={}",
                                workspace,
                                result,
                            )

        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("fs_watcher_error workspace={} err={}", workspace, exc)
        finally:
            logger.debug("fs_watcher_stopped workspace={}", workspace)


# Singleton instance — shared across the application
workspace_file_watcher = WorkspaceFileWatcher()
