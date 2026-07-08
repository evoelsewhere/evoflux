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
        from app.agent.mode.team.mailbox import Message
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

        # Build feedback
        feedback = RejectionFeedback(
            reason=reason,
            issues=list(issues),
            suggestions=list(suggestions),
            severity=severity,
        )
        feedback_json = feedback.model_dump(mode="json")

        # Format human-readable rejection message
        severity_icon = {
            "minor": "⚠️",
            "major": "❌",
            "redo": "🚫",
        }[severity]

        severity_label = {
            "minor": "MINOR FIXES NEEDED",
            "major": "REJECTED — REWORK NEEDED",
            "redo": "REJECTED — REDO FROM SCRATCH",
        }[severity]

        formatted_lines = [
            f"[{agent_name}] {severity_icon} {severity_label}:",
            f"**Reason:** {reason}",
        ]
        if issues:
            formatted_lines.append("**Issues found:**")
            for issue in issues:
                formatted_lines.append(f"  ✗ {issue}")
        if suggestions:
            formatted_lines.append("**Suggestions:**")
            for suggestion in suggestions:
                formatted_lines.append(f"  → {suggestion}")
        formatted_lines.append("")
        formatted_lines.append(
            "Fix the issues above and re-deliver via `team_handoff`. "
            "Your original delegation constraints still apply."
        )

        formatted = "\n".join(formatted_lines)

        # Emit SSE rejection event for the UI
        _emit_rejection_event(team, agent_name, resolved, feedback_json)

        # A rejection is a re-delegation: agent_name is awaiting an improved
        # team_handoff from each recipient before its answer can be final.
        if team is not None:
            team.register_delegation(agent_name, resolved)

        for recipient in resolved:
            msg = Message(
                from_agent=agent_name,
                to_agent=recipient,
                content=formatted,
            )
            # Stash structured feedback for DB persistence / frontend rendering
            msg.__dict__["_rejection_feedback"] = feedback_json
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
