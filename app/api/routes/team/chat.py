"""Team chat, SSE stream, agent listing, session CRUD, and history."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Literal, cast
from uuid import UUID
from uuid import uuid7  # ty: ignore[unresolved-import]

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from loguru import logger
from pydantic import BaseModel, field_validator
from sqlmodel import col, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    ChatFormDep,
    DbSession,
    DbSessionFactory,
    ReadDbSession,
    WriteDbSession,
)
from app.api.routes.team._helpers import (
    _fast_tier,
    _message_response,
    _read_upload_as_attachment,
    _require_team,
    collect_mention_attachments,
)
from app.api.routes.agents import is_registered_model_id
from app.api.routes.team.projects import list_project_responses
from app.api.schemas.sessions import (
    CodingWorkspaceTreeRepository,
    CodingWorkspaceTreeResponse,
    CodingWorkspaceTreeWorktree,
    MessageResponse,
    SessionDetailResponse,
    SessionPageResponse,
    SessionResponse,
    TeamSessionResolveRequest,
    TeamSessionResolveResponse,
    TeamSessionLeadUpdateRequest,
    TeamLeadListResponse,
    TeamLeadMemberResponse,
    TeamLeadResponse,
    TeamSessionUpdateRequest,
    TeamWorkspaceVisibilityRequest,
)
from app.webbridge_tags import WEBBRIDGE_SESSION_TAG
from app.api.schemas.team import GoalResponse, TeamHistoryMember, TeamHistoryResponse
from app.api.routes.team.worktrees import (
    WorktreeCreateRequest,
    create_coding_workspace_worktree,
    find_managed_worktree_source,
)
from app.models.chat import (
    ChatSession,
    CodingProject,
    CodingProjectWorkspace,
    normalize_mode,
)
from app.services import (
    agent_service,
    goal_service,
    memory_stream_store as stream_store,
    team_manager,
)
from app.services.agent_service import AttachmentError, NoTeamConfigured, RawAttachment
from app.services.coding_workspace_service import (
    list_visible_coding_workspaces,
    upsert_coding_workspace,
)
from app.services.coding_purge_service import PurgeConflictError, purge_workspace
from app.services.coding_project_service import (
    get_visible_project_ids_for_workspace_path,
)
from app.services.webbridge_service import webbridge_manager
from app.services.interactive_message_service import resolve_team_for_session
from app.services.chat_service import (
    BoundaryShift,
    cancel_queued_user_message,
    cleanup_reverted_tail,
    delete_session,
    duplicate_session,
    get_team_history,
    get_latest_top_level_session,
    list_sessions_page,
    save_queued_user_message,
    update_session_title,
)
from app.services.commands import parse_slash_invocation
from app.services.session_folder_service import get_folder

if TYPE_CHECKING:
    from app.agent.agent_loop import Agent
    from app.agent.mode.team.member import TeamMemberBase

router = APIRouter()


def _resolve_effective_request_model(
    requested: str | None,
    *,
    provided: bool,
    persisted: str | None,
    default: str | None,
) -> str | None:
    """Resolve one model id for capability checks and runtime dispatch."""
    if provided:
        return requested or default
    return persisted or default


async def _validate_thinking_level_for_model(
    model_id: str | None, thinking_level: str | None
) -> None:
    """Reject a reasoning effort that the resolved model does not advertise.

    Every non-default value, including ``none``, is checked against the
    model/provider/adapter intersection. Some APIs default to reasoning and
    have no explicit off switch, so treating ``none`` as universally safe
    silently changes nothing or produces an invalid request.
    """
    if not model_id:
        return

    from app.agent.providers.model_discovery import ensure_runtime_model_metadata
    from app.agent.providers.thinking import (
        accepts_thinking_level,
        honoured_levels_for,
    )

    if thinking_level or model_id.lower().startswith("fci:"):
        await ensure_runtime_model_metadata(model_id)
    if not thinking_level:
        return
    # One source of truth: what the request builder will honour. Validating
    # against the raw catalog list instead rejected levels the wire accepts
    # and the picker offers — a model whose catalog row says "toggle" still
    # takes a token budget, so ``high`` is a real request.
    if accepts_thinking_level(model_id, thinking_level):
        return

    supported = honoured_levels_for(model_id)
    detail = f"Model '{model_id}' does not support thinking level '{thinking_level}'."
    if supported:
        detail += f" Supported levels: {', '.join(supported)}."
    else:
        detail += " This model has no configurable thinking levels."
    raise HTTPException(status_code=422, detail=detail)


def discover_skills():  # noqa: ANN201 - compatibility wrapper
    from app.agent.tools.builtin.skill import discover_skills as discover

    return discover()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _serialize_agent(agent: Agent, *, is_lead: bool = False) -> dict:
    """Serialize an Agent into the /team/agents response shape."""
    from app.agent.hooks.summarization import prompt_token_threshold_for_model

    skill_names: list[str] = agent.skills or []
    skills: list[dict] = []
    if skill_names:
        try:
            available = discover_skills()
        except Exception:
            available = {}
        skills = [
            {"name": n, "description": available.get(n, {}).get("description", "")}
            for n in skill_names
        ]

    return {
        "name": agent.name,
        "description": agent.description or "",
        "model": agent.model_id,
        "summary_trigger_tokens": prompt_token_threshold_for_model(agent.model_id),
        "tools": [
            {"name": t.name, "description": t.description or ""}
            for t in agent._tools.values()
        ],
        # MCP servers configured on the agent. The UI groups tools by name
        # prefix (`mcp_<server>_<tool>`) using this list. Includes servers that
        # exist in config but aren't ready (zero tools), so the UI can show
        # them as "not ready" instead of silently hiding the section.
        "mcp_servers": list(agent.mcp_servers),
        "skills": skills,
        "is_lead": is_lead,
        "capabilities": agent.capabilities.to_dict(),
    }


# Serialized-blueprint payload cache keyed by (md path, mode), invalidated
# by the .md's mtime. Rebuilding an Agent per blueprint on every GET
# /team/agents re-parses the .md, tool registry, skills and provider —
# expensive and pure, so cache the payload. Staleness note: edits to
# SKILL.md descriptions or mcp.json alone won't bust the cache until the
# blueprint .md is touched or the process restarts.
_blueprint_payload_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _serialize_blueprint(team_obj, bp) -> dict:
    from app.agent.loader import rebuild_agent_from_disk

    key = (str(bp.source_path), team_obj.mode)
    try:
        mtime: float | None = bp.source_path.stat().st_mtime
    except OSError:
        mtime = None

    cached = _blueprint_payload_cache.get(key) if mtime is not None else None
    if cached is not None and cached[0] == mtime:
        payload = dict(cached[1])
    else:
        agent = rebuild_agent_from_disk(
            bp.source_path,
            provider_factory=team_obj._provider_factory,
            extra_tools=team_obj._extra_tools,
            mode=team_obj.mode,
        )
        payload = _serialize_agent(agent)
        if mtime is not None:
            _blueprint_payload_cache[key] = (mtime, dict(payload))
    payload["live_instances"] = team_obj.live_instances_for_blueprint(bp.name)
    return payload


def _validate_workspace_or_422(workspace: str) -> str:
    try:
        return team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _project_paths_for_session(
    db: DbSession, existing: ChatSession, workspace: str
) -> tuple[list[str], list[str]]:
    """(extra_workspace_paths, read_only_paths) for a project-bound session."""
    extra_ws_paths: list[str] = []
    read_only_paths: list[str] = []
    if existing.project_id is not None:
        from app.services.coding_project_service import get_project_workspace_paths

        async with db.begin():
            all_paths = await get_project_workspace_paths(db, existing.project_id)
        extra_ws_paths = [p for p in all_paths if p != workspace]
    return extra_ws_paths, read_only_paths


async def _team_for_session_mode(db: DbSession, session_id: str):
    """Resolve the live team that matches *session_id*'s persisted mode.

    Never binds a default-mode (work) team to a coding session id:
    ``_session_teams`` wins in ``find_team_for_session`` (the workflow
    runner's lookup), so one stray work boot would make every later
    pipeline in that session run with the work lead.
    """
    try:
        _, team_obj = await resolve_team_for_session(db, session_id)
        return team_obj
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NoTeamConfigured as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _changed_paths_payload(shift: BoundaryShift) -> dict:
    """Serialise the A/M/D path partition from a /undo or /redo restore.

    The client uses this to splice the cached Coding Workspace git
    diff for just these paths instead of refetching the whole sidebar.
    Empty lists are valid and meaningful — "no paths changed" still
    tells the client to skip invalidation entirely.
    """
    return {
        "added": shift.added,
        "modified": shift.modified,
        "removed": shift.removed,
    }


def _goal_response(goal) -> GoalResponse:
    return GoalResponse.model_validate(goal_service.snapshot(goal).model_dump())


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/chat", status_code=202)
async def team_chat(
    request: Request,
    db: ReadDbSession,
    write_db_factory: DbSessionFactory,
    body: ChatFormDep,
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """Deliver a message to the team lead (202). Accepts multipart/form-data.

    Modes:
    - **Normal send** (``interrupt=false``, ``message`` required):
      Deliver message to team lead and start a new turn.
    - **Interrupt-only** (``interrupt=true``, ``message`` omitted):
      Cancel all working members. Partial output already saved by checkpointer.
    - **Interrupt + follow-up** (``interrupt=true``, ``message`` provided):
      Cancel working members, then deliver new message to the team lead.

    Returns the session_id. Subscribe to GET /team/{session_id}/stream to
    receive the SSE event stream (supports reconnect + replay).
    """
    from app.agent.mode.team.team import (
        ContinuePreconditionError,
        is_goal_command,
        parse_goal_command,
    )

    message = body.message
    session_id = body.session_id
    interrupt = body.interrupt
    mode = body.mode
    workspace = body.workspace
    raw_form = await request.form()
    model_provided = "model" in raw_form
    thinking_level_provided = "thinking_level" in raw_form
    model = body.model.strip() if body.model else None
    thinking_level = body.thinking_level.strip() if body.thinking_level else None
    if model and not await is_registered_model_id(model):
        raise HTTPException(status_code=422, detail="Choose a model from the registry.")
    existing: ChatSession | None = None
    session_uuid: UUID | None = None

    if session_id:
        try:
            session_uuid = UUID(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid session id.") from exc
        async with db.begin():
            existing = await db.get(ChatSession, session_uuid)

    session_tags = set(existing.tags or ()) if existing is not None else set()
    if body.webbridge_enabled is not None:
        if body.webbridge_enabled:
            session_tags.add(WEBBRIDGE_SESSION_TAG)
        else:
            session_tags.discard(WEBBRIDGE_SESSION_TAG)

    if (
        WEBBRIDGE_SESSION_TAG in session_tags
        and not webbridge_manager.has_active_extension()
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "WebBridge is enabled, but no browser extension is connected. "
                "Connect it from the WebBridge panel and try again."
            ),
        )

    if body.webbridge_enabled is not None and existing is not None:
        async with write_db_factory() as write_db:
            async with write_db.begin():
                writable = await write_db.get(ChatSession, existing.id)
                if writable is not None:
                    writable.tags = sorted(session_tags) or None

    # A persisted session owns its mode and workspace. Request fields select
    # the context only when creating a new session; they can never migrate an
    # existing Work session into Coding (or vice versa) as a side effect.
    if existing is not None:
        try:
            persisted_mode = normalize_mode(existing.mode)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Session has unsupported persisted mode: {existing.mode}",
            ) from exc
        if persisted_mode == "coding":
            if not existing.workspace:
                raise HTTPException(
                    status_code=409,
                    detail="Coding session has no persisted workspace.",
                )
            persisted_workspace = _validate_workspace_or_422(existing.workspace)
            if mode == persisted_mode and workspace is not None:
                requested_workspace = _validate_workspace_or_422(workspace)
                if requested_workspace != persisted_workspace:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Session belongs to a different coding workspace: "
                            f"{persisted_workspace}"
                        ),
                    )
            workspace = persisted_workspace
        else:
            workspace = existing.workspace
        mode = persisted_mode

    if mode == "coding":
        if session_id is None:
            session_id = str(uuid7())
        assert workspace is not None
        workspace = _validate_workspace_or_422(workspace)
        extra_ws_paths: list[str] = []
        read_only_paths: list[str] = []
        if existing is not None:
            extra_ws_paths, read_only_paths = await _project_paths_for_session(
                db, existing, workspace
            )
        try:
            team_obj = await team_manager.get_or_start_coding_team(
                workspace,
                session_id,
                extra_workspace_paths=extra_ws_paths or None,
                mode=mode,
                read_only_paths=read_only_paths or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        if session_id is None:
            session_id = str(uuid7())
        team_obj = await team_manager.get_or_start_team_for_session(session_id)
        team_obj = _require_team(team_obj)
        # The persisted session is authoritative for Work workspaces.  A
        # reloaded/stale client may omit the field (or still carry the
        # previously selected folder), but the live team must always use the
        # folder most recently saved through PUT /{session_id}/workspace.
        if existing is not None:
            workspace = existing.workspace
        team_obj.workspace = workspace

    # Restore persisted session settings so the in-memory team reflects the
    # user's selection even after a server restart or a cold team boot.
    team_obj.session_tags = frozenset(session_tags)
    if existing is not None:
        team_obj.permission_mode = existing.permission_mode

    # An explicit blank model clears the session override and therefore uses
    # the lead default for this very turn. When the field is omitted, preserve
    # the persisted session selection. This same resolved id must drive both
    # attachment delivery and the runtime provider.
    effective_request_model = _resolve_effective_request_model(
        model,
        provided=model_provided,
        persisted=existing.model if existing is not None else None,
        default=team_obj.lead.agent.model_id,
    )
    effective_thinking_level = (
        thinking_level
        if thinking_level_provided
        else (existing.thinking_level if existing is not None else None)
    )
    await _validate_thinking_level_for_model(
        effective_request_model, effective_thinking_level
    )
    fast_mode_service_tier = _fast_tier(effective_request_model, body.fast_mode)

    # ── Interrupt (mutually exclusive with message) ─────────────────────────
    if interrupt:
        await agent_service.interrupt_team(team_obj, session_id)
        return {"status": "interrupted", "session_id": session_id}

    assert message is not None
    slash_invocation = parse_slash_invocation(message)
    if slash_invocation is not None and slash_invocation.command == "loop":
        raise HTTPException(
            status_code=410,
            detail="/loop has been removed. Use /goal <objective> instead.",
        )
    goal_command = None
    if is_goal_command(message):
        goal_command = parse_goal_command(message)
        if goal_command is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Invalid /goal command. Use /goal <objective>, /goal, "
                    "/goal:pause, /goal:resume, /goal:budget <tokens|none>, "
                    "or /goal:stop."
                ),
            )

    if body.shell:
        if files:
            raise HTTPException(
                status_code=422,
                detail="Shell commands cannot include file uploads.",
            )
        command = message.strip()
        if command.startswith("!"):
            command = command[1:].strip()
        if not command:
            raise HTTPException(status_code=422, detail="Shell command is required.")
        sid = await agent_service.dispatch_user_shell_command(
            team_obj,
            command=command,
            session_id=session_id,
            mode=mode,
            workspace=workspace,
            model=model,
            model_provided=model_provided,
            thinking_level=thinking_level,
            thinking_level_provided=thinking_level_provided,
            service_tier=fast_mode_service_tier,
        )
        logger.info("team_chat_shell_received session_id={}", sid)
        return {"status": "accepted", "session_id": sid}

    # Materialise the multipart uploads into transport-neutral attachments
    # so agent_service can validate + persist them without knowing about
    # FastAPI ``UploadFile``.
    attachments: list[RawAttachment] = []
    for file in files:
        raw = await _read_upload_as_attachment(file)
        if raw is not None:
            attachments.append(raw)
    explicit_attachment_count = len(attachments)

    # Resolve any ``@path`` mentions in the message text against the
    # session workspace and attach the matched files. Done before the
    # queue branch so a queued message keeps its mention attachments
    # rather than silently dropping them when the agent is busy. Missing
    # / oversize / unsupported paths are silently dropped (the visual
    # chip in the input already gates this on workspace-resolvable refs).
    # Explicit uploads above remain authoritative — mentions only *add*
    # context.
    mention_attachments = await collect_mention_attachments(
        message=message,
        team=team_obj,
        session_id=session_id,
        workspace=workspace,
        existing_total_bytes=sum(len(a.data) for a in attachments),
    )
    attachments.extend(mention_attachments)

    async with team_obj.user_message_lock:
        if session_uuid is not None:
            async with write_db_factory() as write_db:
                async with write_db.begin():
                    await cleanup_reverted_tail(write_db, session_uuid)

        if (
            session_uuid is not None
            and team_obj.has_active_user_turn()
            and goal_command is None
        ):
            # Explicit uploads still 409 — they need the live capability check
            # + persistence pipeline that only runs on the dispatch path. But
            # mentions are derived from workspace files the agent will see
            # anyway, so we persist them onto the queued row so the dequeue
            # path rehydrates the same context the user typed.
            if explicit_attachment_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot queue messages with attachments while the agent is working.",
                )
            queued_attachment_metas: list[dict] = []
            if mention_attachments:
                try:
                    (
                        _,
                        queued_attachment_metas,
                    ) = await agent_service.validate_and_persist_attachments(
                        team_obj,
                        mention_attachments,
                        session_id,
                        model_override=effective_request_model,
                    )
                except AttachmentError as exc:
                    raise HTTPException(
                        status_code=exc.status, detail=str(exc)
                    ) from exc
            async with write_db_factory() as write_db:
                async with write_db.begin():
                    queued_extra: dict[str, object] = {}
                    effective_model = model or team_obj.lead.agent.model_id
                    if effective_model:
                        queued_extra["model"] = effective_model
                    if thinking_level:
                        queued_extra["thinking_level"] = thinking_level
                    if fast_mode_service_tier:
                        queued_extra["service_tier"] = "fast"
                    if queued_attachment_metas:
                        queued_extra["attachments"] = queued_attachment_metas
                    existing_row = await write_db.get(ChatSession, session_uuid)
                    if existing_row is not None:
                        if model_provided:
                            existing_row.model = model
                        if thinking_level_provided:
                            existing_row.thinking_level = thinking_level
                        effective_model = (
                            existing_row.model or team_obj.lead.agent.model_id
                        )
                        if effective_model:
                            queued_extra["model"] = effective_model
                        if existing_row.thinking_level:
                            queued_extra["thinking_level"] = existing_row.thinking_level
                        if fast_mode_service_tier:
                            queued_extra["service_tier"] = "fast"
                        write_db.add(existing_row)
                    queued = await save_queued_user_message(
                        write_db,
                        session_uuid,
                        message,
                        extra=queued_extra,
                    )
            logger.info(
                "team_chat_queued session_id={} message_id={} mentions={}",
                session_id,
                queued.id,
                len(queued_attachment_metas),
            )
            if not team_obj.has_active_user_turn():
                await team_obj._activate_queued_user_messages(session_id)
            return {
                "status": "queued",
                "session_id": session_id,
                "message_id": str(queued.id),
            }

        try:
            sid, n_attachments = await agent_service.dispatch_user_message(
                team_obj,
                content=message,
                session_id=session_id,
                attachments=attachments,
                mode=mode,
                workspace=workspace,
                model=model,
                attachment_model=effective_request_model,
                model_provided=model_provided,
                thinking_level=thinking_level,
                thinking_level_provided=thinking_level_provided,
                service_tier=fast_mode_service_tier,
                # A normal user turn can acknowledge immediately after
                # validation/stream initialisation. Snapshot, persistence and
                # agent activation continue in-order in the background.
                # Goal controls stay synchronous because they mutate durable
                # state rather than queueing a prompt.
                defer=goal_command is None,
            )
        except AttachmentError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        except ContinuePreconditionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.reason) from exc

        logger.info(
            "team_chat_received session_id={} attachments={}",
            sid,
            n_attachments,
        )
        return {"status": "accepted", "session_id": sid}


@router.delete("/sessions/{session_id}/queued-messages/{message_id}", status_code=204)
async def cancel_queued_message(
    db: DbSession,
    session_id: UUID,
    message_id: UUID,
) -> None:
    async with db.begin():
        cancelled = await cancel_queued_user_message(db, session_id, message_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Queued message not found.")


class CommandRequest(BaseModel):
    """Request body for ``POST /team/commands``."""

    command: Literal["continue", "compact", "undo", "redo"]
    session_id: str


@router.post("/commands", status_code=202)
async def team_command(
    body: CommandRequest,
    db: DbSession,
) -> dict:
    """Run a slash-command on a session — no new user message persisted.

    Currently supported:

    * ``continue`` — resume from the last assistant turn.  The provider
      sees the existing history (ending in the prior assistant message)
      and keeps generating; the resulting first assistant row is flagged
      ``extra["is_continuation"] = True`` so the UI can render it tight
      against the prior bubble.
    * ``compact`` — force the existing summariser before the next model call
      without adding a visible user message.
    * ``undo`` / ``redo`` — move the visible conversation boundary backward or
      forward without adding a user message.

    Returns 202 with the session_id.  Subscribe to
    ``GET /team/{session_id}/stream`` for the SSE feed.

    Returns 409 with a human-readable ``detail`` when the session can't
    be continued (no assistant message, last message has unfinished tool
    calls, lead is already working, etc.).
    """
    from app.agent.mode.team.team import ContinuePreconditionError

    # Resolve by the session's persisted mode — booting the default
    # (work) team here for a coding session would poison the
    # session→team lookup for the rest of the process (see
    # _team_for_session_mode).
    team_obj = await _team_for_session_mode(db, body.session_id)

    if body.command == "continue":
        try:
            sid = await team_obj.handle_continue(body.session_id)
        except ContinuePreconditionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.reason) from exc
        logger.info("team_command_continue session_id={}", sid)
        return {"status": "accepted", "session_id": sid, "command": "continue"}

    if body.command == "compact":
        try:
            sid = await team_obj.handle_compact(body.session_id)
        except ContinuePreconditionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.reason) from exc
        logger.info("team_command_compact session_id={}", sid)
        return {"status": "accepted", "session_id": sid, "command": "compact"}

    if body.command == "undo":
        try:
            sid, shift = await team_obj.handle_undo(body.session_id)
        except ContinuePreconditionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.reason) from exc
        logger.info("team_command_undo session_id={}", sid)
        assert shift.target is not None
        return {
            "status": "accepted",
            "session_id": sid,
            "command": "undo",
            "message": _message_response(shift.target).model_dump(mode="json"),
            "changed_paths": _changed_paths_payload(shift),
        }

    if body.command == "redo":
        try:
            sid, shift = await team_obj.handle_redo(body.session_id)
        except ContinuePreconditionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.reason) from exc
        logger.info("team_command_redo session_id={}", sid)
        return {
            "status": "accepted",
            "session_id": sid,
            "command": "redo",
            "message": (
                _message_response(shift.target).model_dump(mode="json")
                if shift.target is not None
                else None
            ),
            "changed_paths": _changed_paths_payload(shift),
        }

    # Defensive — the Literal makes this unreachable, but pyright/ty wants it.
    raise HTTPException(status_code=400, detail=f"Unknown command: {body.command}")


@router.get("/{session_id}/stream")
async def team_stream(session_id: str, request: Request):
    """SSE stream for all team agent events.

    Replays buffered events from the current turn then delivers live events.
    Safe to reconnect — resumes from where you left off within the TTL window.
    """

    async def _gen() -> AsyncGenerator[dict, None]:
        try:
            async for event in stream_store.attach(session_id):
                if await request.is_disconnected():
                    break
                yield {
                    "event": event.get("event", "message"),
                    "data": event.get("data", "{}"),
                }
        except Exception as exc:
            logger.exception("team_stream_error type={}", type(exc).__name__)
            yield {
                "event": "error",
                "data": f'{{"type":"error","message":"stream_error:{type(exc).__name__}"}}',
            }

    return EventSourceResponse(_gen())


@router.get("/leads", response_model=TeamLeadListResponse)
async def list_team_leads(
    mode: str = Query("work", description="Lead roster mode: 'work' or 'coding'."),
) -> TeamLeadListResponse:
    try:
        normalized_mode = normalize_mode(mode)
        if normalized_mode not in {"work", "coding"}:
            raise ValueError("mode must be 'work' or 'coding'.")
        default_lead, rosters = await asyncio.to_thread(
            team_manager.configured_lead_rosters, normalized_mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TeamLeadListResponse(
        mode=cast(Literal["work", "coding"], normalized_mode),
        default_lead=default_lead,
        leads=[
            TeamLeadResponse(
                name=lead.name,
                description=lead.description,
                model=lead.model,
                is_default=lead.name == default_lead,
                members=[
                    TeamLeadMemberResponse(
                        name=member.name,
                        description=member.description,
                        model=member.model,
                    )
                    for member, _member_path in members
                ],
            )
            for lead, _lead_path, members in rosters
        ],
    )


@router.get("/agents")
async def list_team_agents(
    db: ReadDbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
    mode: str = Query(
        "coding",
        description="Which roster the workspace team uses: 'coding'. "
        "Ignored without a workspace (the default work team has one roster).",
    ),
    session_id: UUID | None = Query(
        None, description="Open top-level session whose persisted lead owns the roster."
    ),
) -> dict:
    """Return info on the lead, all live member instances, and spawnable blueprints.

    Refreshes drifted-but-idle agents from disk before serializing so the
    capabilities panel reflects what the *next* turn will use, not the
    config that was loaded the last time the agent woke up.  Without this
    nudge the UI keeps showing the previously-active model after the user
    edits ``model:`` / ``tools:`` / ``skills:`` in the settings page until
    they happen to send another message.

    Working agents are skipped — refreshing them would race ``agent.run()``
    swapping ``self.agent`` mid-execution.  Those will pick up their edits
    via the regular start-of-turn path.

    Response shape::

        {
          "agents": [<lead>, <live members>...],
          "blueprints": [
            {"name": "executor", "description": "...",
             "live_instances": ["executor#1", "executor#2"]},
            ...
          ]
        }
    """
    selected_lead: str | None = None
    runtime_session_id = str(session_id) if session_id is not None else None
    if session_id is not None:
        session = await db.get(ChatSession, session_id)
        if session is None or session.parent_session_id is not None:
            raise HTTPException(status_code=404, detail="Session not found.")
        persisted_mode = normalize_mode(session.mode)
        if persisted_mode not in {"work", "coding"}:
            raise HTTPException(status_code=409, detail="Session has unsupported mode.")
        mode = persisted_mode
        workspace = session.workspace if mode == "coding" else None
        try:
            selected_lead = await asyncio.to_thread(
                team_manager.resolve_configured_lead,
                mode,
                session.agent_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if workspace:
        mode = normalize_mode(mode)
        if mode != "coding":
            raise HTTPException(status_code=422, detail="mode must be 'coding'.")
        try:
            team_obj = await team_manager.get_or_start_coding_team(
                workspace,
                runtime_session_id or f"__agents_{mode}__",
                mode=mode,
                lead_name=selected_lead,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        # Resolved lazily instead of via TeamDep so the coding branch above
        # never pays for (or waits on) a default-team boot it won't use.
        team_obj = _require_team(
            await team_manager.get_or_start_team_for_session(
                runtime_session_id, lead_name=selected_lead
            )
            if runtime_session_id
            else await team_manager.get_or_start_team()
        )
    # Rediscover blueprint files from disk before serializing so newly
    # created members (Settings → Agents) appear without a server restart.
    team_manager.refresh_blueprints(team_obj)
    team_manager.refresh_idle_agents(team_obj)
    all_members: list[TeamMemberBase] = [team_obj.lead, *team_obj.members.values()]
    blueprints = [
        _serialize_blueprint(team_obj, bp) for bp in team_obj.blueprints.values()
    ]
    return {
        "agents": [
            _serialize_agent(m.agent, is_lead=(m is team_obj.lead)) for m in all_members
        ],
        "blueprints": blueprints,
        "mode": team_obj.mode,
        "workspace": team_obj.workspace,
        "lead_name": team_obj.lead.name,
    }


@router.get("/workspace/validate")
async def validate_coding_workspace(
    workspace: str = Query(..., description="Coding workspace directory."),
) -> dict:
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"workspace": resolved}


def _dedupe_named_paths(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Collapse ``(name, resolved_path)`` pairs sharing a resolved path.

    Windows ships legacy compatibility junctions (e.g. "My Documents", "My
    Pictures") that resolve to the same target as their modern counterpart
    ("Documents", "Pictures"). Left unfiltered, both show up as distinct
    directory entries with an identical ``path`` — the frontend uses that
    as a React list key, so a duplicate collides. First-seen name wins;
    input order (and thus the caller's sort) is preserved.
    """
    seen_paths: set[str] = set()
    result: list[dict[str, str]] = []
    for name, resolved_path in pairs:
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        result.append({"name": name, "path": resolved_path})
    return result


@router.get("/workspace/browse")
async def browse_coding_workspace(
    path: str | None = Query(None, description="Directory to list."),
) -> dict:
    root = Path(path).expanduser().resolve() if path else Path.home().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail=f"Not a directory: {root}")

    try:
        entries = sorted(root.iterdir(), key=lambda entry: entry.name.lower())
    except OSError as exc:
        raise HTTPException(
            status_code=403, detail=f"Cannot read directory: {root}"
        ) from exc

    named_paths: list[tuple[str, str]] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if not entry.is_dir():
                continue
            named_paths.append((entry.name, str(entry.resolve())))
        except OSError:
            continue

    directories = _dedupe_named_paths(named_paths)

    return {
        "path": str(root),
        "parent": str(root.parent) if root.parent != root else None,
        "directories": directories,
    }


