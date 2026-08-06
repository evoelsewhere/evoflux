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

from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

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
            "Delegation task UUIDs this task depends on. The runtime keeps the "
            "task blocked until all dependencies complete."
        ),
    )
    deadline_at: datetime | None = Field(
        default=None,
        description="Optional timezone-aware deadline for this task.",
    )
    dependency_results: list[dict] = Field(
        default_factory=list,
        description="Runtime-injected final results from prerequisite tasks.",
    )
    target_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Workspace-relative files or directories this task may modify. "
            "Exclusive claims prevent overlapping parallel assignments."
        ),
    )
    exclusive_paths: bool = Field(
        default=True,
        description="Whether target_paths are exclusive while the task is open.",
    )
    isolation: Literal["auto", "shared", "worktree"] = Field(
        default="auto",
        description=(
            "Lead-selected workspace isolation. Auto uses a worktree for mutable "
            "coding tasks and shared workspace for read-only coordination."
        ),
    )
    resolved_isolation: Literal["shared", "worktree"] = Field(
        default="shared",
        description="Runtime-resolved isolation policy.",
    )
    target_repos: list[str] = Field(
        default_factory=list,
        description=(
            "Project repository names or exact absolute paths that receive a "
            "task worktree. Multiple entries create one atomic worktree set."
        ),
    )
    worktree_allocation: dict | None = Field(
        default=None,
        description="Runtime-owned durable worktree allocation metadata.",
    )
    complexity: Literal["auto", "trivial", "simple", "multi_step", "complex"] = Field(
        default="auto",
        description="Task complexity used for adaptive reasoning and verification.",
    )


# ── Tool description ─────────────────────────────────────────────────────────

_DELEGATE_DESCRIPTION = (
    "Delegate a structured task to one or more team members with explicit "
    "goal, expected output, and constraints. Use this instead of team_message "
    "when assigning substantial work — it gives the member a clear contract "
    "of what 'done' looks like, reducing back-and-forth and improving output "
    "quality. For quick questions or coordination, use team_message instead."
)


