"""Filesystem watcher that keeps the code graph fresh.

Watches every visible coding workspace and runs an *incremental* re-index
whenever indexable source files change on disk. Bursts of events are coalesced
by ``watchfiles``' built-in debounce so a "save all" only triggers one reindex
per workspace.

Opt-in via ``code_graph.watch_enabled`` (default off). The watcher degrades
gracefully: a missing ``watchfiles`` install or a transient reindex error is
logged, never raised, so it can't take the server down.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from app.core.runtime_settings import load_runtime_settings
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph_service import reindex_workspace, resolve_workspace_id
from app.services.coding_workspace_service import list_visible_coding_workspaces

if TYPE_CHECKING:
    from app.core.db import DbFactory


class CodeGraphWatcher:
    """Background task that incrementally reindexes workspaces on file changes."""

    def __init__(self, db_factory: DbFactory) -> None:
        self._db_factory = db_factory
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> bool:
        """Start watching all visible workspaces. Idempotent.

        Returns ``True`` if a watch loop is running afterwards, ``False`` if
        there was nothing to watch or ``watchfiles`` is unavailable.
        """
        async with self._lock:
            if self._task is not None and not self._task.done():
                return True
            paths = await self._workspace_paths()
            if not paths:
                logger.info("code_graph_watcher_no_workspaces")
                return False
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(
                self._run(paths), name="code-graph-watcher"
            )
            logger.info("code_graph_watcher_started workspaces={}", len(paths))
            return True

    async def stop(self) -> None:
        """Signal the watch loop to exit and wait briefly for it to finish."""
        async with self._lock:
            if self._stop is not None:
                self._stop.set()
            task = self._task
            self._task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            logger.warning("code_graph_watcher_stop_error err={}", exc)

    async def _workspace_paths(self) -> list[Path]:
        async with self._db_factory() as db:
            workspaces = await list_visible_coding_workspaces(db)
        return [Path(w.path) for w in workspaces if Path(w.path).is_dir()]

    async def _run(self, paths: list[Path]) -> None:
        try:
            from watchfiles import awatch
        except Exception as exc:  # noqa: BLE001 — optional native dep
            logger.warning("code_graph_watcher_unavailable err={}", exc)
            return

        extensions = default_registry().supported_extensions()
        debounce = load_runtime_settings().code_graph.watch_debounce_ms

        def _is_source(_change: object, path: str) -> bool:
            return Path(path).suffix.lower() in extensions

        try:
            async for changes in awatch(
                *[str(p) for p in paths],
                watch_filter=_is_source,
                debounce=debounce,
                stop_event=self._stop,
            ):
                for workspace in self._affected_workspaces(changes, paths):
                    await self._reindex(workspace)
        except Exception as exc:  # noqa: BLE001 — never let the loop kill startup
            logger.error("code_graph_watcher_loop_error err={}", exc)

    @staticmethod
    def _affected_workspaces(
        changes: Iterable[tuple[object, str]], paths: list[Path]
    ) -> list[Path]:
        hit: list[Path] = []
        for _change, raw in changes:
            changed = Path(raw)
            for workspace in paths:
                if workspace in hit:
                    continue
                if _is_within(changed, workspace):
                    hit.append(workspace)
        return hit

    async def _reindex(self, workspace: Path) -> None:
        try:
            async with self._db_factory() as db:
                workspace_id = await resolve_workspace_id(db, path=str(workspace))
                if workspace_id is None:
                    return
                stats = await reindex_workspace(
                    db,
                    workspace_id=workspace_id,
                    root_path=str(workspace),
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


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
