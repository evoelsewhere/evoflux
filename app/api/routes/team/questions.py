"""Ask-user question reply endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.api.schemas.team import AskUserReplyRequest

router = APIRouter()


@router.post("/{session_id}/questions/{request_id}/reply", status_code=200)
async def reply_question(
    session_id: str,
    request_id: str,
    body: AskUserReplyRequest,
) -> dict:
    """Reply to a pending ``ask_user`` question batch, unblocking the agent."""
    from app.agent.ask_user import get_service_for_session

    svc = get_service_for_session(session_id)
    if svc is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active question for session '{session_id}'.",
        )

    resolved = svc.reply(request_id, body.answers)
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"Question '{request_id}' not found or already resolved.",
        )

    logger.info(
        "question_replied session_id={} request_id={}", session_id, request_id
    )
    return {"status": "ok", "request_id": request_id, "answers": body.answers}