def format_delegation_message(
    agent_name: str,
    task_id: str,
    spec_data: TaskSpec | dict,
    *,
    attempt: int = 1,
) -> str:
    """Render the durable task contract delivered through the mailbox."""
    spec = (
        spec_data
        if isinstance(spec_data, TaskSpec)
        else TaskSpec.model_validate(spec_data)
    )
    priority_icon = {
        "low": "○",
        "normal": "●",
        "high": "◉",
        "critical": "🔴",
    }[spec.priority]
    formatted_lines = [
        f"[{agent_name}] {priority_icon} TASK DELEGATION:",
        f"**Task ID:** {task_id}",
        f"**Attempt:** {attempt}",
        f"**Goal:** {spec.goal}",
        f"**Expected output:** {spec.expected_output}",
    ]
    if spec.constraints:
        formatted_lines.append("**Constraints:**")
        formatted_lines.extend(f"  • {constraint}" for constraint in spec.constraints)
    if spec.context:
        formatted_lines.append(f"**Context:** {spec.context}")
    if spec.depends_on:
        formatted_lines.append(f"**Depends on:** {', '.join(spec.depends_on)}")
    if spec.target_paths:
        mode = "exclusive" if spec.exclusive_paths else "shared"
        formatted_lines.append(
            f"**Target paths ({mode}):** {', '.join(spec.target_paths)}"
        )
    formatted_lines.append(
        f"**Isolation:** {spec.resolved_isolation} (requested: {spec.isolation})"
    )
    if spec.target_repos:
        formatted_lines.append(
            f"**Target repositories:** {', '.join(spec.target_repos)}"
        )
    allocation = spec.worktree_allocation
    if isinstance(allocation, dict):
        repositories = [
            item
            for item in allocation.get("repositories", [])
            if isinstance(item, dict)
        ]
        if repositories:
            formatted_lines.append("**Assigned worktrees:**")
            formatted_lines.extend(
                f"  • {item.get('source')}: {item.get('workspace')}"
                for item in repositories
            )
    formatted_lines.append(f"**Complexity:** {spec.complexity}")
    if spec.deadline_at:
        formatted_lines.append(f"**Deadline:** {spec.deadline_at.isoformat()}")
    if spec.dependency_results:
        formatted_lines.append("**Dependency results:**")
        for dependency in spec.dependency_results:
            rendered = json.dumps(dependency, ensure_ascii=False, default=str)
            formatted_lines.append(f"  - {rendered}")
    formatted_lines.append(
        "Use this exact Task ID in partial/final `team_handoff` calls."
    )
    return "\n".join(formatted_lines)


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
                    "Delegation task UUIDs this task depends on. The runtime "
                    "will dispatch it only after all dependencies complete."
                ),
            ),
        ] = [],  # noqa: B006
        deadline_at: Annotated[
            datetime | None,
            Field(
                description=(
                    "Optional timezone-aware ISO 8601 deadline. "
                    "Example: 2026-07-25T18:00:00+07:00."
                )
            ),
        ] = None,
        target_paths: Annotated[
            list[str],
            Field(
                description=(
                    "Workspace-relative files/directories the task may modify. "
                    "Use precise paths so parallel members cannot collide."
                )
            ),
        ] = [],  # noqa: B006
        exclusive_paths: Annotated[
            bool,
            Field(
                description=(
                    "Reserve target_paths exclusively until final handoff. "
                    "Default true."
                )
            ),
        ] = True,
        isolation: Annotated[
            Literal["auto", "shared", "worktree"],
            Field(
                description=(
                    "Workspace policy chosen by the lead. 'worktree' gives each "
                    "recipient an isolated branch/worktree, 'shared' uses path "
                    "claims, and 'auto' isolates mutable coding tasks."
                )
            ),
        ] = "auto",
        target_repos: Annotated[
            list[str],
            Field(
                description=(
                    "Repository names or exact absolute project-repository paths "
                    "to include. Two or more create a multi-repo worktree set."
                )
            ),
        ] = [],  # noqa: B006
        complexity: Annotated[
            Literal["auto", "trivial", "simple", "multi_step", "complex"],
            Field(
                description=(
                    "Expected task complexity. 'auto' derives it from priority "
                    "and target-path breadth."
                )
            ),
        ] = "auto",
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

        if deadline_at is not None:
            if deadline_at.tzinfo is None:
                return "Error: deadline_at must include a timezone offset."
            if deadline_at <= datetime.now(timezone.utc):
                return "Error: deadline_at must be in the future."
        try:
            normalized_targets = _normalize_target_paths(target_paths)
        except ValueError as exc:
            return f"Error: {exc}"
        try:
            from app.services.delegation_worktree_service import resolve_isolation

            resolved_isolation = resolve_isolation(
                requested=isolation,
                team_mode=team.mode if team is not None else "work",
                target_paths=normalized_targets,
                target_repos=list(target_repos),
            )
        except ValueError as exc:
            return f"Error: {exc}"
        if (
            resolved_isolation == "shared"
            and exclusive_paths
            and normalized_targets
            and len(resolved) > 1
        ):
            return (
                "Error: exclusive target_paths cannot be assigned to multiple "
                "recipients in one delegation. Split the paths into separate tasks "
                "or use worktree isolation."
            )

        # Build task spec
        spec = TaskSpec(
            goal=goal,
            expected_output=expected_output,
            constraints=list(constraints),
            context=context,
            priority=priority,
            depends_on=list(depends_on),
            deadline_at=deadline_at,
            target_paths=normalized_targets,
            exclusive_paths=exclusive_paths,
            isolation=isolation,
            resolved_isolation=resolved_isolation,
            target_repos=list(target_repos),
            complexity=complexity,
        )
        spec_json = spec.model_dump(mode="json", exclude_none=True)

        if team is not None:
            try:
                tasks = await team.create_delegation_tasks(
                    delegator=agent_name,
                    recipients=resolved,
                    spec=spec_json,
                    dependencies=list(depends_on),
                    deadline_at=deadline_at,
                )
            except (TypeError, ValueError) as exc:
                return f"Error: {exc}"
            task_ids = [str(task.id) for task in tasks]
            try:
                await team.dispatch_delegation_tasks(tasks)
            except (OSError, RuntimeError, ValueError) as exc:
                _emit_delegation_event(team, agent_name, resolved, task_ids, spec_json)
                return (
                    f"Error: delegation workspace allocation/dispatch failed: {exc}. "
                    f"Durable Task IDs: {', '.join(task_ids)}. "
                    "Inspect these tasks to retry, merge, or explicitly discard "
                    "any allocated worktrees."
                )
            blocked = [str(task.id) for task in tasks if task.status == "blocked"]
        else:
            task_ids = []
            for recipient in resolved:
                task_id = str(uuid7())
                msg = Message(
                    from_agent=agent_name,
                    to_agent=recipient,
                    content=format_delegation_message(
                        agent_name, task_id, spec, attempt=1
                    ),
                    extra={
                        "kind": "delegation",
                        "task_id": task_id,
                        "_task_spec": spec_json,
                    },
                )
                await mailbox.send(to=recipient, message=msg)
                task_ids.append(task_id)
            blocked = []

        _emit_delegation_event(team, agent_name, resolved, task_ids, spec_json)
        suffix = f" Task IDs: {', '.join(task_ids)}."
        if blocked:
            suffix += f" Blocked on dependencies: {', '.join(blocked)}."
        return f"Task delegated to {', '.join(resolved)}.{suffix}"

    return Tool(team_delegate, name="team_delegate", description=_DELEGATE_DESCRIPTION)


def _normalize_target_paths(paths: list[str]) -> list[str]:
    from pathlib import PurePosixPath

    normalized: list[str] = []
    for raw in paths:
        value = raw.strip().replace("\\", "/")
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError(
                f"target path must be non-empty, workspace-relative, and traversal-free: {raw!r}"
            )
        clean = path.as_posix().rstrip("/")
        if clean not in normalized:
            normalized.append(clean)
    return normalized


# ── SSE event emission ───────────────────────────────────────────────────────


def _emit_delegation_event(
    team: "AgentTeam | None",
    from_agent: str,
    to_agents: list[str],
    task_ids: list[str],
    spec: dict,
) -> None:
    """Push a ``delegation`` SSE event to the stream store (fire-and-forget).

    Uses ``from_parts`` because the delegation event carries team-specific
    fields not worth a full typed event class in ``events.py`` — the same
    pattern used for ``handoff`` and ``inbox`` events.
    """
    if team is None:
        return
    try:
        import asyncio

        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        lead_session = team.lead.session_id
        envelope = StreamEnvelope.from_parts(
            event="delegation",
            data={
                "type": "delegation",
                "from": from_agent,
                "to": to_agents,
                "task_ids": task_ids,
                "title": str(spec.get("goal") or "Delegated task")[:120],
                "spec": spec,
            },
        )
        # Use create_task so we don't block the tool return
        asyncio.create_task(stream_store.push_event(lead_session, envelope))
    except Exception as exc:
        logger.debug("delegation_event_emit_failed error={}", exc)
