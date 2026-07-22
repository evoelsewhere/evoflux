"""Shared interactive message ingress for HTTP and browser channels."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.services import agent_service, team_manager
from app.services.agent_service import NoTeamConfigured
from app.services.chat_service import cleanup_reverted_tail, save_queued_user_message


@dataclass(frozen=True)
class InteractiveMessageResult:
    status: str
    session_id: str
    message_id: UUID | None = None


async def _project_paths_for_session(
    db: AsyncSession, session: ChatSession, workspace: str
) -> tuple[list[str], list[str]]:
    extra_workspace_paths: list[str] = []
    read_only_paths: list[str] = []
    if session.project_id is None:
        return extra_workspace_paths, read_only_paths

    from app.services.coding_project_service import (
        get_project,
        get_project_workspace_paths,
    )

    async with db.begin():
        project = await get_project(db, session.project_id)
        all_paths = await get_project_workspace_paths(db, session.project_id)
    extra_workspace_paths = [path for path in all_paths if path != workspace]
    if project is not None and project.kind == "aim":
        from app.services.aim.project import resolve_source_workspace_paths

        async with db.begin():
            read_only_paths = await resolve_source_workspace_paths(db, project)
    return extra_workspace_paths, read_only_paths


async def resolve_team_for_session(
    db: AsyncSession,
    session_id: str,
    *,
    require_existing: bool = False,
):
    """Resolve a session's persisted mode and restore its team-level settings."""
    try:
        session_uuid = UUID(session_id)
    except ValueError as exc:
        raise ValueError("Invalid session id.") from exc

    async with db.begin():
        session = await db.get(ChatSession, session_uuid)
    if session is None and require_existing:
        raise ValueError("Session not found.")

    if session is not None and session.mode in ("coding", "aim") and session.workspace:
        workspace = team_manager.validate_workspace(session.workspace)
        extra_paths, read_only_paths = await _project_paths_for_session(
            db, session, workspace
        )
        team = await team_manager.get_or_start_coding_team(
            workspace,
            session_id,
            extra_workspace_paths=extra_paths or None,
            mode=session.mode,
            read_only_paths=read_only_paths or None,
        )
    else:
        team = await team_manager.get_or_start_team_for_session(session_id)
    team = agent_service.require_team(team)

    if session is not None:
        team.session_tags = frozenset(session.tags or ())
        team.permission_mode = session.permission_mode
    return session, team


async def submit_persisted_interactive_message(
    db: AsyncSession,
    *,
    session: ChatSession,
    team,
    content: str,
) -> InteractiveMessageResult:
    """Queue or dispatch one prepared, attachment-free interactive message."""
    session_id = str(session.id)
    team.session_tags = frozenset(session.tags or ())
    team.permission_mode = session.permission_mode

    async with team.user_message_lock:
        async with db.begin():
            await cleanup_reverted_tail(db, session.id)

        if team.has_active_user_turn():
            queued_extra: dict[str, object] = {}
            effective_model = session.model or team.lead.agent.model_id
            if effective_model:
                queued_extra["model"] = effective_model
            if session.thinking_level:
                queued_extra["thinking_level"] = session.thinking_level
            async with db.begin():
                queued = await save_queued_user_message(
                    db,
                    session.id,
                    content,
                    extra=queued_extra,
                )
            if not team.has_active_user_turn():
                await team._activate_queued_user_messages(session_id)
            return InteractiveMessageResult(
                status="queued",
                session_id=session_id,
                message_id=queued.id,
            )

        dispatched_id, _ = await agent_service.dispatch_user_message(
            team,
            content=content,
            session_id=session_id,
            mode=session.mode,
            workspace=session.workspace,
        )
        return InteractiveMessageResult(status="accepted", session_id=dispatched_id)


__all__ = [
    "InteractiveMessageResult",
    "NoTeamConfigured",
    "resolve_team_for_session",
    "submit_persisted_interactive_message",
]
