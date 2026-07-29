"""Automatic projection rebuilds for AIM knowledge-base changes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from loguru import logger
from sqlmodel import select

from app.models.chat import CodingProject
from app.services.aim.project import resolve_kb_workspace_path
from app.services.aim.reindex import reindex_project
from app.services.workspace_file_watcher import FsChangeEvent, workspace_file_watcher


class AimIndexWatcher:
    def __init__(self, *, db_factory, debounce_ms: int = 750) -> None:  # noqa: ANN001
        self._db_factory = db_factory
        self._debounce_s = debounce_ms / 1000
        self._projects: dict[str, UUID] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def is_relevant(path: str) -> bool:
        normalized = path.replace("\\", "/")
        return normalized == "aim.yaml" or normalized.startswith(
            ("modules/", "runs/", "state/")
        )

    async def start(self) -> None:
        async with self._db_factory() as db:
            projects = (
                await db.exec(select(CodingProject).where(CodingProject.kind == "aim"))
            ).all()
            registrations: list[tuple[UUID, str]] = []
            for project in projects:
                kb_path = await resolve_kb_workspace_path(db, project)
                if kb_path:
                    registrations.append((project.id, kb_path))
        for project_id, kb_path in registrations:
            await self.watch_project(project_id, kb_path)

    async def watch_project(self, project_id: UUID, kb_path: str) -> bool:
        resolved = str(Path(kb_path).resolve())
        if not Path(resolved).is_dir():
            return False
        async with self._lock:
            already_watched = resolved in self._projects
            self._projects[resolved] = project_id
            if already_watched:
                return True
            await workspace_file_watcher.add_callback(resolved, self._on_change)
        logger.debug("aim_index_watcher_started project={} kb={}", project_id, resolved)
        return True

    async def stop(self) -> None:
        async with self._lock:
            paths = list(self._projects)
            self._projects.clear()
            for task in self._tasks.values():
                task.cancel()
            self._tasks.clear()
        for path in paths:
            await workspace_file_watcher.remove_callback(path, self._on_change)

    async def _on_change(self, workspace: str, events: list[FsChangeEvent]) -> None:
        if not any(self.is_relevant(event["path"]) for event in events):
            return
        existing = self._tasks.get(workspace)
        if existing is not None and not existing.done():
            existing.cancel()
        self._tasks[workspace] = asyncio.create_task(
            self._delayed_reindex(workspace), name=f"aim-reindex:{workspace}"
        )

    async def _delayed_reindex(self, workspace: str) -> None:
        try:
            await asyncio.sleep(self._debounce_s)
        except asyncio.CancelledError:
            return
        project_id = self._projects.get(workspace)
        if project_id is not None:
            await self.reindex_now(project_id, workspace)

    async def reindex_now(self, project_id: UUID, kb_path: str) -> None:
        try:
            async with self._db_factory() as db:
                result = await reindex_project(db, project_id, Path(kb_path))
                await db.commit()
            logger.debug(
                "aim_index_watcher_reindexed project={} created={} updated={} "
                "invalid={} runs_created={} links_created={}",
                project_id,
                result.created,
                result.updated,
                result.invalid,
                result.runs_created,
                result.links_created,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "aim_index_watcher_reindex_failed project={} kb={} error={}",
                project_id,
                kb_path,
                exc,
            )


_global_aim_watcher: AimIndexWatcher | None = None


def set_global_aim_watcher(watcher: AimIndexWatcher) -> None:
    global _global_aim_watcher
    _global_aim_watcher = watcher
