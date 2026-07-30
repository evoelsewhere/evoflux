"""Filesystem watcher that keeps the code graph fresh.

Subscribes to the unified ``WorkspaceFileWatcher`` and runs incremental
re-indexing whenever indexable source files change on disk. The single
filesystem watcher is shared with SSE subscribers so only one ``awatch``
loop exists per workspace.

Scope: only workspaces reachable by an existing session are watched — see
``list_workspace_paths_with_sessions``. At boot this covers every
project/workspace someone has already opened; ``watch_paths()`` extends the
set on demand when a new session is resolved for a workspace/project that
had none yet (``resolve_team_session``), so a repo only starts being watched
once it's actually used, not merely registered.

Gated by ``code_graph.watch_enabled`` (default on). The watcher degrades
gracefully: a transient reindex error is logged, never raised.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.core.runtime_settings import load_runtime_settings
from app.services.code_graph.cross_repo_jobs import cross_repo_jobs
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph_service import reindex_workspace, resolve_workspace_id
from app.services.coding_project_service import (
    get_project_workspaces,
    get_projects_for_workspace,
)
from app.services.coding_workspace_service import list_workspace_paths_with_sessions
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
        # Pause/resume support: when paused, events accumulate but don't trigger reindex.
        self._pause_count: int = 0
        self._dirty_workspaces: set[str] = set()
        # Per-workspace reindex serialization: prevents concurrent reindexes
        # from piling up CPU/RAM when many files change in quick succession.
        self._reindex_locks: dict[str, asyncio.Lock] = {}
        self._reindex_pending: set[str] = set()

    async def start(self) -> bool:
        """Subscribe to the shared watcher for every workspace with a session.

        Returns ``True`` if subscribed successfully, ``False`` if nothing to watch.
        """
        if self._watched_workspaces:
            return True  # already running

        paths = await self._workspace_paths()
        if not paths:
            logger.info("code_graph_watcher_no_workspaces")
            return False
        return await self.watch_paths([str(p) for p in paths])

    async def watch_paths(self, paths: list[str]) -> bool:
        """Idempotently add *paths* to the watch set.

        Safe to call at any time — e.g. when a session is resolved for a
        workspace or project that isn't watched yet. Already-watched paths
        are skipped; no-op (returns ``False``) if the feature is disabled.
        """
        settings = load_runtime_settings()
        if not settings.code_graph.watch_enabled:
            return False

        async with self._lock:
            if not self._extensions:
                self._extensions = set(default_registry().supported_extensions())
                # Use code_graph debounce for reindex batching
                self._reindex_debounce_ms = settings.code_graph.watch_debounce_ms

            new_paths = [
                p
                for p in paths
                if p not in self._watched_workspaces and Path(p).is_dir()
            ]
            if not new_paths:
                return bool(self._watched_workspaces)

            self._watched_workspaces.extend(new_paths)
            await workspace_file_watcher.add_callback_many(new_paths, self._on_change)
            logger.info(
                "code_graph_watcher_started workspaces={} new={}",
                len(self._watched_workspaces),
                len(new_paths),
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
            # Reset pause state so a subsequent start() begins clean
            self._pause_count = 0
            self._dirty_workspaces.clear()

    async def pause(self) -> None:
        """Pause reindexing. Events still accumulate; reindex deferred until resume.

        Supports nested pause/resume (reference counted). Each ``pause()`` must
        be balanced by a ``resume()``.
        """
        async with self._lock:
            self._pause_count += 1
            if self._pause_count == 1:
                # Cancel any pending debounce tasks — work will be done on resume
                for task in self._debounce_tasks.values():
                    task.cancel()
                self._debounce_tasks.clear()
                logger.info("code_graph_watcher_paused")

    async def resume(self) -> None:
        """Resume reindexing after a pause. Triggers a single batched reindex
        for every workspace that accumulated changes while paused, after a
        settling delay (``watch_resume_delay_ms``) so late file-system events
        from the agent's final writes get coalesced into the same pass.
        """
        async with self._lock:
            if self._pause_count <= 0:
                return
            self._pause_count -= 1
            if self._pause_count > 0:
                return  # still paused by another caller
            dirty = list(self._dirty_workspaces)
            self._dirty_workspaces.clear()

        logger.info("code_graph_watcher_resumed dirty_workspaces={}", len(dirty))
        if not dirty:
            return
        # Schedule reindex after a settling delay — new events arriving during
        # the delay are handled normally by _on_change (watcher is unpaused now)
        # and will debounce into the same or a subsequent pass.
        settings = load_runtime_settings()
        delay_s = settings.code_graph.watch_resume_delay_ms / 1000.0
        for workspace in dirty:
            self._debounce_tasks[workspace] = asyncio.create_task(
                self._delayed_reindex(workspace, delay_s)
            )

    @property
    def is_paused(self) -> bool:
        """Whether the watcher is currently paused."""
        return self._pause_count > 0

    async def _on_change(self, workspace: str, events: list[FsChangeEvent]) -> None:
        """Callback from WorkspaceFileWatcher — filter and debounce reindex."""
        # Fast extension check via str ops (avoid Path allocation per event)
        extensions = self._extensions
        has_source = any(_suffix(e["path"]) in extensions for e in events)
        if not has_source:
            return

        # When paused, just mark the workspace dirty — no reindex until resume
        if self._pause_count > 0:
            self._dirty_workspaces.add(workspace)
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

    async def _delayed_reindex(self, workspace: str, delay_s: float) -> None:
        """Wait for a settling delay then perform incremental reindex.

        Used after agent-run resume to let final writes land before reindexing.
        If a new event cancels this task (via _on_change debounce), the normal
        debounce path takes over — no work is lost.
        """
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
        await self._reindex(workspace)

    async def _reindex(self, workspace: str) -> None:
        # Skip if an API-triggered reindex job is already running for this workspace.
        from app.services.code_graph.jobs import index_jobs

        ws_lock = self._reindex_locks.setdefault(workspace, asyncio.Lock())

        if ws_lock.locked():
            # Another watcher-triggered reindex is in progress — mark pending
            # so it re-runs once more after the current pass finishes.
            self._reindex_pending.add(workspace)
            return

        async with ws_lock:
            # Inner loop: run at most twice (once for the current batch, once
            # more if new events arrived while the first pass was running).
            while True:
                self._reindex_pending.discard(workspace)
                try:
                    async with self._db_factory() as db:
                        workspace_id = await resolve_workspace_id(db, path=workspace)
                        if workspace_id is None:
                            return
                        # Skip if the API-triggered background job is running
                        if index_jobs.is_running(workspace_id):
                            logger.debug(
                                "code_graph_watcher_skip_job_running workspace={}",
                                workspace,
                            )
                            return
                        stats = await reindex_workspace(
                            db,
                            workspace_id=workspace_id,
                            root_path=workspace,
                            incremental=True,
                        )

                        # Chain into cross-repo resolve for every multi-repo
                        # project this workspace belongs to — mirrors what the
                        # manual reindex endpoint already does
                        # (reindex_project_code_graph), now that a full resolve
                        # pass is cheap enough (~15-20s on a real 4-repo,
                        # 40k-node project, was hours before the Tier
                        # A/reattach fixes) to run after every incremental
                        # reindex instead of only on an explicit click.
                        # cross_repo_jobs.start() is idempotent per project
                        # (a no-op if a resolve is already running for it), so
                        # firing it here on every save is safe even when
                        # several repos in the same project are edited in
                        # quick succession. Skipped when nothing actually
                        # changed — a debounced no-op reindex can't have
                        # introduced a new unresolved reference.
                        if stats.changed_files or stats.deleted_files:
                            for project_id in await get_projects_for_workspace(
                                db, workspace_id
                            ):
                                pairs = await get_project_workspaces(db, project_id)
                                if len(pairs) > 1:
                                    await cross_repo_jobs.start(project_id=project_id)
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
                    # Don't retry immediately on error — the next file-change
                    # event will schedule a fresh attempt via normal debounce.
                    self._reindex_pending.discard(workspace)
                    break

                # If no new events arrived during this pass, we're done.
                if workspace not in self._reindex_pending:
                    break

    async def _workspace_paths(self) -> list[Path]:
        async with self._db_factory() as db:
            paths = await list_workspace_paths_with_sessions(db)
        return [Path(p) for p in paths if Path(p).is_dir()]


def _suffix(path: str) -> str:
    """Extract lowercase file extension without Path allocation."""
    dot = path.rfind(".")
    if dot == -1 or "/" in path[dot:]:
        return ""
    return path[dot:].lower()


# Module-level reference set by the lifespan to allow hooks (e.g. IndexPauseHook)
# to access the watcher without importing app.state or FastAPI.
_global_watcher: CodeGraphWatcher | None = None


def set_global_watcher(watcher: CodeGraphWatcher) -> None:
    """Register the watcher instance for module-level access."""
    global _global_watcher  # noqa: PLW0603
    _global_watcher = watcher
