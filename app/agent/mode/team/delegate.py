"""Structured task delegation tool — typed task assignments from lead to members.

``team_delegate`` is the structured counterpart to ``team_message`` for task
assignment.  While ``team_message`` is free-form text, ``team_delegate``
enforces a typed task specification with explicit goal, constraints, expected
output, and context — giving the receiving agent a clear contract of what
"done" looks like.

The task spec is persisted in the DB message ``extra`` field and surfaced via
a dedicated ``delegation`` SSE event, enabling richer UI rendering (task cards
with acceptance criteria) than plain text instructions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import Tool

if TYPE_CHECKING:
    from app.agent.mode.team.mailbox import TeamMailbox
    from app.agent.mode.team.team import AgentTeam


# ── Task specification schema ────────────────────────────────────────────────


class TaskSpec(BaseModel):
    """Structured task specification for delegation.

    Defines what the receiving agent must accomplish with explicit acceptance
    criteria, reducing ambiguity and improving output quality.
    """

    goal: str = Field(
        description="Clear, actionable description of what must be accomplished.",
    )
    expected_output: str = Field(
        description=(
            "What 'done' looks like — the format, content, and quality bar "
            "the deliverable must meet. Be specific: 'a list of 5 URLs with "
            "summaries' not 'research results'."
        ),
    )
    constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Boundaries the agent must respect — e.g. 'only use Python 3.14 "
            "features', 'do not modify tests/', 'max 500 words'."
        ),
    )
    context: str | None = Field(
        default=None,
        description=(
            "Relevant background the agent needs to start — prior findings, "
            "file paths, URLs, decisions already made. Include what the agent "
            "would otherwise have to ask or search for."
        ),
    )
    priority: Literal["low", "normal", "high", "critical"] = Field(
        default="normal",
        description="Task priority — guides agent urgency and thoroughness.",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description=(
            "Task IDs or agent handles this task depends on. The agent should "
            "wait for these before starting if they haven't delivered yet."
        ),
    )


# ── Tool description ─────────────────────────────────────────────────────────

_DELEGATE_DESCRIPTION = (
    "Delegate a structured task to one or more team members with explicit "
    "goal, expected output, and constraints. Use this instead of team_message "
    "when assigning substantial work — it gives the member a clear contract "
    "of what 'done' looks like, reducing back-and-forth and improving output "
    "quality. For quick questions or coordination, use team_message instead."
)


# ── Tool factory ─────────────────────────────────────────────────────────────


def make_team_delegate_tool(
    mailbox: "TeamMailbox",
    agent_name: str,
    team: "AgentTeam | None" = None,
) -> Tool:
    """Return the ``team_delegate`` tool bound to *agent_name*. Lead-only."""

    async def team_delegate(
        to: Annotated[
            list[str],
            Field(
                description=(
                    "Recipient handles — exact instance handles "
                    "(e.g. 'executor#1') or bare blueprint name "
                    "when only one instance is live."
                ),
            ),
        ],
        goal: Annotated[
            str,
            Field(
                description=(
                    "Clear, actionable description of what the member must "
                    "accomplish. Be specific — 'implement retry logic in "
                    "agent_service.py with exponential backoff' not 'fix retries'."
                ),
            ),
        ],
        expected_output: Annotated[
            str,
            Field(
                description=(
                    "What 'done' looks like — the format, content, and quality "
                    "bar the deliverable must meet. E.g. 'a team_handoff with "
                    "findings listing 5+ relevant papers, each with URL and "
                    "one-line summary, confidence >= 0.7'."
                ),
            ),
        ],
        constraints: Annotated[
            list[str],
            Field(
                description=(
                    "Boundaries — e.g. 'only Python 3.14 features', "
                    "'do not modify tests/', 'max 500 words', "
                    "'must run ruff check before handoff'."
                ),
            ),
        ] = [],  # noqa: B006
        context: Annotated[
            str | None,
            Field(
                description=(
                    "Background the agent needs — prior findings, file paths, "
                    "URLs, decisions already made. Saves the agent from asking."
                ),
            ),
        ] = None,
        priority: Annotated[
            Literal["low", "normal", "high", "critical"],
            Field(description="Task priority — guides urgency and thoroughness."),
        ] = "normal",
        depends_on: Annotated[
            list[str],
            Field(
                description=(
                    "Task IDs or agent handles this depends on. "
                    "Agent should wait for these before starting."
                ),
            ),
        ] = [],  # noqa: B006
    ) -> str:
        """Delegate a structured task with explicit acceptance criteria."""
        from app.agent.mode.team.mailbox import Message
        from app.agent.mode.team.tools import _recipient_error, _resolve

        if not goal.strip():
            return "Error: goal cannot be empty."
        if not expected_output.strip():
            return "Error: expected_output cannot be empty — define what 'done' looks like."

        # Resolve recipients
        requested = [r for r in to if r != agent_name]
        if not requested:
            return "No valid recipients (cannot delegate to yourself)."

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

        # Build task spec
        spec = TaskSpec(
            goal=goal,
            expected_output=expected_output,
            constraints=list(constraints),
            context=context,
            priority=priority,
            depends_on=list(depends_on),
        )
        spec_json = spec.model_dump(mode="json", exclude_none=True)

        # Format human-readable message for the agent's inbox
        priority_icon = {
            "low": "○",
            "normal": "●",
            "high": "◉",
            "critical": "🔴",
        }[priority]

        formatted_lines = [
            f"[{agent_name}] {priority_icon} TASK DELEGATION:",
            f"**Goal:** {goal}",
            f"**Expected output:** {expected_output}",
        ]
        if constraints:
            formatted_lines.append("**Constraints:**")
            for c in constraints:
                formatted_lines.append(f"  • {c}")
        if context:
            formatted_lines.append(f"**Context:** {context}")
        if depends_on:
            formatted_lines.append(f"**Depends on:** {', '.join(depends_on)}")

        formatted = "\n".join(formatted_lines)

        # Emit SSE delegation event for the UI
        _emit_delegation_event(team, agent_name, resolved, spec_json)

        for recipient in resolved:
            msg = Message(
                from_agent=agent_name,
                to_agent=recipient,
                content=formatted,
            )
            # Stash structured task spec for DB persistence / frontend rendering
            msg.__dict__["_task_spec"] = spec_json
            await mailbox.send(to=recipient, message=msg)

        return f"Task delegated to {', '.join(resolved)}."

    return Tool(team_delegate, name="team_delegate", description=_DELEGATE_DESCRIPTION)


# ── SSE event emission ───────────────────────────────────────────────────────


def _emit_delegation_event(
    team: "AgentTeam | None",
    from_agent: str,
    to_agents: list[str],
    spec: dict,
) -> None:
    """Push a ``delegation`` SSE event to the stream store (fire-and-forget)."""
    if team is None:
        return
    try:
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        stream_key = str(team.lead_session_id)
        envelope = StreamEnvelope.from_parts(
            event="delegation",
            data={
                "from": from_agent,
                "to": to_agents,
                "spec": spec,
            },
        )
        stream_store.push(stream_key, envelope)
    except Exception as exc:
        logger.debug("delegation_event_emit_failed error={}", exc)
