"""Suggested-task endpoints — the chips an agent parks for out-of-scope work.

Starting one produces a real coding session the user lands in; the prompt is
returned rather than sent so the client posts it through the ordinary
``POST /chat`` path and inherits everything that route already does.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.suggested_task_status import publish_suggested_task
from app.api.deps import DbSession
from app.api.routes.team.chat import _register_session_workspace
from app.api.routes.team.worktrees import (
    WorktreeCreateRequest,
    create_coding_workspace_worktree,
)
from app.models.chat import ChatSession
from app.services import suggested_task_service, team_manager
from app.services.coding_project_service import (
    get_visible_project_ids_for_workspace_path,
)
from app.services.suggested_task_service import (
    SuggestedTaskConflictError,
    SuggestedTaskSnapshot,
)

router = APIRouter()


class SuggestedTaskListResponse(BaseModel):
    tasks: list[SuggestedTaskSnapshot]


class SuggestedTaskStartRequest(BaseModel):
    isolated: bool = Field(
        default=False,
        description=(
            "Create a managed git worktree for the new session instead of "
            "sharing the parent session's working tree."
        ),
    )


class SuggestedTaskStartResponse(BaseModel):
    session_id: UUID
    workspace: str
    #: The client posts this as the new session's first message.
    prompt: str
    worktree_path: str | None = None
    task: SuggestedTaskSnapshot


class SuggestedTaskDismissRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


@router.get("/sessions/{session_id}/suggested-tasks")
async def list_suggested_tasks(
    session_id: UUID, db: DbSession, include_resolved: bool = False
) -> SuggestedTaskListResponse:
    """Open chips for a session; ``include_resolved`` adds started/dismissed."""

    statuses = ("pending", "started", "dismissed") if include_resolved else ("pending",)
    async with db.begin():
        rows = await suggested_task_service.list_for_session(
            db, session_id, statuses=statuses
        )
    return SuggestedTaskListResponse(
        tasks=[suggested_task_service.snapshot(row) for row in rows]
    )


@router.post("/suggested-tasks/{task_id}/start")
async def start_suggested_task(
    task_id: UUID, body: SuggestedTaskStartRequest, db: DbSession
) -> SuggestedTaskStartResponse:
    """Turn a chip into its own coding session.

    The worktree, when requested, is created before the session row so a git
    failure leaves the chip pending and retryable rather than stranding a
    session pointed at a directory that does not exist.
    """

    async with db.begin():
        task = await suggested_task_service.get(db, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Suggested task not found.")
        if task.status != "pending":
            raise HTTPException(
                status_code=409, detail=f"This suggestion was already {task.status}."
            )
        parent = await db.get(ChatSession, task.session_id)
        if parent is None:
            raise HTTPException(
                status_code=404, detail="Originating session no longer exists."
            )
        workspace = task.cwd or parent.workspace
        agent_name = parent.agent_name
        model = parent.model
        thinking_level = parent.thinking_level

    if not workspace:
        raise HTTPException(
            status_code=422,
            detail=(
                "The originating session has no workspace, so there is nowhere "
                "to start this task."
            ),
        )

    worktree_path: str | None = None
    if body.isolated:
        created = await create_coding_workspace_worktree(
            WorktreeCreateRequest(source_workspace=workspace, name=task.title)
        )
        worktree_path = created.directory
        workspace = created.directory

    async with db.begin():
        task = await suggested_task_service.require(db, task_id)
        project_ids = await get_visible_project_ids_for_workspace_path(db, workspace)
        session = ChatSession(
            mode="coding",
            # Top-level: the spawned task is its own entry in the sidebar, not
            # a subagent of the session that suggested it. The link back lives
            # on the task row's spawned_session_id.
            parent_session_id=None,
            agent_name=agent_name,
            title=task.title,
            workspace=workspace,
            project_id=project_ids[0] if len(project_ids) == 1 else None,
            model=model,
            thinking_level=thinking_level,
        )
        db.add(session)
        await _register_session_workspace(db, workspace)
        await db.flush()
        await db.refresh(session)
        try:
            await suggested_task_service.mark_started(
                db,
                task,
                spawned_session_id=session.id,
                worktree_path=worktree_path,
            )
        except SuggestedTaskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        snapshot = suggested_task_service.snapshot(task)
        prompt = task.prompt

    team_manager.prewarm_session_team(
        mode=session.mode,
        session_id=str(session.id),
        workspace=session.workspace,
        lead_name=session.agent_name,
    )
    await publish_suggested_task(
        str(snapshot.session_id), snapshot, source="start_suggested_task"
    )
    return SuggestedTaskStartResponse(
        session_id=session.id,
        workspace=workspace,
        prompt=prompt,
        worktree_path=worktree_path,
        task=snapshot,
    )


@router.post("/suggested-tasks/{task_id}/dismiss")
async def dismiss_suggested_task(
    task_id: UUID, body: SuggestedTaskDismissRequest, db: DbSession
) -> SuggestedTaskSnapshot:
    async with db.begin():
        task = await suggested_task_service.get(db, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Suggested task not found.")
        try:
            await suggested_task_service.dismiss(db, task, reason=body.reason)
        except SuggestedTaskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        snapshot = suggested_task_service.snapshot(task)

    await publish_suggested_task(
        str(snapshot.session_id), snapshot, source="dismiss_suggested_task"
    )
    return snapshot
