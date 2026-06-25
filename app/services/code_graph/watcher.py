"""Filesystem watcher that keeps the code graph fresh.

Subscribes to the unified ``WorkspaceFileWatcher`` and runs incremental
re-indexing whenever indexable source files change on disk. The single
filesystem watcher is shared with SSE subscribers so only one ``awatch``
loop exists per workspace.

Opt-in via ``code_graph.watch_enabled`` (default off). The watcher degrades
gracefully: a transient reindex error is logged, never raised.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.core.runtime_settings import load_runtime_settings
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph_service import reindex_workspace, resolve_workspace_id
from app.services.coding_workspace_service import list_visible_coding_workspaces
from app.services.workspace_file_watcher import (
    FsChangeEvent,
    workspace_file_watcher,
)

if TYPE_CHECKING:
    from app.core.db import DbFactory


class CodeGraphWatcher:
    """Background subscriber that incrementally reindexes workspaces on file changes."""

    def __init__(self, db_factory: DbFactory) -> None:
        self._db_factory = db_factory
        self._watched_workspaces: list[str] = []
        self._extensions: set[str] = set()
        self._lock = asyncio.Lock()
        # Debounce reindex per workspace
        self._debounce_tasks: dict[str, asyncio.Task[None]] = {}

    async def start(self) -> bool:
        """Subscribe to the shared watcher for all visible workspaces.

        Returns ``True`` if subscribed successfully, ``False`` if nothing to watch.
        """
        async with self._lock:
            if self._watched_workspaces:
                return True  # already running

            paths = await self._workspace_paths()
            if not paths:
                logger.info("code_graph_watcher_no_workspaces")
                return False

            self._extensions = set(default_registry().supported_extensions())
            settings = load_runtime_settings()
            # Use code_graph debounce for reindex batching
            self._reindex_debounce_ms = settings.code_graph.watch_debounce_ms

            self._watched_workspaces = [str(p) for p in paths]
            await workspace_file_watcher.add_callback_many(
                self._watched_workspaces, self._on_change
            )
            logger.info(
                "code_graph_watcher_started workspaces={}", len(self._watched_workspaces)
            )
            return True

    async def stop(self) -> None:
        """Unsubscribe from the shared watcher."""
        async with self._lock:
            if not self._watched_workspaces:
                return
            await workspace_file_watcher.remove_callback_many(
                self._watched_workspaces, self._on_change
            )
            # Cancel pending debounce tasks
            for task in self._debounce_tasks.values():
                task.cancel()
            self._debounce_tasks.clear()
            self._watched_workspaces = []

    async def _on_change(
        self, workspace: str, events: list[FsChangeEvent]
    ) -> None:
        """Callback from WorkspaceFileWatcher — filter and debounce reindex."""
        # Fast extension check via str ops (avoid Path allocation per event)
        extensions = self._extensions
        has_source = any(
            _suffix(e["path"]) in extensions for e in events
        )
        if not has_source:
            return

        # Debounce: cancel any pending reindex for this workspace, reschedule
        existing = self._debounce_tasks.get(workspace)
        if existing and not existing.done():
            existing.cancel()
        self._debounce_tasks[workspace] = asyncio.create_task(
            self._debounced_reindex(workspace)
        )

    async def _debounced_reindex(self, workspace: str) -> None:
        """Wait for the debounce window then perform incremental reindex."""
        try:
            await asyncio.sleep(self._reindex_debounce_ms / 1000.0)
        except asyncio.CancelledError:
            return  # superseded by a newer event batch
        await self._reindex(workspace)

    async def _reindex(self, workspace: str) -> None:
        try:
            async with self._db_factory() as db:
                workspace_id = await resolve_workspace_id(db, path=workspace)
                if workspace_id is None:
                    return
                stats = await reindex_workspace(
                    db,
                    workspace_id=workspace_id,
                    root_path=workspace,
                    incremental=True,
                )
            logger.info(
                "code_graph_watcher_reindexed workspace={} changed={} deleted={}",
                workspace,
                stats.changed_files,
                stats.deleted_files,
            )
        except Exception as exc:  # noqa: BLE001 — one bad reindex shouldn't stop watching
            logger.error(
                "code_graph_watcher_reindex_failed workspace={} err={}",
                workspace,
                exc,
            )

    async def _workspace_paths(self) -> list[Path]:
        async with self._db_factory() as db:
            workspaces = await list_visible_coding_workspaces(db)
        return [Path(w.path) for w in workspaces if Path(w.path).is_dir()]


def _suffix(path: str) -> str:
    """Extract lowercase file extension without Path allocation."""
    dot = path.rfind(".")
    if dot == -1 or "/" in path[dot:]:
        return ""
    return path[dot:].lower()