@router.get("/sessions")
async def list_team_sessions(
    db: DbSession,
    before: str | None = Query(
        None,
        description="ISO 8601 created_at cursor — return sessions older than this.",
    ),
    limit: int = Query(20, ge=1, le=100),
    mode: str | None = Query(None),
    workspace: str | None = Query(None),
    project_id: UUID | None = Query(None),
) -> SessionPageResponse:
    """List team lead sessions newest-first, cursor-paginated by created_at.

    Pass ``before=<created_at_iso>`` (the ``next_cursor`` from the previous
    page) to retrieve the next batch.  Omit to start from the newest.
    """
    if mode is not None:
        mode = normalize_mode(mode)
        if mode not in {"work", "coding"}:
            raise HTTPException(status_code=422, detail="Invalid mode")
    if workspace is not None and mode != "coding":
        raise HTTPException(status_code=422, detail="workspace requires mode=coding")

    try:
        sessions, next_cursor, has_more = await list_sessions_page(
            db,
            before=before,
            limit=limit,
            mode=mode,
            workspace=workspace,
            project_id=project_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid 'before' cursor — expected ISO 8601 datetime.",
        )

    running_session_ids = stream_store.running_session_ids()
    return SessionPageResponse(
        data=[
            SessionResponse.model_validate(s).model_copy(
                update={"running": str(s.id) in running_session_ids}
            )
            for s in sessions
        ],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/sessions/resolve", response_model=TeamSessionResolveResponse)
async def resolve_team_session(
    body: TeamSessionResolveRequest, db: DbSession
) -> TeamSessionResolveResponse:
    """Return the newest matching top-level session, creating one if absent."""
    body.mode = normalize_mode(body.mode)
    if body.mode not in {"work", "coding"}:
        raise HTTPException(status_code=422, detail="mode must be 'work' or 'coding'.")
    try:
        default_lead, _rosters = await asyncio.to_thread(
            team_manager.configured_lead_rosters, body.mode
        )
        requested_lead = (
            await asyncio.to_thread(
                team_manager.resolve_configured_lead,
                body.mode,
                body.agent_name,
            )
            if body.agent_name
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    model = body.model.strip() if body.model else None
    thinking_level = body.thinking_level.strip() if body.thinking_level else None
    if model and not await is_registered_model_id(model):
        raise HTTPException(status_code=422, detail="Choose a model from the registry.")
    await _validate_thinking_level_for_model(model, thinking_level)

    workspace = body.workspace
    project_id = body.project_id
    folder_id = body.folder_id
    if body.mode == "work":
        workspace = None
        project_id = None
        if body.worktree_from or body.worktree_name or body.worktree_branch:
            raise HTTPException(
                status_code=422, detail="worktree options require mode='coding'."
            )
    elif project_id is not None:
        # Project-mode: derive the primary workspace from the project. A
        # project session spans all repos; it is matched/reused by
        # project_id, never by this derived path (see
        # get_latest_top_level_session).
        from app.services.coding_project_service import get_project_workspace_paths

        async with db.begin():
            paths = await get_project_workspace_paths(db, project_id)
        if not paths:
            raise HTTPException(
                status_code=422,
                detail="Project has no workspaces configured.",
            )
        # Fail fast with a clear 422 if the primary repo path is stale/missing.
        workspace = _validate_workspace_or_422(paths[0])
    elif body.worktree_from or body.worktree_name or body.worktree_branch:
        if not body.worktree_from or not body.worktree_name:
            raise HTTPException(
                status_code=422,
                detail="worktree_from and worktree_name are required for worktree sessions.",
            )
        source_workspace = _validate_workspace_or_422(body.worktree_from)
        # Fail before creating a worktree when its source repo belongs to more
        # than one project. Picking one here would make the resulting session
        # disappear into an arbitrary project in the sidebar.
        async with db.begin():
            source_project_ids = await get_visible_project_ids_for_workspace_path(
                db, source_workspace
            )
        if len(source_project_ids) > 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Workspace belongs to multiple projects. Open the target "
                    "project first, then create the worktree from there."
                ),
            )
        if source_project_ids:
            project_id = source_project_ids[0]
        created_worktree = await create_coding_workspace_worktree(
            WorktreeCreateRequest(
                source_workspace=source_workspace,
                name=body.worktree_name,
                branch=body.worktree_branch,
            )
        )
        workspace = created_worktree.directory
        # A worktree request always represents a new coding workspace/session,
        # even if the caller omitted create=true.
        body.create = True
    elif not workspace:
        raise HTTPException(
            status_code=422,
            detail=f"workspace is required when mode='{body.mode}'.",
        )
    else:
        workspace = _validate_workspace_or_422(workspace)

    # Keep session ownership aligned with the sidebar's project-only rule.
    # Before this canonicalisation, opening a project-owned repo through the
    # standalone "+" succeeded but produced a session the Workspaces filter
    # could never render. Worktrees inherit ownership from their source repo.
    if body.mode == "coding" and workspace and project_id is None:
        async with db.begin():
            inferred_project_ids = await get_visible_project_ids_for_workspace_path(
                db, workspace
            )
        if len(inferred_project_ids) > 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Workspace belongs to multiple projects. Open one of those "
                    "projects explicitly instead of opening it as standalone."
                ),
            )
        if inferred_project_ids:
            project_id = inferred_project_ids[0]

    # Normalise to a sorted unique list so tag-set equality is a plain array
    # comparison (see get_latest_top_level_session); empty stays NULL on write.
    session_tags = sorted(set(body.tags))
    async with db.begin():
        # Validated inside the transaction: any read before ``db.begin()``
        # autobegins one and makes entering it raise.
        if folder_id is not None:
            folder = await get_folder(db, folder_id)
            if folder is None:
                raise HTTPException(status_code=404, detail="Folder not found.")
            if normalize_mode(folder.mode) != body.mode:
                raise HTTPException(
                    status_code=422,
                    detail="Folder belongs to a different mode than the session.",
                )
        session = None
        if not body.create:
            session = await get_latest_top_level_session(
                db,
                mode=body.mode,
                workspace=workspace,
                project_id=project_id,
                folder_id=folder_id,
                tags=session_tags,
                tag_match=body.tag_match,
                agent_name=requested_lead,
                include_unassigned_agent=requested_lead == default_lead,
            )
        created = session is None
        if session is None:
            session = ChatSession(
                mode=body.mode,
                agent_name=requested_lead or default_lead,
                workspace=workspace,
                project_id=project_id,
                folder_id=folder_id,
                model=model,
                thinking_level=thinking_level,
                tags=session_tags or None,
            )
            db.add(session)
        elif session.agent_name is None:
            session.agent_name = default_lead
            db.add(session)
        if body.mode == "coding" and workspace:
            managed_source = find_managed_worktree_source(Path(workspace))
            if managed_source:
                await upsert_coding_workspace(
                    db,
                    path=managed_source,
                    kind="repo",
                    hidden=False,
                )
                await upsert_coding_workspace(
                    db,
                    path=workspace,
                    kind="worktree",
                    source_path=managed_source,
                    managed=True,
                    hidden=False,
                )
            else:
                await upsert_coding_workspace(
                    db, path=workspace, kind="repo", hidden=False
                )
        await db.flush()
        await db.refresh(session)

    data = SessionResponse.model_validate(session).model_dump()
    team_manager.prewarm_session_team(
        mode=session.mode,
        session_id=str(session.id),
        workspace=session.workspace,
        lead_name=session.agent_name,
    )
    return TeamSessionResolveResponse(**data, created=created)


