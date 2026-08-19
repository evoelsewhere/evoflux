"""Explicit AI assistance for local Git and review workflows."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.api.deps import DbSession
from app.api.schemas.git_ai import GitAIRequest, GitAIResponse
from app.models.chat import ChatSession
from app.services import team_manager
from app.services import coding_workspace_authorization
from app.services.change_set_service import ChangeSetStale
from app.services.git_ai_service import run_git_ai_action

router = APIRouter(prefix="/workspace/git/ai")


@router.post("", response_model=GitAIResponse)
async def run_git_ai_action_route(
    workspace: str,
    body: GitAIRequest,
    db: DbSession,
) -> GitAIResponse:
    try:
        root = Path(team_manager.validate_workspace(workspace)).resolve()
        session_uuid = UUID(body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session = await db.get(ChatSession, session_uuid)
    if session is None or session.mode != "coding":
        raise HTTPException(status_code=404, detail="Coding session not found.")
    if not session.workspace:
        raise HTTPException(status_code=409, detail="Coding session has no workspace.")
    project_id = getattr(session, "project_id", None)
    primary_matches = Path(session.workspace).resolve() == root
    project_matches = bool(
        project_id
        and await coding_workspace_authorization.project_contains_workspace_path(
            db, project_id, root
        )
    )
    if not primary_matches and not project_matches:
        raise HTTPException(
            status_code=409, detail="Session belongs to another workspace."
        )

    team = team_manager.find_team_for_session(body.session_id)
    if team is None:
        team = await team_manager.get_or_start_coding_team(
            str(Path(session.workspace).resolve()), body.session_id, mode="coding"
        )
    provider = team.lead.agent.llm_provider
    provider_factory = getattr(team, "_provider_factory", None)
    if session.model and provider_factory is not None:
        model_kwargs: dict[str, object] = {}
        if session.thinking_level:
            model_kwargs["thinking_level"] = session.thinking_level
        provider = provider_factory(session.model, model_kwargs=model_kwargs)

    token = set_sandbox(SandboxConfig(workspace=str(root), session_id=body.session_id))
    try:
        result = await run_git_ai_action(
            workspace=root,
            provider=provider,
            action=body.action,
            session_id=body.session_id,
            reference=body.reference,
            remote_context=body.remote_context,
        )
    except ChangeSetStale as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_change_set", "paths": exc.paths},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(token)
    return GitAIResponse.model_validate(result)
