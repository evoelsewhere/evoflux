"""In-memory registry of in-progress cross-repo resolution jobs.

Mirrors ``jobs.py``'s ``IndexJobRegistry`` shape and lifecycle, but keyed by
``project_id`` instead of ``workspace_id`` — a resolution pass spans every
repo in a project, not a single workspace, so it doesn't fit that registry's
one-job-per-workspace design. State is process-local, same as index jobs: a
job cannot outlive a server restart, and after one "not running" is correct.

Every run goes through this registry: Tier 0 (reattach), Tier A (static),
and Tier B (FTS5 lexical) all run together as a background job so the route
stays fast regardless of project size.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass
from uuid import UUID

from loguru import logger

from app.core.db import DbFactory, resolve_db_factory
from app.services.code_graph.cross_repo import CrossRepoResolveStats, resolve_project
from app.services.code_graph.cross_repo_llm import resolve_project_tier_b
from app.services.code_graph.jobs import index_jobs


@dataclass(slots=True)
class CrossRepoResolveJob:
    """Snapshot of a single project's cross-repo resolution run."""

    project_id: str
    started_at: float
    status: str = "running"  # running | done | error
    finished_at: float | None = None
    error: str | None = None
    phase: str = "starting"  # starting | indexing | reattach | static | lexical | done
    progress: float = 0.0
    message: str = ""
    stats: dict | None = None


class CrossRepoResolveJobRegistry:
    """Tracks at most one running resolution job per project."""

    def __init__(self) -> None:
        self._jobs: dict[str, CrossRepoResolveJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        project_id: UUID,
        db_factory: DbFactory | None = None,
        wait_for_workspaces: list[UUID] | None = None,
        changed_workspaces: set[UUID] | None = None,
    ) -> tuple[CrossRepoResolveJob, bool]:
        """Start a background resolution pass for ``project_id``.

        ``wait_for_workspaces``, when given, is a set of workspaces the job
        should sit and wait on (polling ``index_jobs.is_running``) before
        touching the database — used to chain a resolve pass onto an
        in-flight project-wide reindex without resolving against half-parsed
        repos. The job is registered as ``running`` immediately either way,
        so ``GET .../cross-repo/status`` never has a gap between "reindex
        accepted" and "resolve actually starts" where a poller could
        mistake "hasn't started yet" for "already finished".

        ``changed_workspaces``, when given, enables incremental resolution —
        only edges involving those workspaces are re-resolved. This avoids
        redundant work when only some repos in a project have changed.

        Returns ``(job, started)``; ``started`` is ``False`` when a job was
        already running for this project (the existing job is returned).
        """
        key = str(project_id)
        async with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.status == "running":
                return existing, False
            job = CrossRepoResolveJob(
                project_id=key,
                started_at=time.time(),
            )
            self._jobs[key] = job
            task = asyncio.create_task(
                self._run(
                    job=job,
                    project_id=project_id,
                    db_factory=db_factory,
                    wait_for_workspaces=wait_for_workspaces,
                    changed_workspaces=changed_workspaces,
                )
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return job, True

    async def _run(
        self,
        *,
        job: CrossRepoResolveJob,
        project_id: UUID,
        db_factory: DbFactory | None,
        wait_for_workspaces: list[UUID] | None = None,
        changed_workspaces: set[UUID] | None = None,
    ) -> None:
        factory = resolve_db_factory(db_factory)
        try:
            if wait_for_workspaces:
                job.phase = "indexing"
                job.message = "Waiting for repos to finish indexing…"
                while any(index_jobs.is_running(wid) for wid in wait_for_workspaces):
                    await asyncio.sleep(0.5)

            job.phase = "reattach"
            job.progress = 0.0
            job.message = "Re-attaching stale links…"
            async with factory() as db:
                stats: CrossRepoResolveStats = await resolve_project(
                    db, project_id=project_id, changed_workspaces=changed_workspaces
                )

            job.phase = "static"
            job.progress = 0.33
            job.message = f"{stats.static_resolved} resolved statically"
            job.stats = asdict(stats)

            job.phase = "lexical"
            job.progress = 0.5
            job.message = "Narrowing remaining references…"
            async with factory() as db:
                tier_b = await resolve_project_tier_b(db, project_id=project_id)
            merged = CrossRepoResolveStats(
                reattached=stats.reattached,
                static_resolved=stats.static_resolved,
                lexical_resolved=tier_b.lexical_resolved,
                still_unresolved=max(
                    0,
                    stats.still_unresolved - tier_b.lexical_resolved,
                ),
                capped=tier_b.capped,
            )
            job.stats = asdict(merged)
            job.progress = 0.9
            job.message = f"{tier_b.lexical_resolved} resolved by lexical match" + (
                f" ({tier_b.capped} deferred to next run)" if tier_b.capped else ""
            )

            job.status = "done"
            job.phase = "done"
            job.progress = 1.0
            job.message = ""
            job.error = None
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI via status
            job.status = "error"
            job.error = str(exc)
            logger.exception("cross_repo resolve job failed project={}", job.project_id)
        finally:
            job.finished_at = time.time()

    def snapshot(self, project_id: UUID) -> CrossRepoResolveJob | None:
        """Return the most recent job for ``project_id`` (or ``None``)."""
        return self._jobs.get(str(project_id))

    def is_running(self, project_id: UUID) -> bool:
        job = self._jobs.get(str(project_id))
        return job is not None and job.status == "running"


cross_repo_jobs = CrossRepoResolveJobRegistry()
