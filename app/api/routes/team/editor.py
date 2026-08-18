"""Explicit AI semantic-editor actions and inspectable context previews."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.api.deps import DbSession
from app.api.schemas.editor import (
    EditorActionRequest,
    EditorActionResponse,
    EditorContextRequest,
    EditorContextResponse,
)
from app.models.chat import ChatSession
from app.services import team_manager
from app.services.editor_action_service import run_editor_action
from app.services.editor_context_service import EditorContextError, build_editor_context

router = APIRouter(prefix="/workspace/editor")
_CHANGE_ACTIONS = frozenset(
    {
        "fix_diagnostic",
        "refactor_selection",
        "generate_tests",
        "generate_documentation",
        "simplify_code",
        "convert_pattern",
        "propagate_api_change",
    }
)


def _workspace(raw: str) -> Path:
    try:
        return Path(team_manager.validate_workspace(raw)).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _context(workspace: Path, body: EditorContextRequest):
    try:
        return await build_editor_context(
            workspace,
            active_file=body.active_file,
            content=body.content,
            document_version=body.document_version,
            selection=body.selection.model_dump() if body.selection else None,
            cursor_symbol=body.cursor_symbol,
            diagnostics=body.diagnostics,
            mention_paths=body.mention_paths,
            session_id=body.session_id,
            relevant_terminal_failure=body.relevant_terminal_failure,
        )
    except EditorContextError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/context", response_model=EditorContextResponse)
async def preview_editor_context(
    workspace: str, body: EditorContextRequest
) -> EditorContextResponse:
    context = await _context(_workspace(workspace), body)
    return EditorContextResponse(context=context.to_dict())


@router.post("/action", response_model=EditorActionResponse)
async def run_editor_action_route(
    workspace: str,
    body: EditorActionRequest,
    db: DbSession,
) -> EditorActionResponse:
    root = _workspace(workspace)
    if not body.session_id:
        raise HTTPException(
            status_code=422, detail="AI editor actions require session_id."
        )
    try:
        session_uuid = UUID(body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session_id.") from exc
    session = await db.get(ChatSession, session_uuid)
    if session is None or session.mode != "coding":
        raise HTTPException(status_code=404, detail="Coding session not found.")
    if not session.workspace or Path(session.workspace).resolve() != root:
        raise HTTPException(
            status_code=409, detail="Session belongs to another workspace."
        )

    context = await _context(root, body)
    if body.action in _CHANGE_ACTIONS:
        target = root / context.active_file
        try:
            disk_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if disk_hash != context.content_sha256:
            raise HTTPException(
                status_code=409,
                detail="Save the active editor buffer before requesting AI changes.",
            )

    team = team_manager.find_team_for_session(body.session_id)
    if team is None:
        team = await team_manager.get_or_start_coding_team(
            str(root), body.session_id, mode="coding"
        )
    provider = team.lead.agent.llm_provider
    provider_factory = getattr(team, "_provider_factory", None)
    if session.model and provider_factory is not None:
        model_kwargs: dict[str, object] = {}
        if session.thinking_level:
            model_kwargs["thinking_level"] = session.thinking_level
        provider = provider_factory(session.model, model_kwargs=model_kwargs)

    sandbox_token = set_sandbox(
        SandboxConfig(workspace=str(root), session_id=body.session_id)
    )
    try:
        result = await run_editor_action(
            provider=provider,
            action=body.action,
            instruction=body.instruction,
            context=context,
            session_id=body.session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(sandbox_token)
    return EditorActionResponse.model_validate(result)
