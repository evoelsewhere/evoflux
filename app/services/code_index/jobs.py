"""In-process coordination for user-triggered code-index refresh jobs."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, replace

from app.services.code_index.project import IndexProgress, RepositoryIndex


@dataclass(frozen=True, slots=True)
class RepositoryIndexJob:
    """UI-facing state for one repository in a project refresh."""

    indexing: bool = False
    phase: str | None = None
    progress: float | None = None
    message: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectIndexStart:
    indexing: bool
    repo_count: int
    already_running: int
    full: bool


class ProjectIndexJobCoordinator:
    """Own background refresh tasks and expose thread-safe progress snapshots.

    ``RepositoryIndex`` invokes progress callbacks from its worker executor, so
    state updates must not rely on the request event loop. Jobs are deliberately
    regeneratable and process-local: a server restart simply clears progress;
    the repository indexes themselves remain intact on disk.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._states: dict[str, dict[str, RepositoryIndexJob]] = {}

    def snapshot(self, project_id: str) -> dict[str, RepositoryIndexJob]:
        with self._lock:
            return dict(self._states.get(project_id, {}))

    def start(
        self,
        project_id: str,
        repositories: tuple[tuple[str, RepositoryIndex], ...],
        *,
        full: bool,
    ) -> ProjectIndexStart:
        with self._lock:
            current = self._tasks.get(project_id)
            if current is not None and not current.done():
                return ProjectIndexStart(
                    indexing=True,
                    repo_count=len(repositories),
                    already_running=len(repositories),
                    full=full,
                )
            self._states[project_id] = {
                label: RepositoryIndexJob(
                    indexing=True,
                    phase="queued",
                    progress=0.0,
                    message="Waiting to scan repository",
                )
                for label, _index in repositories
            }
            task = asyncio.create_task(
                self._run(project_id, repositories, full=full),
                name=f"code-index-project-{project_id}",
            )
            self._tasks[project_id] = task
        return ProjectIndexStart(
            indexing=bool(repositories),
            repo_count=len(repositories),
            already_running=0,
            full=full,
        )

    def _update(self, project_id: str, label: str, **changes: object) -> None:
        with self._lock:
            state = self._states.setdefault(project_id, {}).get(label)
            if state is None:
                return
            self._states[project_id][label] = replace(state, **changes)

    async def _run_repository(
        self,
        project_id: str,
        label: str,
        index: RepositoryIndex,
        *,
        full: bool,
    ) -> None:
        def progress(value: IndexProgress) -> None:
            self._update(
                project_id,
                label,
                indexing=value.progress < 1.0,
                phase=value.phase,
                progress=value.progress,
                message=value.message,
                error=None,
            )

        try:
            await index.update(full=full, progress=progress)
        except asyncio.CancelledError:
            self._update(
                project_id,
                label,
                indexing=False,
                phase="cancelled",
                message="Index refresh cancelled",
            )
            raise
        except Exception as exc:
            self._update(
                project_id,
                label,
                indexing=False,
                phase="failed",
                message="Index refresh failed",
                error=str(exc),
            )
        else:
            self._update(
                project_id,
                label,
                indexing=False,
                phase="ready",
                progress=1.0,
                message="Repository index is ready",
            )

    async def _run(
        self,
        project_id: str,
        repositories: tuple[tuple[str, RepositoryIndex], ...],
        *,
        full: bool,
    ) -> None:
        try:
            await asyncio.gather(
                *(
                    self._run_repository(
                        project_id,
                        label,
                        index,
                        full=full,
                    )
                    for label, index in repositories
                )
            )
        finally:
            with self._lock:
                current = self._tasks.get(project_id)
                if current is asyncio.current_task():
                    self._tasks.pop(project_id, None)


project_index_jobs = ProjectIndexJobCoordinator()


__all__ = [
    "ProjectIndexJobCoordinator",
    "ProjectIndexStart",
    "RepositoryIndexJob",
    "project_index_jobs",
]
