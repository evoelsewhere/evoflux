"""Plan Mode — intercept destructive tools for batch user review before execution.

When plan mode is active (``PlanModeService.active``), :mod:`tool_executor`
records tool calls instead of running them.  ``exit_plan_mode`` collects
the steps, pushes a ``plan_approval_requested`` SSE event to the session
stream, and blocks until the user approves or rejects.

Context-var pattern mirrors :mod:`app.agent.permission`.
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

PlanDecision = Literal["approved", "rejected"]


@dataclass
class PlanStep:
    """One recorded step in a plan."""

    tool_name: str
    args: dict[str, Any]
    summary: str  # one-line human-readable description shown in the approval UI


@dataclass
class PlanApprovalRequest:
    """Pending plan-approval awaiting a user reply."""

    id: str
    session_id: str
    steps: list[PlanStep]
    _future: asyncio.Future | None = field(default=None, compare=False, repr=False)

    @classmethod
    def create(cls, session_id: str, steps: list[PlanStep]) -> "PlanApprovalRequest":
        req = cls(id=str(uuid.uuid4()), session_id=session_id, steps=list(steps))
        req._future = asyncio.get_running_loop().create_future()
        return req


# Global registry keyed by session_id — allows the HTTP reply endpoint to
# locate the right service without sharing a context var.
_active_services: dict[str, "PlanModeService"] = {}


class PlanModeService:
    """Per-session plan mode tracker.

    Lifecycle::

        svc.enter()                      # called by enter_plan_mode tool
        svc.record_step(name, args, s)   # called by tool_executor intercept
        decision = await svc.request_approval()  # called by exit_plan_mode tool
        # blocks until svc.reply(request_id, decision) is called from HTTP
    """

    def __init__(
        self,
        session_id: str,
        *,
        stream_session_id: str | None = None,
    ) -> None:
        self.session_id = session_id
        # SSE events are published to the lead's stream (may differ from
        # the member's own session_id when called from a member agent).
        self.stream_session_id = stream_session_id or session_id
        self._active = False
        self._steps: list[PlanStep] = []
        self._pending: dict[str, PlanApprovalRequest] = {}

    @property
    def active(self) -> bool:
        return self._active

    @property
    def step_count(self) -> int:
        return len(self._steps)

    def enter(self) -> None:
        """Start recording steps.  Clears any previous steps."""
        self._active = True
        self._steps = []

    def record_step(self, tool_name: str, args: dict[str, Any], summary: str) -> str:
        """Record a step and return a status string for the agent."""
        step = PlanStep(tool_name=tool_name, args=args, summary=summary)
        self._steps.append(step)
        idx = len(self._steps)
        return f"[PLAN] Step {idx} recorded: {tool_name} — {summary}"

    async def request_approval(self) -> PlanDecision:
        """Exit plan mode, push SSE event, and block until user replies.

        Returns ``"approved"`` or ``"rejected"``.  If there are no recorded
        steps, returns ``"approved"`` immediately without prompting.
        """
        self._active = False
        steps = list(self._steps)
        self._steps = []

        if not steps:
            return "approved"

        req = PlanApprovalRequest.create(self.session_id, steps)
        self._pending[req.id] = req

        try:
            from app.agent.schemas.events import PlanApprovalRequestedEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(
                self.stream_session_id,
                StreamEnvelope.from_event(
                    PlanApprovalRequestedEvent(
                        request_id=req.id,
                        session_id=self.session_id,
                        steps=[
                            {"tool": s.tool_name, "args": s.args, "summary": s.summary}
                            for s in steps
                        ],
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            from loguru import logger

            logger.warning("plan_approval_sse_push_failed error={}", exc)

        assert req._future is not None
        try:
            result: PlanDecision = await req._future
        except asyncio.CancelledError:
            # Agent was interrupted while waiting — clean up and re-raise.
            self._pending.pop(req.id, None)
            raise
        self._pending.pop(req.id, None)
        return result

    def reply(self, request_id: str, decision: PlanDecision) -> bool:
        """Resolve a pending approval.  Called by the API reply endpoint.

        Returns ``True`` if the request was found and resolved, ``False``
        if not found or already resolved.
        """
        req = self._pending.get(request_id)
        if req is None or req._future is None or req._future.done():
            return False
        req._future.set_result(decision)
        return True


# ── Context-var integration ───────────────────────────────────────────────────

_plan_ctx: contextvars.ContextVar[PlanModeService] = contextvars.ContextVar("plan_ctx")
_default_service: PlanModeService | None = None


def get_plan_mode_service() -> PlanModeService:
    """Return the active ``PlanModeService`` for the current context.

    Falls back to a module-level no-op service when no context is set
    (standalone tool invocations, tests).
    """
    global _default_service
    try:
        return _plan_ctx.get()
    except LookupError:
        if _default_service is None:
            _default_service = PlanModeService(session_id="default")
        return _default_service


def set_plan_mode_service(service: PlanModeService) -> contextvars.Token:
    """Scope *service* to the current async context and register globally."""
    _active_services[service.session_id] = service
    return _plan_ctx.set(service)


def reset_plan_mode_service(token: contextvars.Token, session_id: str) -> None:
    """Restore the previous context and unregister from the global registry."""
    _active_services.pop(session_id, None)
    _plan_ctx.reset(token)


def get_service_for_session(session_id: str) -> PlanModeService | None:
    """Look up an active service by session_id (for the HTTP reply endpoint)."""
    return _active_services.get(session_id)