@router.patch("/workspace/visibility")
async def update_coding_workspace_visibility(
    body: TeamWorkspaceVisibilityRequest, db: DbSession
) -> dict:
    workspace = (
        str(Path(body.workspace).expanduser().resolve())
        if body.hidden
        else _validate_workspace_or_422(body.workspace)
    )
    if body.hidden:
        try:
            await purge_workspace(db, workspace)
        except PurgeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        async with db.begin():
            await upsert_coding_workspace(db, path=workspace, kind="repo", hidden=False)
    return {"workspace": workspace, "hidden": body.hidden}


@router.get("/workspace/tree", response_model=CodingWorkspaceTreeResponse)
async def list_coding_workspace_tree(db: DbSession) -> CodingWorkspaceTreeResponse:
    """Every visible repo (standalone or project-owned) plus the full
    projects list, in one response — the sidebar renders both the Projects
    and Workspaces sections from this alone. project_id per repo comes from
    a real CodingProjectWorkspace lookup, not path-string matching against
    a separately-fetched projects list."""
    rows = await list_visible_coding_workspaces(db)
    # Only live Coding projects own sidebar placement. A stale link to a
    # hidden/soft-deleted project must not suppress the repository from the
    # standalone Workspaces section when that project is absent from Projects.
    membership_rows = (
        await db.exec(
            select(
                CodingProjectWorkspace.workspace_id,
                CodingProjectWorkspace.project_id,
            )
            .join(
                CodingProject,
                col(CodingProject.id) == col(CodingProjectWorkspace.project_id),
            )
            .where(
                ~col(CodingProject.hidden),
                col(CodingProject.deleted_at).is_(None),
                CodingProject.kind == "coding",
            )
            .order_by(col(CodingProject.created_at).asc())
        )
    ).all()
    # A repository can belong to more than one visible project. The response
    # shape exposes one owner only; keep the oldest deterministic owner, while
    # project lists still show every real membership.
    membership: dict[UUID, UUID] = {}
    for workspace_id, project_id in membership_rows:
        membership.setdefault(workspace_id, project_id)
    repositories: dict[str, CodingWorkspaceTreeRepository] = {}
    pending_worktrees = []
    for row in rows:
        if row.kind == "worktree":
            pending_worktrees.append(row)
            continue
        repositories[row.path] = CodingWorkspaceTreeRepository(
            workspace_id=row.id,
            path=row.path,
            name=row.name or Path(row.path).name,
            worktrees=[],
            project_id=membership.get(row.id),
        )
    for row in pending_worktrees:
        source = row.source_path
        if not source:
            continue
        if source not in repositories:
            repositories[source] = CodingWorkspaceTreeRepository(
                path=source,
                name=Path(source).name,
                worktrees=[],
            )
        repositories[source].worktrees.append(
            CodingWorkspaceTreeWorktree(
                path=row.path,
                name=row.name or Path(row.path).name,
                managed=row.managed,
            )
        )
    return CodingWorkspaceTreeResponse(
        repositories=list(repositories.values()),
        projects=await list_project_responses(db),
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_team_session_detail(
    session_id: UUID, db: DbSession
) -> SessionDetailResponse:
    """Return one team lead session with its most recent messages."""
    history = await get_team_history(db, session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    lead_resp = SessionResponse.model_validate(history.lead_session).model_copy(
        update={
            "running": str(history.lead_session.id)
            in stream_store.running_session_ids()
        }
    )
    return SessionDetailResponse(
        **lead_resp.model_dump(),
        messages=[_message_response(m) for m in history.lead_messages],
    )


@router.get("/sessions/{session_id}/metadata", response_model=SessionResponse)
async def get_team_session_metadata(session_id: UUID, db: DbSession) -> SessionResponse:
    """Return session metadata without hydrating its message history."""
    session = await db.get(ChatSession, session_id)
    if session is None or session.parent_session_id is not None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionResponse.model_validate(session).model_copy(
        update={"running": str(session.id) in stream_store.running_session_ids()}
    )


@router.get("/{session_id}/goal", response_model=GoalResponse | None)
async def get_session_goal(session_id: UUID, db: DbSession) -> GoalResponse | None:
    """Return the durable goal attached to a session, if one exists."""

    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    goal = await goal_service.get_goal(db, session_id)
    return _goal_response(goal) if goal is not None else None


class TurnChangedFileOut(BaseModel):
    path: str
    status: Literal["added", "modified", "removed", "changed"] = "changed"
    additions: int | None = None
    deletions: int | None = None


class TurnChangesOut(BaseModel):
    session_id: str
    additions: int = 0
    deletions: int = 0
    files: list[TurnChangedFileOut] = []


@router.get("/sessions/{session_id}/changes", response_model=TurnChangesOut)
async def get_session_turn_changes(session_id: UUID) -> TurnChangesOut:
    """Return the latest post-turn file-change snapshot for a lead session."""
    from app.services import turn_changes as turn_changes_svc

    snap = turn_changes_svc.get_latest(str(session_id))
    if snap is None:
        return TurnChangesOut(session_id=str(session_id))
    return TurnChangesOut(
        session_id=snap.session_id,
        additions=snap.additions,
        deletions=snap.deletions,
        files=[TurnChangedFileOut(**f.to_dict()) for f in snap.files],
    )


@router.patch("/sessions/{session_id}")
async def update_team_session(
    session_id: UUID, body: TeamSessionUpdateRequest, db: DbSession
) -> SessionResponse:
    """Update editable metadata for a top-level team session."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title cannot be empty.")
    session = await update_session_title(db, session_id, title)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionResponse.model_validate(session).model_copy(
        update={"running": str(session.id) in stream_store.running_session_ids()}
    )


@router.patch("/sessions/{session_id}/lead", response_model=SessionResponse)
async def update_team_session_lead(
    session_id: UUID,
    body: TeamSessionLeadUpdateRequest,
    db: DbSession,
) -> SessionResponse:
    """Switch one idle top-level session to another same-mode lead roster."""

    session = await db.get(ChatSession, session_id)
    if session is None or session.parent_session_id is not None:
        raise HTTPException(status_code=404, detail="Session not found.")
    live_team = team_manager.find_team_for_session(str(session_id))
    if str(session_id) in stream_store.running_session_ids() or (
        live_team is not None
        and any(member.state == "working" for member in live_team.all_members)
    ):
        raise HTTPException(
            status_code=409,
            detail="Finish or stop the active team turn before changing lead.",
        )
    mode = normalize_mode(session.mode)
    try:
        selected = await asyncio.to_thread(
            team_manager.resolve_configured_lead,
            mode,
            body.lead_name.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    previous = session.agent_name
    if previous != selected:
        session.agent_name = selected
        db.add(session)
        await db.commit()
        await db.refresh(session)
        await team_manager.stop_sessions({str(session_id)})
        logger.info(
            "team_session_lead_changed session_id={} mode={} old_lead={} new_lead={}",
            session_id,
            mode,
            previous,
            selected,
        )
    return SessionResponse.model_validate(session).model_copy(update={"running": False})


@router.post(
    "/sessions/{session_id}/duplicate",
    response_model=SessionResponse,
    status_code=201,
)
async def duplicate_team_session(session_id: UUID, db: DbSession) -> SessionResponse:
    """Create an independent copy of a completed chat conversation."""
    if str(session_id) in stream_store.running_session_ids():
        raise HTTPException(
            status_code=409,
            detail="Wait for the session to finish before duplicating it.",
        )
    session = await duplicate_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return SessionResponse.model_validate(session)


_VALID_PERMISSION_MODES = frozenset({"ask", "accept-edits", "plan", "auto", "bypass"})


class PermissionModeRequest(BaseModel):
    mode: str


@router.patch("/sessions/{session_id}/permission-mode", status_code=200)
async def set_session_permission_mode(
    session_id: UUID, body: PermissionModeRequest, db: DbSession
) -> dict:
    """Persist the agent permission mode for a session.

    ``mode`` must be one of: ``ask``, ``accept-edits``, ``plan``, ``auto``, ``bypass``.
    The in-memory team is updated if one is loaded, and any *running* agent's
    permission service switches immediately — pending requests the new mode
    no longer gates are auto-resolved so a blocked agent resumes.
    """
    if body.mode not in _VALID_PERMISSION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{body.mode}'. Must be one of: {sorted(_VALID_PERMISSION_MODES)}",
        )

    async with db.begin():
        session = await db.get(ChatSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        session.permission_mode = body.mode
        session_mode = session.mode
        session_workspace = session.workspace

    sid = str(session_id)
    # Peek only — the persisted mode is picked up at the next team boot, so
    # starting a team here just to set an attribute wastes a full cold boot.
    team_obj = team_manager.current_team_for_session(sid)
    if team_obj is None and session_mode == "coding" and session_workspace:
        team_obj = team_manager.current_coding_team_for_session(session_workspace, sid)
    if team_obj is not None:
        team_obj.permission_mode = body.mode

    # Flip live permission services (agents mid-run) to the new mode.  Each
    # service auto-resolves pending requests the new mode no longer gates and
    # publishes permission_replied events that close open approval UIs.
    from app.agent.permission import Mode, get_services_for_stream

    auto_resolved: list[str] = []
    for service in get_services_for_stream(sid):
        auto_resolved.extend(service.set_mode(cast(Mode, body.mode)))
    if auto_resolved:
        logger.info(
            "permission_mode_switch_resolved session_id={} mode={} request_ids={}",
            sid,
            body.mode,
            auto_resolved,
        )

    return {"session_id": sid, "permission_mode": body.mode}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_team_session(session_id: UUID, db: DbSession) -> None:
    """Delete a team session, all its messages, and uploaded files."""
    found = await delete_session(db, session_id)
    if not found:
        raise HTTPException(status_code=404, detail="Session not found.")


@router.get("/{session_id}/history")
async def team_history(
    db: DbSession,
    session_id: UUID,
    before: str | None = Query(default=None),
) -> TeamHistoryResponse:
    """Return the latest page of turn history (cursor-based, newest-first page).

    Pass ``before`` (ISO 8601 ``created_at`` of the oldest message from the
    previous response) to load an older page.
    """
    try:
        history = await get_team_history(db, session_id, before=before)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid before cursor: {before}"
        ) from exc
    if history is None:
        raise HTTPException(status_code=404, detail="Lead session not found.")
    team_manager.prewarm_session_team(
        mode=history.lead_session.mode,
        session_id=str(history.lead_session.id),
        workspace=history.lead_session.workspace,
    )
    goal_row = await goal_service.get_goal(db, history.lead_session.id)
    goal_response = _goal_response(goal_row) if goal_row is not None else None
    lead_resp = SessionResponse.model_validate(history.lead_session).model_copy(
        update={
            "running": str(history.lead_session.id)
            in stream_store.running_session_ids()
        }
    )
    lead_detail = SessionDetailResponse(
        **lead_resp.model_dump(),
        messages=[_message_response(m) for m in history.lead_messages],
    )

    member_histories = [
        TeamHistoryMember(
            name=member.session.agent_name or str(member.session.id),
            session_id=str(member.session.id),
            messages=[_message_response(m) for m in member.messages],
        )
        for member in history.members
    ]

    next_cursor = history.next_cursor

    workflow_execution: dict | None = None
    try:
        from app.workflow.runner import runner as workflow_runner

        wf_state = workflow_runner.get(str(history.lead_session.id))
        if wf_state is not None:
            order = wf_state.graph.order
            current = wf_state.current_node_id or wf_state.pending_node
            workflow_execution = {
                "execution_id": str(wf_state.execution_id),
                "definition_name": wf_state.definition.name,
                "status": wf_state.status,
                "node_id": current,
                "node_index": (order.index(current) + 1) if current in order else None,
                "total_nodes": len(order),
            }
    except Exception:  # noqa: BLE001 — history must never fail on this
        workflow_execution = None

    return TeamHistoryResponse(
        lead=lead_detail,
        members=member_histories,
        goal=goal_response,
        workflow_execution=workflow_execution,
        has_more=history.has_more,
        next_cursor=next_cursor,
    )


# ── Side Chat ────────────────────────────────────────────────────────────────
#
# Tool exclusion and the read-only system-prompt addendum live in
# app.agent.mode.team.tier_policy (side_chat_session_excluded_tools) and
# app.agent.mode.team.member (SIDE_CHAT_SESSION_PROMPT) — applied via the
# "side_chat" session tag set on the session by create_side_chat_session,
# the same mechanism WebBridge sessions use. Not imported here: nothing in
# this file needs them directly, tagging happens once at session creation.


class SideChatCreateRequest(BaseModel):
    """Request body for creating a side chat session."""

    title: str | None = None


class SideChatMessageRequest(BaseModel):
    """Request body for sending a message to a side chat."""

    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, content: str) -> str:
        if not content.strip():
            raise ValueError("content must not be blank")
        return content


def _side_chat_belongs_to_source(
    side_chat: ChatSession | None,
    source_session_id: UUID,
) -> bool:
    """Validate side-chat ownership even after its source FK is cleared."""
    if side_chat is None or side_chat.session_type != "side_chat":
        return False
    source_ref = side_chat.source_session_ref or side_chat.source_session_id
    return source_ref == source_session_id


@router.post("/{session_id}/side-chat", response_model=SessionResponse)
async def create_side_chat(
    session_id: UUID,
    db: DbSession,
    body: SideChatCreateRequest | None = None,
) -> SessionResponse:
    """Create a side chat session with read-only access to the main session.

    The side chat inherits the main session's workspace, mode, and project
    settings but operates independently with its own message history.
    """
    from app.services.chat_service import create_side_chat_session

    try:
        side_chat = await create_side_chat_session(
            db,
            session_id,
            title=body.title if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionResponse.model_validate(side_chat)


@router.get("/{session_id}/side-chat/{side_chat_id}/messages")
async def get_side_chat_messages(
    session_id: UUID,
    side_chat_id: UUID,
    db: DbSession,
) -> list[MessageResponse]:
    """Get messages for a side chat session.

    Returns the side chat's own message history (not the source context).
    """
    side_chat = await db.get(ChatSession, side_chat_id)
    if not _side_chat_belongs_to_source(side_chat, session_id):
        raise HTTPException(status_code=404, detail="Side chat not found")
    assert side_chat is not None

    from app.services.chat_service import get_visible_session_rows

    rows = await get_visible_session_rows(db, side_chat_id)
    return [_message_response(row) for row in rows]


@router.post("/{session_id}/side-chat/{side_chat_id}/message", status_code=202)
async def send_side_chat_message(
    session_id: UUID,
    side_chat_id: UUID,
    body: SideChatMessageRequest,
    db: DbSession,
) -> dict:
    """Send a message to a side chat session.

    This creates a side chat agent run with restricted tools (read-only).
    Subscribe to GET /team/{side_chat_id}/stream for the SSE feed.
    """
    # Read inside an explicit transaction block so it closes before
    # _team_for_session_mode opens its own `db.begin()` below — an implicit
    # transaction left open by a bare `db.get()` would make that begin()
    # raise "transaction already in progress".
    async with db.begin():
        side_chat = await db.get(ChatSession, side_chat_id)

    if not _side_chat_belongs_to_source(side_chat, session_id):
        raise HTTPException(status_code=404, detail="Side chat not found")
    assert side_chat is not None

    # Kick off the side chat agent run in the background. The team flow
    # persists the user message itself (AgentTeam.handle_user_message), so
    # only save it here as a fallback when no run could be dispatched —
    # saving unconditionally would double every user message.
    from app.agent.schemas.chat import HumanMessage
    from app.services import agent_service
    from app.services.chat_service import save_message

    try:
        # Reuse the team_for_session_mode to get the right team
        team_obj = await _team_for_session_mode(db, str(side_chat_id))
    except Exception as exc:
        logger.warning("side_chat_team_resolve_failed error={}", exc)
        team_obj = None

    dispatched = False
    if team_obj is not None:
        # Dispatch through the normal team flow — the side chat agent
        # will use excluded_tools to restrict to read-only.
        try:
            await agent_service.dispatch_user_message(
                team_obj,
                content=body.content,
                session_id=str(side_chat_id),
                mode=side_chat.mode,
                workspace=side_chat.workspace,
            )
            dispatched = True
        except Exception as exc:
            logger.warning("side_chat_dispatch_failed error={}", exc)

    if not dispatched:
        await save_message(db, side_chat_id, HumanMessage(content=body.content))
        await db.commit()
        raise HTTPException(status_code=503, detail="Side chat agent unavailable")

    return {"status": "accepted", "session_id": str(side_chat_id)}


@router.get("/{session_id}/side-chat/{side_chat_id}/stream")
async def side_chat_stream(
    session_id: UUID,
    side_chat_id: UUID,
    request: Request,
    db: WriteDbSession,
):
    """SSE stream for side chat agent events.

    Uses the side chat's own session ID for streaming, isolated from the
    main session's event feed.
    """
    # Validate the side chat exists and belongs to this main session
    async with db.begin():
        sc = await db.get(ChatSession, side_chat_id)

    if not _side_chat_belongs_to_source(sc, session_id):
        raise HTTPException(status_code=404, detail="Side chat not found")

    async def _gen() -> AsyncGenerator[dict, None]:
        try:
            async for event in stream_store.attach(str(side_chat_id)):
                if await request.is_disconnected():
                    break
                yield {
                    "event": event.get("event", "message"),
                    "data": event.get("data", "{}"),
                }
        except Exception as exc:
            logger.exception("side_chat_stream_error type={}", type(exc).__name__)
            yield {
                "event": "error",
                "data": f'{{"type":"error","message":"stream_error:{type(exc).__name__}"}}',
            }

    return EventSourceResponse(_gen())
