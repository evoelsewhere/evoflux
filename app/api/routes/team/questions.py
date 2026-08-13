"""Ask-user question reply endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.api.schemas.team import AskUserReplyRequest

router = APIRouter()


@router.get("/{session_id}/questions/pending", status_code=200)
async def pending_questions(session_id: str) -> dict:
    """Pending ``ask_user`` batches for a session.

    *session_id* is the stream (lead) session — pending requests from every
    team member publishing to that stream are included (parity with
    ``GET /permissions`` and the webbridge side-panel restore path).

    Live-state only, like the service itself. Forge/Coding also rediscover
    pending questions via SSE reconnect replay of ``question_asked``.
    """
    from app.agent.ask_user import get_services_for_stream

    return {
        "questions": [
            {
                "request_id": request_id,
                "session_id": service.session_id,
                "items": [
                    {
                        "question": q.question,
                        "options": q.options,
                        "strict": q.strict,
                        "kind": q.kind,
                        **(
                            {"agent_spawn": q.agent_spawn.model_dump()}
                            if q.agent_spawn is not None
                            else {}
                        ),
                    }
                    for q in request.questions
                ],
            }
            for service in get_services_for_stream(session_id)
            for request_id, request in service._pending.items()
        ]
    }


@router.post("/{session_id}/questions/{request_id}/reply", status_code=200)
async def reply_question(
    session_id: str,
    request_id: str,
    body: AskUserReplyRequest,
) -> dict:
    """Reply to a pending ``ask_user`` question batch, unblocking the agent.

    *session_id* may be either the owning agent session or the lead stream
    session (gate banner posts the lead id). The service publishes the
    ``question_replied`` SSE event that closes the question UI on every
    connected client.
    """
    from app.agent.ask_user import get_services_for_stream

    services = get_services_for_stream(session_id)
    if not services:
        raise HTTPException(
            status_code=404,
            detail=f"No active question for session '{session_id}'.",
        )

    # Prefer the service that still owns this request_id so validation and
    # reply land on the same instance (member vs lead).
    owner = next(
        (svc for svc in services if svc.get_pending(request_id) is not None),
        None,
    )
    if owner is None:
        raise HTTPException(
            status_code=404,
            detail=f"Question '{request_id}' not found or already resolved.",
        )

    validation_error = owner.validate_answers(request_id, body.answers)
    if validation_error is not None:
        raise HTTPException(status_code=422, detail=validation_error)

    resolved = owner.reply(request_id, body.answers)
    if not resolved:
        raise HTTPException(
            status_code=404,
            detail=f"Question '{request_id}' not found or already resolved.",
        )

    logger.info("question_replied session_id={} request_id={}", session_id, request_id)
    return {"status": "ok", "request_id": request_id, "answers": body.answers}
