"""Destructive cleanup for removed Coding projects and their sessions.

Repository source directories are user-owned and are never deleted. The
service removes app-owned session state and database records so reopening
starts cleanly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.artifacts import session_artifact_dir
from app.core.logging_config import SESSION_LOG_DIR, remove_session_sink
from app.core.paths import workspace_dir
from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
    CodingWorkspace,
    DreamLog,
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
from app.scheduler.models import ScheduledTask
from app.scheduler.scheduler import task_scheduler
from app.services import agent_service, memory_stream_store, team_manager
from app.services.coding_project_service import (
    get_visible_project_ids_for_workspace_path,
)
from app.services.snapshot_service import snapshot_dir
from app.services.terminal_service import terminal_manager


@dataclass(frozen=True, slots=True)
class SessionFiles:
    session_ids: tuple[UUID, ...] = ()


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
    for session_id in string_ids:
        agent_service.cancel_deferred_user_message(session_id)
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

    # Remove episodic evidence first; semantic facts survive only when another
    # session still supports them. This gives chat deletion real forget
    # semantics for the canonical scoped-memory store.
    from app.services.scoped_memory import forget_session_memory

    for session_id in session_ids:
        await forget_session_memory(db, session_id)

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


async def _sole_owner(db: AsyncSession, workspace: str | None) -> UUID | None:
    """The one live project owning *workspace* (or its worktree source)."""
    if not workspace:
        return None
    owners = await get_visible_project_ids_for_workspace_path(db, workspace)
    return owners[0] if len(owners) == 1 else None


async def purge_standalone_coding_sessions(
    db: AsyncSession, *, created_before: datetime | None = None
) -> PurgeResult:
    """File or permanently remove Coding sessions and tasks with no project.

    Coding is project-only: a Coding chat or scheduled task that belongs to
    no project (a standalone workspace from before that rule, or one whose
    project link was lost) can no longer be opened anywhere.

    One whose repository — or, for a worktree, its source repository — now
    belongs to exactly one project is filed under that project instead: a
    repo that joined a project later never had its older chats moved over.
    The rest are deleted, their sub-agent sessions and side chats with them.
    Repository sources and the repository registry are left alone, so the
    folders can still be added to a project.

    ``created_before`` leaves rows made after that moment alone: a row still
    being set up by a live request (a member session is written before its
    parent link) must not be caught half-built.

    Idempotent; cheap when there is nothing to remove.
    """
    session_filter: list[Any] = [
        ChatSession.mode == "coding",
        col(ChatSession.project_id).is_(None),
        col(ChatSession.parent_session_id).is_(None),
        col(ChatSession.session_type) != "side_chat",
    ]
    task_filter: list[Any] = [
        ScheduledTask.mode == "coding",
        col(ScheduledTask.project_id).is_(None),
    ]
    if created_before is not None:
        session_filter.append(col(ChatSession.created_at) < created_before)
        task_filter.append(col(ScheduledTask.created_at) < created_before)
    seeds = list((await db.exec(select(ChatSession).where(*session_filter))).all())
    scheduled = list((await db.exec(select(ScheduledTask).where(*task_filter))).all())
    if not seeds and not scheduled:
        await db.rollback()
        return PurgeResult(0, ())

    adopted: dict[UUID, UUID] = {}
    for session in seeds:
        owner = await _sole_owner(db, session.workspace)
        if owner is not None:
            session.project_id = owner
            db.add(session)
            adopted[session.id] = owner
    if adopted:
        # Their side chats travel with them.
        side_chats = (
            await db.exec(
                select(ChatSession).where(
                    col(ChatSession.source_session_id).in_(set(adopted)),
                    col(ChatSession.project_id).is_(None),
                )
            )
        ).all()
        for side_chat in side_chats:
            if side_chat.source_session_id is not None:
                side_chat.project_id = adopted[side_chat.source_session_id]
                db.add(side_chat)
    kept_tasks = []
    for task in scheduled:
        owner = await _sole_owner(db, task.workspace)
        if owner is not None:
            task.project_id = owner
            db.add(task)
        else:
            kept_tasks.append(task)
    scheduled = kept_tasks
    seed_ids = {session.id for session in seeds if session.id not in adopted}
    if adopted:
        logger.info("standalone_coding_sessions_adopted sessions={}", len(adopted))
    if not seed_ids and not scheduled:
        await db.commit()
        return PurgeResult(0, ())

    sessions = await _session_closure(db, seed_ids)
    session_ids: set[UUID] = {session.id for session in sessions}
    workspace_paths = {session.workspace for session in sessions if session.workspace}
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=True)
    task_scheduler.cancel_timers({task.id for task in scheduled})
    if scheduled:
        await db.exec(
            delete(ScheduledTask).where(
                col(ScheduledTask.id).in_({t.id for t in scheduled})
            )
        )
    await db.commit()

    await _purge_session_files(files)
    logger.info(
        "standalone_coding_sessions_purged sessions={} scheduled_tasks={}",
        len(session_ids),
        len(scheduled),
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
    repository_paths = {workspace.path for _link, workspace in pairs}
    seed_ids = set(
        (
            await db.exec(
                select(ChatSession.id).where(ChatSession.project_id == project_id)
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
    seed_ids = set(
        (
            await db.exec(
                select(ChatSession.id).where(ChatSession.project_id == project_id)
            )
        ).all()
    )
    sessions = await _session_closure(db, seed_ids)
    session_ids: set[UUID] = {session.id for session in sessions}
    await _stop_session_runtime(session_ids)
    files = await _purge_session_rows(db, sessions, delete_scheduled_tasks=False)
    await db.delete(link)
    await db.commit()

    await _purge_session_files(files)
    logger.info(
        "coding_project_workspace_purged project_id={} workspace={} sessions={}",
        project_id,
        workspace.path,
        len(session_ids),
    )
    return PurgeResult(len(session_ids), (workspace.path,))


__all__ = [
    "PurgeResult",
    "purge_project",
    "purge_project_workspace",
    "purge_session",
    "purge_standalone_coding_sessions",
]
