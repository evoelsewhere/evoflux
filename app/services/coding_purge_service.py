"""Destructive cleanup for removed Coding workspaces and projects.

Repository source directories are user-owned and are never deleted. The
service removes app-owned session state, database records, managed worktrees,
and regeneratable code-index/graph caches so reopening starts cleanly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, or_, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.artifacts import session_artifact_dir
from app.agent.sandbox_config import managed_worktree_roots
from app.artifacts.service import get_artifact_service
from app.artifacts.storage import ArtifactStore
from app.core.logging_config import SESSION_LOG_DIR, remove_session_sink
from app.core.paths import workspace_dir
from app.models.artifact import ArtifactJob, ArtifactReview, ArtifactRevision
from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
    CodingWorkspace,
    DreamLog,
    GitServerConnection,
    SessionMessage,
)
from app.models.goal import SessionGoal
from app.models.team import DelegationTask
from app.models.webbridge import (
    WebBridgeInteraction,
    WebBridgeTabBinding,
    WebBridgeTeachDraft,
    WebBridgeTeachReplay,
)
from app.models.workflow import (
    WorkflowExecution,
    WorkflowGateRequest,
    WorkflowNodeRun,
)
from app.scheduler.models import ScheduledTask
from app.scheduler.scheduler import task_scheduler
from app.services import agent_service, memory_stream_store, team_manager
from app.services.code_index.jobs import project_index_jobs
from app.services.code_index.project import repository_indexes
from app.services.snapshot_service import snapshot_dir
from app.services.terminal_service import terminal_manager
from app.workflow.runner import runner as workflow_runner


class PurgeConflictError(ValueError):
    """The requested standalone purge would destroy project-owned state."""


@dataclass(frozen=True, slots=True)
class SessionFiles:
    session_ids: tuple[UUID, ...] = ()
    artifact_job_ids: tuple[UUID, ...] = ()
    artifact_revision_ids: tuple[UUID, ...] = ()
    orphan_blob_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PurgeResult:
    session_count: int
    repository_paths: tuple[str, ...]


async def _session_closure(
    db: AsyncSession, seed_ids: set[UUID]
) -> tuple[ChatSession, ...]:
    if not seed_ids:
        return ()
    sessions = list((await db.exec(select(ChatSession))).all())
    selected = set(seed_ids)
    changed = True
    while changed:
        changed = False
        for session in sessions:
            if session.id in selected:
                continue
            if (
                session.parent_session_id in selected
                or session.source_session_id in selected
                or session.source_session_ref in selected
            ):
                selected.add(session.id)
                changed = True
    return tuple(session for session in sessions if session.id in selected)


async def _stop_session_runtime(session_ids: set[UUID]) -> None:
    if not session_ids:
        return
    string_ids = {str(session_id) for session_id in session_ids}
    await team_manager.stop_sessions(string_ids)
    await get_artifact_service().cancel_for_sessions(session_ids)
    for session_id in string_ids:
        agent_service.cancel_deferred_user_message(session_id)
        state = workflow_runner.active.get(session_id)
        if state is not None:
            await workflow_runner.stop(state.execution_id)
        for terminal_id in terminal_manager.list_terminals(session_id):
            await terminal_manager.close(session_id, terminal_id=terminal_id)
        await memory_stream_store.clear(session_id)


async def _purge_session_rows(
    db: AsyncSession,
    sessions: tuple[ChatSession, ...],
    *,
    delete_scheduled_tasks: bool,
) -> SessionFiles:
    session_ids: set[UUID] = {session.id for session in sessions}
    if not session_ids:
        return SessionFiles()

    artifact_jobs = list(
        (
            await db.exec(
                select(ArtifactJob).where(col(ArtifactJob.session_id).in_(session_ids))
            )
        ).all()
    )
    job_ids: set[UUID] = {job.id for job in artifact_jobs}
    revisions = (
        list(
            (
                await db.exec(
                    select(ArtifactRevision).where(
                        col(ArtifactRevision.job_id).in_(job_ids)
                    )
                )
            ).all()
        )
        if job_ids
        else []
    )
    revision_ids: set[UUID] = {revision.id for revision in revisions}
    blob_keys = {revision.blob_key for revision in revisions}
    referenced_keys: set[str] = set()
    if blob_keys:
        referenced_keys = set(
            (
                await db.exec(
                    select(ArtifactRevision.blob_key).where(
                        col(ArtifactRevision.blob_key).in_(blob_keys),
                        ~col(ArtifactRevision.job_id).in_(job_ids),
                    )
                )
            ).all()
        )

    executions = list(
        (
            await db.exec(
                select(WorkflowExecution).where(
                    col(WorkflowExecution.session_id).in_(session_ids)
                )
            )
        ).all()
    )
    execution_ids = {execution.id for execution in executions}
    drafts = list(
        (
            await db.exec(
                select(WebBridgeTeachDraft).where(
                    col(WebBridgeTeachDraft.session_id).in_(session_ids)
                )
            )
        ).all()
    )
    draft_ids = {draft.id for draft in drafts}

    if revision_ids:
        await db.exec(
            delete(ArtifactReview).where(
                col(ArtifactReview.revision_id).in_(revision_ids)
            )
        )
        await db.exec(
            delete(ArtifactRevision).where(col(ArtifactRevision.id).in_(revision_ids))
        )
    if job_ids:
        await db.exec(delete(ArtifactJob).where(col(ArtifactJob.id).in_(job_ids)))
    if execution_ids:
        await db.exec(
            delete(WorkflowGateRequest).where(
                col(WorkflowGateRequest.execution_id).in_(execution_ids)
            )
        )
        await db.exec(
            delete(WorkflowNodeRun).where(
                col(WorkflowNodeRun.execution_id).in_(execution_ids)
            )
        )
        await db.exec(
            delete(WorkflowExecution).where(
                col(WorkflowExecution.id).in_(execution_ids)
            )
        )
    if draft_ids:
        await db.exec(
            delete(WebBridgeTeachReplay).where(
                col(WebBridgeTeachReplay.draft_id).in_(draft_ids)
            )
        )
    await db.exec(
        delete(WebBridgeTeachDraft).where(
            col(WebBridgeTeachDraft.session_id).in_(session_ids)
        )
    )
    await db.exec(
        delete(WebBridgeTabBinding).where(
            col(WebBridgeTabBinding.session_id).in_(session_ids)
        )
    )
    await db.exec(
        delete(WebBridgeInteraction).where(
            col(WebBridgeInteraction.target_session_id).in_(session_ids)
        )
    )
    await db.exec(
        delete(DelegationTask).where(
            col(DelegationTask.lead_session_id).in_(session_ids)
        )
    )
    await db.exec(
        delete(SessionGoal).where(col(SessionGoal.session_id).in_(session_ids))
    )
    await db.exec(delete(DreamLog).where(col(DreamLog.session_id).in_(session_ids)))
    await db.exec(
        delete(SessionMessage).where(col(SessionMessage.session_id).in_(session_ids))
    )

    string_ids = {str(session_id) for session_id in session_ids}
    if delete_scheduled_tasks:
        scheduled = list(
            (
                await db.exec(
                    select(ScheduledTask).where(
                        col(ScheduledTask.session_id).in_(string_ids)
                    )
                )
            ).all()
        )
        task_scheduler.cancel_timers({task.id for task in scheduled})
        await db.exec(
            delete(ScheduledTask).where(
                col(ScheduledTask.id).in_({t.id for t in scheduled})
            )
        )
    else:
        await db.exec(
            update(ScheduledTask)
            .where(col(ScheduledTask.session_id).in_(string_ids))
            .values(session_id=None)
        )

    await db.exec(delete(ChatSession).where(col(ChatSession.id).in_(session_ids)))
    return SessionFiles(
        session_ids=tuple(UUID(str(value)) for value in sorted(session_ids, key=str)),
        artifact_job_ids=tuple(UUID(str(value)) for value in sorted(job_ids, key=str)),
        artifact_revision_ids=tuple(
            UUID(str(value)) for value in sorted(revision_ids, key=str)
        ),
        orphan_blob_keys=tuple(sorted(blob_keys - referenced_keys)),
    )


async def _remove_tree(path: Path) -> None:
    if path.exists():
        await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)


async def _purge_session_files(files: SessionFiles) -> None:
    for session_id in files.session_ids:
        sid = str(session_id)
        remove_session_sink(sid)
        await asyncio.gather(
            _remove_tree(workspace_dir(sid)),
            _remove_tree(session_artifact_dir(sid)),
            _remove_tree(snapshot_dir(sid)),
            _remove_tree(SESSION_LOG_DIR / sid),
        )

    store = ArtifactStore()
    for job_id in files.artifact_job_ids:
        await _remove_tree(store.root / "work" / str(job_id))
    for revision_id in files.artifact_revision_ids:
        await _remove_tree(store.revision_root / str(revision_id))
    for key in files.orphan_blob_keys:
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "sha256" or len(parts[2]) != 64:
            continue
        blob = (store.blob_root / parts[1] / parts[2]).resolve()
        try:
            blob.relative_to(store.blob_root.resolve())
        except ValueError:
            continue
        await asyncio.to_thread(blob.unlink, missing_ok=True)


async def _purge_repository_caches(paths: set[str]) -> None:
    for path in sorted(paths):
        await repository_indexes.purge(Path(path))


async def purge_session(db: AsyncSession, session_id: UUID) -> bool:
    """Purge one chat session plus all child/side-chat state and files."""
    session = await db.get(ChatSession, session_id)
    if session is None:
        return False
    sessions = await _session_closure(db, {session_id})
    session_ids = {item.id for item in sessions}
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=False)
    await db.commit()
    await _purge_session_files(files)
    logger.info("session_purged session_id={} rows={}", session_id, len(session_ids))
    return True


def _git(source: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "managed_worktree_cleanup_failed source={} error={}", source, exc
        )
        return None


async def _remove_managed_worktree(source_path: str, worktree_path: str) -> None:
    source = Path(source_path).expanduser().resolve()
    worktree = Path(worktree_path).expanduser().resolve()
    if not any(root in worktree.parents for root in managed_worktree_roots(source)):
        logger.warning("managed_worktree_cleanup_refused path={}", worktree)
        return

    branch_result = await asyncio.to_thread(
        _git, worktree, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    branch = (
        branch_result.stdout.strip()
        if branch_result is not None and branch_result.returncode == 0
        else None
    )
    removed = await asyncio.to_thread(
        _git, source, "worktree", "remove", "--force", str(worktree)
    )
    if removed is None or removed.returncode != 0:
        await _remove_tree(worktree)
        await asyncio.to_thread(_git, source, "worktree", "prune")
    if branch and branch.startswith("EvoFlux/"):
        await asyncio.to_thread(_git, source, "branch", "-D", branch)


async def purge_workspace(db: AsyncSession, path: str) -> PurgeResult:
    """Permanently remove one standalone repository and all owned app data."""
    resolved = str(Path(path).expanduser().resolve())
    rows = list(
        (
            await db.exec(
                select(CodingWorkspace).where(
                    or_(
                        col(CodingWorkspace.path) == resolved,
                        col(CodingWorkspace.source_path) == resolved,
                    )
                )
            )
        ).all()
    )
    source = next((row for row in rows if row.path == resolved), None)
    if source is not None:
        membership = (
            await db.exec(
                select(CodingProjectWorkspace)
                .join(
                    CodingProject,
                    col(CodingProject.id) == col(CodingProjectWorkspace.project_id),
                )
                .where(
                    col(CodingProjectWorkspace.workspace_id) == source.id,
                    col(CodingProject.deleted_at).is_(None),
                )
            )
        ).first()
        if membership is not None:
            raise PurgeConflictError(
                "Workspace belongs to a project; remove it from the project first."
            )

    workspace_paths = {resolved, *(row.path for row in rows)}
    managed_worktrees = tuple(
        (row.source_path, row.path)
        for row in rows
        if row.kind == "worktree" and row.managed and row.source_path
    )
    seed_ids = set(
        (
            await db.exec(
                select(ChatSession.id).where(
                    col(ChatSession.workspace).in_(workspace_paths)
                )
            )
        ).all()
    )
    sessions = await _session_closure(db, seed_ids)
    session_ids: set[UUID] = {session.id for session in sessions}
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=True)

    scheduled = list(
        (
            await db.exec(
                select(ScheduledTask).where(
                    col(ScheduledTask.workspace).in_(workspace_paths)
                )
            )
        ).all()
    )
    task_scheduler.cancel_timers({task.id for task in scheduled})
    if scheduled:
        await db.exec(
            delete(ScheduledTask).where(
                col(ScheduledTask.id).in_({t.id for t in scheduled})
            )
        )
    workspace_ids = {row.id for row in rows}
    if workspace_ids:
        await db.exec(
            delete(CodingProjectWorkspace).where(
                col(CodingProjectWorkspace.workspace_id).in_(workspace_ids)
            )
        )
        await db.exec(
            delete(GitServerConnection).where(
                col(GitServerConnection.workspace_id).in_(workspace_ids)
            )
        )
    for row in rows:
        await db.delete(row)
    await db.commit()

    await _purge_session_files(files)
    await _purge_repository_caches(workspace_paths)
    for source_path, worktree_path in managed_worktrees:
        await _remove_managed_worktree(source_path, worktree_path)
    logger.info(
        "coding_workspace_purged path={} sessions={}", resolved, len(session_ids)
    )
    return PurgeResult(len(session_ids), tuple(sorted(workspace_paths)))


async def _project_membership_paths(
    db: AsyncSession, project_id: UUID
) -> tuple[CodingProject, list[tuple[CodingProjectWorkspace, CodingWorkspace]]] | None:
    project = await db.get(CodingProject, project_id)
    if project is None or project.deleted_at is not None:
        return None
    pairs = list(
        (
            await db.exec(
                select(CodingProjectWorkspace, CodingWorkspace)
                .join(
                    CodingWorkspace,
                    col(CodingWorkspace.id) == col(CodingProjectWorkspace.workspace_id),
                )
                .where(CodingProjectWorkspace.project_id == project_id)
            )
        ).all()
    )
    return project, [(link, workspace) for link, workspace in pairs]


async def purge_project(db: AsyncSession, project_id: UUID) -> PurgeResult | None:
    """Hard-delete a project and all project-owned session/runtime data."""
    loaded = await _project_membership_paths(db, project_id)
    if loaded is None:
        return None
    project, pairs = loaded
    workspace_ids: set[UUID] = {workspace.id for _link, workspace in pairs}
    repository_paths = {workspace.path for _link, workspace in pairs}
    shared_ids: set[UUID] = set()
    if workspace_ids:
        shared_ids = set(
            (
                await db.exec(
                    select(CodingProjectWorkspace.workspace_id)
                    .join(
                        CodingProject,
                        col(CodingProject.id) == col(CodingProjectWorkspace.project_id),
                    )
                    .where(
                        col(CodingProjectWorkspace.workspace_id).in_(workspace_ids),
                        CodingProjectWorkspace.project_id != project_id,
                        col(CodingProject.deleted_at).is_(None),
                    )
                )
            ).all()
        )
    purge_paths = {
        workspace.path for _link, workspace in pairs if workspace.id not in shared_ids
    }
    seed_ids = set(
        (
            await db.exec(
                select(ChatSession.id).where(ChatSession.project_id == project_id)
            )
        ).all()
    )
    sessions = await _session_closure(db, seed_ids)
    session_ids: set[UUID] = {session.id for session in sessions}
    await project_index_jobs.cancel(str(project_id))
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=True)

    scheduled = list(
        (
            await db.exec(
                select(ScheduledTask).where(ScheduledTask.project_id == project_id)
            )
        ).all()
    )
    task_scheduler.cancel_timers({task.id for task in scheduled})
    if scheduled:
        await db.exec(
            delete(ScheduledTask).where(
                col(ScheduledTask.id).in_({t.id for t in scheduled})
            )
        )
    await db.exec(
        delete(CodingProjectWorkspace).where(
            col(CodingProjectWorkspace.project_id) == project_id
        )
    )
    await db.delete(project)
    await db.commit()

    await _purge_session_files(files)
    await _purge_repository_caches(purge_paths)
    logger.info(
        "coding_project_purged project_id={} sessions={}", project_id, len(session_ids)
    )
    return PurgeResult(len(session_ids), tuple(sorted(repository_paths)))


async def purge_project_workspace(
    db: AsyncSession, project_id: UUID, workspace_id: UUID
) -> PurgeResult | None:
    """Detach a repo and reset every project session that authorized it."""
    loaded = await _project_membership_paths(db, project_id)
    if loaded is None:
        return None
    _project, pairs = loaded
    selected = next(
        (
            (link, workspace)
            for link, workspace in pairs
            if workspace.id == workspace_id
        ),
        None,
    )
    if selected is None:
        return None
    link, workspace = selected
    shared = (
        await db.exec(
            select(CodingProjectWorkspace)
            .join(
                CodingProject,
                col(CodingProject.id) == col(CodingProjectWorkspace.project_id),
            )
            .where(
                col(CodingProjectWorkspace.workspace_id) == workspace_id,
                col(CodingProjectWorkspace.project_id) != project_id,
                col(CodingProject.deleted_at).is_(None),
            )
        )
    ).first()
    seed_ids = set(
        (
            await db.exec(
                select(ChatSession.id).where(ChatSession.project_id == project_id)
            )
        ).all()
    )
    sessions = await _session_closure(db, seed_ids)
    session_ids: set[UUID] = {session.id for session in sessions}
    await project_index_jobs.cancel(str(project_id))
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=False)
    await db.delete(link)
    await db.commit()

    await _purge_session_files(files)
    if shared is None:
        await _purge_repository_caches({workspace.path})
    logger.info(
        "coding_project_workspace_purged project_id={} workspace={} sessions={}",
        project_id,
        workspace.path,
        len(session_ids),
    )
    return PurgeResult(len(session_ids), (workspace.path,))


__all__ = [
    "PurgeConflictError",
    "PurgeResult",
    "purge_project",
    "purge_project_workspace",
    "purge_session",
    "purge_workspace",
]
