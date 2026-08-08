"""Team communication tools — LLM-callable tools for agent-team messaging.

One tool for everyone: team_message(to, content)

Injected into agent.run() at runtime via injected_tools.  For structured
deliverables, see ``handoff.py`` which provides ``team_handoff``.
Lead and members share the same underlying function but get role-specific
descriptions so the LLM understands the intended usage for each role.

Recipient resolution:
- Exact instance handle (``executor#1``) routes directly.
- Bare blueprint name (``executor``) routes to the unique live instance
  if exactly one exists.  Ambiguous (multiple live instances) and unknown
  (no live instance) cases produce a tailored error so the lead/member can
  pick a specific handle.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from app.agent.tools.registry import Tool
from app.uuid7 import uuid7

if TYPE_CHECKING:
    from app.agent.mode.team.mailbox import TeamMailbox
    from app.agent.mode.team.team import AgentTeam


_LEAD_DESCRIPTION = (
    "Send a quick coordination message to one or more live members. Use for "
    "questions, answers, context corrections, and status queries. Do not assign "
    "substantial work here; use team_delegate so the assignment is durable and "
    "has an explicit completion contract."
)

_MEMBER_DESCRIPTION = (
    "Send a quick message to a teammate — use for questions, clarifications, "
    "status queries, and short coordination. For delivering substantial work "
    "output (findings, analysis, completed tasks), use team_handoff instead."
)


def make_team_message_tool(
    mailbox: "TeamMailbox",
    agent_name: str,
    role: Literal["lead", "member"] = "member",
    team: "AgentTeam | None" = None,
) -> Tool:
    """Return the team_message tool bound to *agent_name* with role-specific description.

    When ``team`` is supplied, recipient resolution understands instance
    handles (``executor#1``) and bare-blueprint-name shorthand (``executor``,
    routed to the unique live instance).  Without it the tool falls back to
    raw mailbox name lookup — used by older tests that build a mailbox by
    hand.
    """

    async def team_message(
        to: Annotated[
            list[str],
            Field(
                description=(
                    "Recipient names — exact instance handles "
                    "(e.g. 'executor#1') or the bare blueprint name "
                    "('executor') when only one instance is live. "
                    "One call per intended audience: if you need to say "
                    "different things to different people, make separate "
                    'calls. Example: ["explorer#1"], ["writer", "analyst#2"]'
                )
            ),
        ],
        content: Annotated[
            str,
            Field(
                description=(
                    "The message body. Must be addressed ONLY to recipients in `to`. "
                    "Use concise questions, answers, corrections, or status information. "
                    "Do not place a new substantial task or final deliverable here. "
                    "Do NOT prefix with your name — the system adds [your-name]: automatically."
                )
            ),
        ],
        intent: Annotated[
            Literal["coordination", "question", "answer", "context", "status"],
            Field(
                description=(
                    "Message intent. Use 'question' when a reply is required and "
                    "'answer' with reply_to when answering a specific message."
                )
            ),
        ] = "coordination",
        reply_to: Annotated[
            str | None,
            Field(description="Message ID being answered, when intent='answer'."),
        ] = None,
    ) -> str:
        """Send a message to one or more teammates."""
        from app.agent.mode.team.mailbox import Message

        # Drop self — agents cannot message themselves
        requested = [r for r in to if r != agent_name]
        if not requested:
            return "No valid recipients (cannot message yourself)."
        if not content.strip():
            return "Error: content cannot be empty."
        if intent == "answer" and not reply_to:
            return "Error: reply_to is required when intent='answer'."

        # Resolve each requested name through the team's recipient
        # resolver (handles bare-blueprint-name shorthand) when available.
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

        # Strip self-prefix in both "[name]: " and "name: " forms (prevents double-prefix)
        stripped = re.sub(r"^\[?" + re.escape(agent_name) + r"\]?:\s*", "", content)
        message_ids: list[str] = []
        for recipient in resolved:
            message_id = str(uuid7())
            marker = ""
            if intent != "coordination":
                marker = f"[{intent} id={message_id}"
                if reply_to:
                    marker += f" reply_to={reply_to}"
                marker += "] "
            formatted = f"[{agent_name}]: {marker}{stripped}"
            msg = Message(
                id=message_id,
                from_agent=agent_name,
                to_agent=recipient,
                content=formatted,
                extra={
                    "kind": "team_message",
                    "intent": intent,
                    **({"reply_to": reply_to} if reply_to else {}),
                },
            )
            await mailbox.send(to=recipient, message=msg)
            message_ids.append(message_id)

        return (
            f"Message sent to {', '.join(resolved)}. "
            f"Message IDs: {', '.join(message_ids)}."
        )

    description = _LEAD_DESCRIPTION if role == "lead" else _MEMBER_DESCRIPTION
    return Tool(team_message, name="team_message", description=description)


def _resolve(
    team: "AgentTeam | None",
    mailbox: "TeamMailbox",
    name: str,
    sender: str,
) -> str | None:
    """Resolve a requested recipient name to a live mailbox key, or ``None``."""
    if team is not None:
        target = team.resolve_recipient(name)
        if target is not None and target != sender:
            return target
        if target == sender:
            return None
        # Fall through to mailbox-based check so the caller can produce a
        # tailored ambiguity / unknown error message via ``_recipient_error``.
        return None
    # No team context — fall back to raw mailbox lookup.
    if name in mailbox.registered_agents and name != sender:
        return name
    return None


def _recipient_error(
    team: "AgentTeam | None",
    mailbox: "TeamMailbox",
    name: str,
    sender: str,
) -> str:
    """Produce a helpful error string for a failed recipient resolution."""
    if team is None:
        available = [a for a in mailbox.registered_agents if a != sender]
        return f"Agent '{name}' not found. Available: {', '.join(available)}"

    # Workflow agent node in flight: the node's roster is the law.
    if team.turn_allowed_blueprints is not None:
        from app.agent.mode.team.team import parse_instance_handle

        parsed = parse_instance_handle(name)
        blueprint = parsed[0] if parsed is not None else name
        if not team.blueprint_allowed_this_turn(blueprint):
            allowed = sorted(team.turn_allowed_blueprints)
            return (
                f"'{name}' is not on this workflow node's roster. "
                f"Allowed this turn: {allowed or ['(lead only)']}."
            )

    # Bare blueprint name? Surface ambiguity vs. not-spawned distinctly.
    if name in team.blueprints:
        live = team.live_instances_for_blueprint(name)
        if not live:
            return (
                f"Blueprint '{name}' has no live instances — "
                f"call team_manage(action='spawn', members=['{name}']) first."
            )
        return (
            f"Blueprint '{name}' has multiple live instances {live}. "
            f"Address one explicitly (e.g. team_message(to=['{live[0]}']))."
        )
    available = [a for a in mailbox.registered_agents if a != sender]
    blueprints = sorted(team.blueprints.keys())
    return (
        f"Agent '{name}' not found. "
        f"Live: {available}. Spawnable blueprints: {blueprints}."
    )
