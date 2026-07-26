"""In-memory registry of in-progress code-graph index jobs.

Reindexing runs as a detached background task so it survives the HTTP request
that started it — a browser reload no longer aborts or "loses" an in-flight
index. ``GET /status`` reads this registry so the UI can re-show "Indexing…"
after a reload and surface the last error if one occurred.

State is process-local and intentionally not persisted: a job cannot outlive a
server restart anyway, and after a restart "not indexing" is the correct view.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from uuid import UUID

from loguru import logger

from app.core.db import DbFactory, resolve_db_factory

# Type for the progress callback used by reindex_workspace.
ProgressCallback = Callable[[str, float, str], None]


class _LazyCodeGraphService:
    def __init__(self) -> None:
        self._service: Any | None = None

    def __getattr__(self, name: str) -> Any:
        if self._service is None:
            self._service = import_module("app.services.code_graph_service")
        return getattr(self._service, name)


svc = _LazyCodeGraphService()


def _make_progress_cb(job: IndexJob) -> ProgressCallback:
    """Return a callback that updates the IndexJob progress fields."""

    def _cb(phase: str, progress: float, message: str) -> None:
        job.phase = phase
        job.progress = progress
        job.message = message

    return _cb


@dataclass(slots=True)
class IndexJob:
    """Snapshot of a single workspace reindex run."""

    workspace_id: str
    full: bool
    started_at: float
    status: str = "running"  # running | done | error
    finished_at: float | None = None
    error: str | None = None
    # Progress tracking
    phase: str = "starting"  # starting | parsing | saving | embedding | done
    progress: float = 0.0  # 0.0 – 1.0
    message: str = ""


class IndexJobRegistry:
    """Tracks at most one running index job per workspace."""

    def __init__(self) -> None:
        self._jobs: dict[str, IndexJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        workspace_id: UUID,
        root_path: str,
        languages: list[str] | None,
        full: bool,
        db_factory: DbFactory | None = None,
    ) -> tuple[IndexJob, bool]:
        """Start a background reindex for ``workspace_id``.

        Returns ``(job, started)``; ``started`` is ``False`` when a job was
        already running for this workspace (the existing job is returned).
        """
        key = str(workspace_id)
        async with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.status == "running":
                return existing, False
            job = IndexJob(workspace_id=key, full=full, started_at=time.time())
            self._jobs[key] = job
            task = asyncio.create_task(
                self._run(
                    job=job,
                    workspace_id=workspace_id,
                    root_path=root_path,
                    languages=languages,
                    full=full,
                    db_factory=db_factory,
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return job, True

    async def _run(
        self,
        *,
        job: IndexJob,
        workspace_id: UUID,
        root_path: str,
        languages: list[str] | None,
        full: bool,
        db_factory: DbFactory | None,
    ) -> None:
        factory = resolve_db_factory(db_factory)
        try:
            async with factory() as db:
                await svc.reindex_workspace(
                    db,
                    workspace_id=workspace_id,
                    root_path=root_path,
                    languages=languages,
                    incremental=not full,
                    progress_cb=_make_progress_cb(job),
                )
            job.status = "done"
            job.phase = "done"
            job.progress = 1.0
            job.message = ""
            job.error = None
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI via status
            job.status = "error"
            job.error = str(exc)
            logger.exception(
                "code_graph index job failed workspace={}", job.workspace_id
            )
        finally:
            job.finished_at = time.time()

    def snapshot(self, workspace_id: UUID) -> IndexJob | None:
        """Return the most recent job for ``workspace_id`` (or ``None``)."""
        return self._jobs.get(str(workspace_id))

    def is_running(self, workspace_id: UUID) -> bool:
        job = self._jobs.get(str(workspace_id))
        return job is not None and job.status == "running"


index_jobs = IndexJobRegistry()
