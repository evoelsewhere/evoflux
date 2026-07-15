"""Permission request list/reply endpoints."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.api.schemas.team import (
    PermissionReplyRequest,
    PermissionRequestResponse,
    PlanReplyRequest,
)

router = APIRouter()


@router.get("/{session_id}/permissions")
async def list_permissions(session_id: str) -> dict:
    """Return all pending permission requests for *session_id*.

    Permissions accumulate while a tool execution is blocked awaiting user
    approval.  Poll this endpoint or listen to ``permission_asked`` SSE events.

    *session_id* is the stream (lead) session — pending requests from every
    team member publishing to that stream are included.
    """
    from app.agent.permission import get_services_for_stream

    return {
        "permissions": [
            PermissionRequestResponse(
                id=req.id,
                session_id=req.session_id,
                tool=req.tool,
                patterns=req.patterns,
                metadata=req.metadata,
            ).model_dump()
            for service in get_services_for_stream(session_id)
            for req in service.list_pending()
        ]
    }


@router.post("/{session_id}/permissions/{request_id}/reply", status_code=200)
async def reply_permission(
    session_id: str,
    request_id: str,
    body: PermissionReplyRequest,
) -> dict:
    """Reply to a pending permission request.

    ``reply`` must be one of:
    - ``"once"``   — allow this single invocation
    - ``"always"`` — allow this command pattern for the rest of the session
    - ``"reject"`` — deny this invocation and raise an error to the agent

    *session_id* is the stream (lead) session; the request is resolved on
    whichever member service owns it.  The service publishes the
    ``permission_replied`` SSE event that closes the approval UI.
    """
    from app.agent.permission import get_services_for_stream

    valid_replies = {"once", "always", "reject"}
    if body.reply not in valid_replies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reply '{body.reply}'. Must be one of: {sorted(valid_replies)}",
        )

    # Validation above guarantees ``body.reply`` is one of the literal values.
    reply = cast(Literal["once", "always", "reject"], body.reply)
    resolved = any(
        service.reply(request_id, reply)
        for service in get_services_for_stream(session_id)
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"Permission request '{request_id}' not found or already resolved.",
        )

    logger.info(
        "permission_replied session_id={} request_id={} reply={}",
        session_id,
        request_id,
        body.reply,
    )
    return {"status": "ok", "request_id": request_id, "reply": body.reply}


# ── Plan approval ─────────────────────────────────────────────────────────────


@router.post("/{session_id}/plan/reply", status_code=200)
async def reply_plan_approval(session_id: str, body: PlanReplyRequest) -> dict:
    """Reply to a pending plan-approval request.

    ``decision`` must be ``"approved"``, ``"rejected"`` or ``"revise"``.

    - ``"approved"`` — unblocks the agent; it will execute the recorded steps.
    - ``"revise"`` — unblocks the agent with the user's ``feedback``; it
      stays in plan mode and submits a revised plan.
    - ``"rejected"`` — unblocks the agent; it will abandon the plan
      (``feedback`` optionally carries the reason).
    """
    from app.agent.plan import get_service_for_session

    valid = {"approved", "rejected", "revise"}
    if body.decision not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision '{body.decision}'. Must be one of: {sorted(valid)}",
        )

    svc = get_service_for_session(session_id)
    if svc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active plan approval for session '{session_id}'.",
        )

    from typing import cast as _cast

    resolved = svc.reply(
        body.request_id,
        _cast(Literal["approved", "rejected", "revise"], body.decision),  # type: ignore[arg-type]
        body.feedback or "",
    )
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"Plan request '{body.request_id}' not found or already resolved.",
        )

    logger.info(
        "plan_replied session_id={} request_id={} decision={}",
        session_id,
        body.request_id,
        body.decision,
    )
    return {"status": "ok", "request_id": body.request_id, "decision": body.decision}
