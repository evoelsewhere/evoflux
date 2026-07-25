"""Structured rejection tool — typed feedback loop from lead to members.

``team_reject`` closes the quality feedback loop opened by ``team_delegate``.
When a member's handoff doesn't meet the expected output or violates
constraints, the lead uses ``team_reject`` to send structured feedback that
re-activates the member with clear reasons and suggestions for improvement.

This implements the Writer→Critic pattern: delegate → handoff → reject (if
needed) → improved handoff → accept.  The structured format ensures the
member understands exactly what was wrong and what to fix, reducing
back-and-forth iterations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import Tool

if TYPE_CHECKING:
    from app.agent.mode.team.mailbox import TeamMailbox
    from app.agent.mode.team.team import AgentTeam


# ── Rejection schema ─────────────────────────────────────────────────────────


class RejectionFeedback(BaseModel):
    """Structured rejection feedback for a handoff that didn't meet criteria.

    Provides actionable guidance so the member can improve without guessing
    what was wrong.
    """

    task_id: str | None = Field(
        default=None,
        description="Delegation task UUID being reopened.",
    )
    reason: str = Field(
        description=(
            "Why the handoff was rejected — what specific criteria it failed "
            "to meet or what was wrong with the output."
        ),
    )
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems found — one per entry.",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete suggestions for improvement — what to fix, add, "
            "or redo. Be actionable, not vague."
        ),
    )
    severity: Literal["minor", "major", "redo"] = Field(
        default="major",
        description=(
            "'minor' = small fixes needed, keep most of the work; "
            "'major' = significant gaps, rework portions; "
            "'redo' = fundamentally wrong approach, start over."
        ),
    )


# ── Tool description ─────────────────────────────────────────────────────────

_REJECT_DESCRIPTION = (
    "Reject a member's handoff with structured feedback when it doesn't meet "
    "the expected output or violates constraints. The member will be "
    "re-activated with clear reasons, specific issues, and suggestions for "
    "improvement. Use this instead of sending a vague 'try again' via "
    "team_message — structured rejection gets better results faster."
)


def format_rejection_message(
    agent_name: str,
    task_id: str,
    feedback_data: RejectionFeedback | dict,
    *,
    attempt: int,
) -> str:
    feedback = (
        feedback_data
        if isinstance(feedback_data, RejectionFeedback)
        else RejectionFeedback.model_validate(feedback_data)
    )
    severity_icon = {"minor": "⚠️", "major": "❌", "redo": "🚫"}[feedback.severity]
    severity_label = {
        "minor": "MINOR FIXES NEEDED",
        "major": "REJECTED — REWORK NEEDED",
        "redo": "REJECTED — REDO FROM SCRATCH",
    }[feedback.severity]
    lines = [
        f"[{agent_name}] {severity_icon} {severity_label}:",
        f"**Task ID:** {task_id}",
        f"**Attempt:** {attempt}",
        f"**Reason:** {feedback.reason}",
    ]
    if feedback.issues:
        lines.append("**Issues found:**")
        lines.extend(f"  ✗ {issue}" for issue in feedback.issues)
    if feedback.suggestions:
        lines.append("**Suggestions:**")
        lines.extend(f"  → {suggestion}" for suggestion in feedback.suggestions)
    lines.extend(
        [
            "",
            "Fix the issues above and re-deliver via `team_handoff` using "
            "the same Task ID. The original delegation constraints still apply.",
        ]
    )
    return "\n".join(lines)


# ── Tool factory ─────────────────────────────────────────────────────────────


def make_team_reject_tool(
    mailbox: "TeamMailbox",
    agent_name: str,
    team: "AgentTeam | None" = None,
) -> Tool:
    """Return the ``team_reject`` tool bound to *agent_name*. Lead-only."""

    async def team_reject(
        to: Annotated[
            list[str],
            Field(
                description=(
                    "The member handle(s) whose handoff is being rejected "
                    "(e.g. 'executor#1')."
                ),
            ),
        ],
        reason: Annotated[
            str,
            Field(
                description=(
                    "Why the handoff was rejected — what criteria it failed "
                    "or what's wrong. Be specific: 'missing error handling for "
                    "network timeouts' not 'incomplete'."
                ),
            ),
        ],
        task_id: Annotated[
            str | None,
            Field(
                description=(
                    "Completed delegation task UUID to reopen. May be omitted "
                    "only when exactly one completed task matches the member."
                )
            ),
        ] = None,
        issues: Annotated[
            list[str],
            Field(
                description=(
                    "Specific problems found — one per entry. "
                    "E.g. ['no tests added', 'hardcoded API key on line 42', "
                    "'confidence too low without evidence']."
                ),
            ),
        ] = [],  # noqa: B006
        suggestions: Annotated[
            list[str],
            Field(
                description=(
                    "Concrete suggestions for improvement. "
                    "E.g. ['add pytest tests for the retry path', "
                    "'use environment variable for the API key', "
                    "'search 3 more sources to raise confidence']."
                ),
            ),
        ] = [],  # noqa: B006
        severity: Annotated[
            Literal["minor", "major", "redo"],
            Field(
                description=(
                    "'minor' = small fixes, keep most work; "
                    "'major' = significant gaps, rework portions; "
                    "'redo' = wrong approach, start over."
                ),
            ),
        ] = "major",
    ) -> str:
        """Reject a handoff with structured feedback for improvement."""
        from app.agent.mode.team.tools import _recipient_error, _resolve

        if not reason.strip():
            return "Error: reason cannot be empty — explain what was wrong."

        # Resolve recipients
        requested = [r for r in to if r != agent_name]
        if not requested:
            return "No valid recipients (cannot reject yourself)."

        resolved: list[str] = []
        errors: list[str] = []
        for name in requested:
            target = _resolve(team, mailbox, name, agent_name)
            if target is None:
                errors.append(_recipient_error(team, mailbox, name, agent_name))
            else:
                resolved.append(target)

        if errors:
            return " | ".join(errors)
        if task_id is not None and len(resolved) != 1:
            return "Error: a task-linked rejection must have exactly one recipient."

        # Build feedback
        feedback = RejectionFeedback(
            task_id=task_id,
            reason=reason,
            issues=list(issues),
            suggestions=list(suggestions),
            severity=severity,
        )
        feedback_json = feedback.model_dump(mode="json", exclude_none=True)

        reopened = []
        if team is not None:
            try:
                for recipient in resolved:
                    reopened_task = await team.reopen_delegation(
                        task_id=task_id,
                        delegator=agent_name,
                        recipient=recipient,
                        feedback=feedback_json,
                    )
                    reopened.append(reopened_task)
            except (TypeError, ValueError) as exc:
                return f"Error: {exc}"
            if len(reopened) == 1:
                task_id = str(reopened[0].id)
                feedback.task_id = task_id
                feedback_json = feedback.model_dump(mode="json", exclude_none=True)

        # Emit SSE rejection event for the UI
        _emit_rejection_event(team, agent_name, resolved, feedback_json)

        if team is not None:
            await team.dispatch_delegation_tasks(reopened)
        else:
            from app.agent.mode.team.mailbox import Message

            for recipient in resolved:
                untracked_id = task_id or "untracked"
                msg = Message(
                    from_agent=agent_name,
                    to_agent=recipient,
                    content=format_rejection_message(
                        agent_name,
                        untracked_id,
                        feedback,
                        attempt=1,
                    ),
                    extra={
                        "kind": "rejection",
                        "task_id": task_id,
                        "_rejection_feedback": feedback_json,
                    },
                )
                await mailbox.send(to=recipient, message=msg)

        return f"Rejection sent to {', '.join(resolved)} (severity: {severity})."

    return Tool(team_reject, name="team_reject", description=_REJECT_DESCRIPTION)


# ── SSE event emission ───────────────────────────────────────────────────────


def _emit_rejection_event(
    team: "AgentTeam | None",
    from_agent: str,
    to_agents: list[str],
    feedback: dict,
) -> None:
    """Push a ``rejection`` SSE event to the stream store (fire-and-forget)."""
    if team is None:
        return
    try:
        import asyncio

        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        lead_session = team.lead.session_id
        env = StreamEnvelope.from_parts(
            "rejection",
            {
                "type": "rejection",
                "from_agent": from_agent,
                "to_agents": to_agents,
                "feedback": feedback,
            },
        )
        asyncio.create_task(stream_store.push_event(lead_session, env))
    except Exception:
        logger.debug("rejection_event_emit_skipped agent={}", from_agent)
