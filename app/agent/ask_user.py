"""Ask-user — let an agent pause mid-task and ask the human one or more
questions in a single batch.

Context-var + session registry pattern mirrors :mod:`app.agent.plan`: the
``ask_user`` tool calls :meth:`AskUserService.ask`, which pushes a
``question_asked`` SSE event carrying every question at once and blocks on
a future until the user answers all of them, then resolves with one answer
per question (in order).
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.tools.builtin.ask_user import QuestionSpec


@dataclass
class AskUserRequest:
    """A pending batch of questions awaiting user replies."""

    id: str
    session_id: str
    questions: list["QuestionSpec"]
    _future: asyncio.Future | None = field(default=None, compare=False, repr=False)

    @classmethod
    def create(
        cls,
        session_id: str,
        questions: list["QuestionSpec"],
        *,
        request_id: str | None = None,
    ) -> "AskUserRequest":
        req = cls(
            id=request_id or str(uuid.uuid4()),
            session_id=session_id,
            questions=list(questions),
        )
        req._future = asyncio.get_running_loop().create_future()
        return req


# Global registry keyed by session_id — allows the HTTP reply endpoint to
# locate the right service without sharing a context var.
_active_services: dict[str, "AskUserService"] = {}


class AskUserService:
    """Per-session question tracker.

    Lifecycle::

        answers = await svc.ask(questions)  # called by the ask_user tool
        # blocks until svc.reply(request_id, answers) is called from HTTP
    """

    def __init__(
        self, session_id: str, *, stream_session_id: str | None = None
    ) -> None:
        self.session_id = session_id
        # SSE events publish to the lead's stream (may differ from a
        # member's own session_id when called from a member agent).
        self.stream_session_id = stream_session_id or session_id
        self._pending: dict[str, AskUserRequest] = {}

    async def ask(
        self,
        questions: list["QuestionSpec"],
        *,
        request_id: str | None = None,
    ) -> list[str]:
        """Push a batch of questions to the user and block until answered.

        Returns one answer per question, in the same order — each either
        an option the user picked or free text they typed.
        """
        req = AskUserRequest.create(self.session_id, questions, request_id=request_id)
        self._pending[req.id] = req

        try:
            from app.agent.schemas.events import QuestionAskedEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(
                self.stream_session_id,
                StreamEnvelope.from_event(
                    QuestionAskedEvent(
                        request_id=req.id,
                        session_id=self.session_id,
                        questions=[
                            {
                                "question": q.question,
                                "options": q.options,
                                **(
                                    {"browser_handoff": q.browser_handoff.model_dump()}
                                    if q.browser_handoff is not None
                                    else {}
                                ),
                            }
                            for q in questions
                        ],
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            from loguru import logger

            logger.warning("ask_user_sse_push_failed error={}", exc)

        assert req._future is not None
        try:
            answers: list[str] = await req._future
        except asyncio.CancelledError:
            # Agent was interrupted while waiting — clean up and re-raise.
            self._pending.pop(req.id, None)
            raise
        self._pending.pop(req.id, None)
        return answers

    def get_pending(self, request_id: str) -> AskUserRequest | None:
        """The pending request for *request_id*, or ``None`` if unknown /
        already resolved — lets the reply endpoint validate answers against
        the questions before resolving."""
        return self._pending.get(request_id)

    def validate_answers(self, request_id: str, answers: list[str]) -> str | None:
        """Check *answers* against a pending batch: one answer per question,
        and any ``strict`` question's answer must be one of its options.

        Returns an error message when invalid, or ``None`` when the answers
        are acceptable. A gate whose answer doesn't match a declared choice
        would otherwise route no edge and silently strand the run.
        """
        req = self._pending.get(request_id)
        if req is None or req._future is None or req._future.done():
            return None  # let reply() report the not-found/resolved case
        if len(answers) != len(req.questions):
            return f"expected {len(req.questions)} answer(s), got {len(answers)}."
        for question, answer in zip(req.questions, answers):
            if question.strict and answer not in question.options:
                return (
                    f"answer {answer!r} is not one of the allowed choices "
                    f"{question.options}."
                )
        return None

    def reply(self, request_id: str, answers: list[str]) -> bool:
        """Resolve a pending question batch.  Called by the API reply endpoint.

        Returns ``True`` if the request was found and resolved, ``False``
        if not found or already resolved.
        """
        req = self._pending.get(request_id)
        if req is None or req._future is None or req._future.done():
            return False
        req._future.set_result(answers)
        return True


# ── Context-var integration ───────────────────────────────────────────────────

_ask_user_ctx: contextvars.ContextVar[AskUserService] = contextvars.ContextVar(
    "ask_user_ctx"
)
_default_service: AskUserService | None = None


def get_ask_user_service() -> AskUserService:
    """Return the active ``AskUserService`` for the current context.

    Falls back to a module-level default (standalone tool invocations, tests).
    """
    global _default_service
    try:
        return _ask_user_ctx.get()
    except LookupError:
        if _default_service is None:
            _default_service = AskUserService(session_id="default")
        return _default_service


def set_ask_user_service(service: AskUserService) -> contextvars.Token:
    """Scope *service* to the current async context and register globally."""
    _active_services[service.session_id] = service
    return _ask_user_ctx.set(service)


def reset_ask_user_service(token: contextvars.Token, session_id: str) -> None:
    """Restore the previous context and unregister from the global registry."""
    _active_services.pop(session_id, None)
    _ask_user_ctx.reset(token)


def get_service_for_session(session_id: str) -> AskUserService | None:
    """Look up an active service by session_id (for the HTTP reply endpoint)."""
    return _active_services.get(session_id)


def get_services_for_stream(stream_session_id: str) -> list[AskUserService]:
    """Live AskUser services publishing to one lead/session stream.

    A member can ask a question while publishing it on its parent lead stream.
    Browser handoff surfaces need this reverse lookup to recover requests after
    reconnect without exposing requests from another session.
    """
    return [
        service
        for service in _active_services.values()
        if service.stream_session_id == stream_session_id
    ]
