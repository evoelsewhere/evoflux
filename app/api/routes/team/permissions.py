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
    """
    from app.agent.permission import get_permission_service

    service = get_permission_service()
    if service.session_id != session_id:
        return {"permissions": []}

    pending = service.list_pending()
    return {
        "permissions": [
            PermissionRequestResponse(
                id=req.id,
                session_id=req.session_id,
                tool=req.tool,
                patterns=req.patterns,
                metadata=req.metadata,
            ).model_dump()
            for req in pending
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
    """
    from app.agent.permission import get_permission_service

    valid_replies = {"once", "always", "reject"}
    if body.reply not in valid_replies:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid reply '{body.reply}'. Must be one of: {sorted(valid_replies)}",
        )

    service = get_permission_service()
    # Validation above guarantees ``body.reply`` is one of the literal values.
    resolved = service.reply(
        request_id, cast(Literal["once", "always", "reject"], body.reply)
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

    # Push SSE so the frontend closes the permission modal immediately.
    import contextlib as _cl
    from app.agent.schemas.events import PermissionRepliedEvent
    from app.services import memory_stream_store as stream_store
    from app.services.stream_envelope import StreamEnvelope

    with _cl.suppress(Exception):
        await stream_store.push_event(
            session_id,
            StreamEnvelope.from_event(
                PermissionRepliedEvent(
                    request_id=request_id,
                    session_id=session_id,
                    reply=body.reply,
                )
            ),
        )

    return {"status": "ok", "request_id": request_id, "reply": body.reply}


# ── Plan approval ─────────────────────────────────────────────────────────────


@router.post("/{session_id}/plan/reply", status_code=200)
async def reply_plan_approval(session_id: str, body: PlanReplyRequest) -> dict:
    """Reply to a pending plan-approval request.

    ``decision`` must be ``"approved"`` or ``"rejected"``.

    - ``"approved"`` — unblocks the agent; it will execute the recorded steps.
    - ``"rejected"`` — unblocks the agent; it will abandon the plan.
    """
    from app.agent.plan import get_service_for_session

    valid = {"approved", "rejected"}
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
        _cast(Literal["approved", "rejected"], body.decision),  # type: ignore[arg-type]
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
