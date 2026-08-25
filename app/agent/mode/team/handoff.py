"""Structured handoff schema and tool — typed deliverables between agents.

``team_handoff`` is the structured counterpart to ``team_message``.  While
``team_message`` is free-form text for questions, instructions, and casual
coordination, ``team_handoff`` enforces a typed ``HandoffArtifact`` so
deliverables (research findings, strategy proposals, review outcomes) carry
machine-readable metadata that the lead and UI can consume without parsing
prose.

The artifact is persisted in the DB message ``extra`` field and surfaced to
the frontend via a dedicated ``handoff`` SSE event, enabling richer
rendering (confidence badges, finding lists, status indicators) than plain
text blocks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import InjectedArg, Tool

if TYPE_CHECKING:
    from app.agent.mode.team.mailbox import TeamMailbox
    from app.agent.mode.team.team import AgentTeam


# ── Artifact schema ──────────────────────────────────────────────────────────


class Verification(BaseModel):
    """Self-verification record attached to a handoff deliverable.

    Captures *whether* and *how* the sender verified their work before
    handing it off.  The lead uses this to decide whether an independent
    sanity-check is still needed.
    """

    verified: bool = Field(
        description="True if the sender performed a verification step.",
    )
    method: str = Field(
        description=(
            "How the work was verified (e.g. 'read output file', "
            "'ran tests', 'checked command exit code')."
        ),
    )
    result: str | None = Field(
        default=None,
        description=(
            "What the verification found "
            "(e.g. 'file exists, 45 lines', 'all 12 tests pass')."
        ),
    )
    command_ids: list[str] = Field(default_factory=list)
    exit_codes: list[int] = Field(default_factory=list)
    revision: str | None = None
    artifact_hash: str | None = None
    completion_contract: dict | None = Field(
        default=None,
        description="Runtime-generated changed-file and command evidence snapshot.",
    )


class CriterionResult(BaseModel):
    """One mission-owned EASD acceptance criterion result."""

    criterion_id: str = Field(min_length=3, max_length=64)
    result: Literal["passed", "failed", "inconclusive"]
    summary: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list)


class HandoffArtifact(BaseModel):
    """Structured deliverable passed between agents via ``team_handoff``.

    Fields are intentionally flat and optional (except ``summary``) so the
    LLM can fill what's relevant without boilerplate.  The schema is kept
    simple to maximise adoption — overly complex schemas cause LLMs to
    fall back to ``team_message`` instead.
    """

    task_id: str | None = Field(
        default=None,
        description="Delegation task UUID this artifact satisfies.",
    )
    summary: str = Field(
        description="1–3 sentence TL;DR of the deliverable.",
    )
    status: Literal["partial", "final"] = Field(
        default="final",
        description=(
            "'partial' if more results are coming in follow-up handoffs; "
            "'final' when this is the complete deliverable."
        ),
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Key findings, conclusions, or action items — one per entry.",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting data, quotes, file paths, or URLs backing the findings.",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Self-assessed confidence in the deliverable (0.0–1.0).",
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up actions for the recipient.",
    )
    raw_data: str | None = Field(
        default=None,
        description=(
            "Extended output, full analysis text, or large data dump. "
            "Omit when the summary + findings suffice."
        ),
    )
    verification: Verification | None = Field(
        default=None,
        description=(
            "Self-verification record. Fill when you verified your work "
            "(e.g. read a file you wrote, ran tests, checked command output). "
            "Omit only for pure research/analysis with no verifiable side-effects."
        ),
    )
    workspace_result: dict | None = Field(
        default=None,
        description=(
            "Runtime-generated commit/diff metadata for an isolated delegation. "
            "Members do not populate this field."
        ),
    )
    criteria_results: list[CriterionResult] = Field(default_factory=list)
    deviations: list[str] = Field(default_factory=list)


# ── Tool descriptions ───────────────────────────────────────────────────────

_HANDOFF_LEAD_DESCRIPTION = (
    "Deliver a structured result to one or more team members. "
    "Use for task delegation results, synthesised findings, and formal deliverables. "
    "Prefer this over team_message when sending substantial work output "
    "that benefits from structure (findings, evidence, confidence, next actions)."
)

_HANDOFF_MEMBER_DESCRIPTION = (
    "Deliver your work output as a structured artifact. "
    "REQUIRED for all final deliverables — use team_message only for quick questions "
    "or clarifications. The artifact's summary, findings, and evidence fields let "
    "the recipient act on your work without re-parsing prose."
)


def format_handoff_message(
    agent_name: str,
    artifact_data: HandoffArtifact | dict,
) -> str:
    """Render a handoff artifact for initial delivery or durable replay."""
    artifact = (
        artifact_data
        if isinstance(artifact_data, HandoffArtifact)
        else HandoffArtifact.model_validate(artifact_data)
    )
    status_label = "📋 PARTIAL" if artifact.status == "partial" else "📋 FINAL"
    lines = [
        f"[{agent_name}] {status_label} HANDOFF:",
        f"Summary: {artifact.summary}",
    ]
    if artifact.task_id:
        lines.insert(1, f"Task ID: {artifact.task_id}")
    if artifact.findings:
        lines.append("Findings:")
        lines.extend(f"  • {finding}" for finding in artifact.findings)
    if artifact.evidence:
        lines.append("Evidence:")
        lines.extend(f"  ◦ {evidence}" for evidence in artifact.evidence)
    if artifact.confidence is not None:
        lines.append(f"Confidence: {artifact.confidence:.0%}")
    if artifact.next_actions:
        lines.append("Next actions:")
        lines.extend(f"  → {action}" for action in artifact.next_actions)
    if artifact.verification is not None:
        if artifact.verification.verified:
            verification_line = f"Verification: ✅ {artifact.verification.method}"
            if artifact.verification.result:
                verification_line += f" — {artifact.verification.result}"
        else:
            verification_line = (
                f"Verification: ⚠️ Not verified ({artifact.verification.method})"
            )
            if artifact.verification.result:
                verification_line += f" — {artifact.verification.result}"
        lines.append(verification_line)
    if artifact.criteria_results:
        lines.append("EASD criteria:")
        lines.extend(
            f"  • {item.criterion_id}: {item.result} — {item.summary}"
            for item in artifact.criteria_results
        )
    if artifact.deviations:
        lines.append("EASD deviations:")
        lines.extend(f"  ⚠ {item}" for item in artifact.deviations)
    if artifact.workspace_result:
        repositories = artifact.workspace_result.get("repositories", [])
        lines.append(
            f"Workspace review: {len(repositories)} repository "
            f"worktree{'s' if len(repositories) != 1 else ''} awaiting lead review"
        )
    return "\n".join(lines)


# ── Tool factory ─────────────────────────────────────────────────────────────


def make_team_handoff_tool(
    mailbox: "TeamMailbox",
    agent_name: str,
    role: Literal["lead", "member"] = "member",
    team: "AgentTeam | None" = None,
) -> Tool:
    """Return the ``team_handoff`` tool bound to *agent_name*.

    Mirrors ``make_team_message_tool`` for recipient resolution but carries
    a structured ``HandoffArtifact`` payload instead of free text.
    """

    async def team_handoff(
        to: Annotated[
            list[str],
            Field(
                description=(
                    "Recipient names — exact instance handles "
                    "(e.g. 'executor#1') or the bare blueprint name "
                    "when only one instance is live."
                ),
            ),
        ],
        summary: Annotated[
            str,
            Field(description="1–3 sentence TL;DR of the deliverable."),
        ],
        task_id: Annotated[
            str | None,
            Field(
                description=(
                    "Delegation task UUID being reported. Required when more "
                    "than one task from the same delegator is pending."
                )
            ),
        ] = None,
        findings: Annotated[
            list[str],
            Field(
                description="Key findings, conclusions, or action items — one per entry.",
            ),
        ] = [],  # noqa: B006
        status: Annotated[
            Literal["partial", "final"],
            Field(
                description=(
                    "'partial' if more results coming; 'final' for complete deliverable."
                ),
            ),
        ] = "final",
        evidence: Annotated[
            list[str],
            Field(
                description="Supporting data, quotes, file paths, or URLs.",
            ),
        ] = [],  # noqa: B006
        confidence: Annotated[
            float | None,
            Field(
                description="Self-assessed confidence (0.0–1.0). Omit if not applicable.",
            ),
        ] = None,
        next_actions: Annotated[
            list[str],
            Field(
                description="Suggested follow-up actions for the recipient.",
            ),
        ] = [],  # noqa: B006
        raw_data: Annotated[
            str | None,
            Field(
                description=(
                    "Extended analysis text or large data. "
                    "Omit when summary + findings suffice."
                ),
            ),
        ] = None,
        verified: Annotated[
            bool | None,
            Field(
                description=(
                    "True if you verified your work (read a file you wrote, "
                    "ran tests, checked output). None to skip verification record."
                ),
            ),
        ] = None,
        verification_method: Annotated[
            str | None,
            Field(
                description=(
                    "How you verified (e.g. 'read output file', 'ran tests', "
                    "'checked exit code'). Required when verified is set."
                ),
            ),
        ] = None,
        verification_result: Annotated[
            str | None,
            Field(
                description=(
                    "What verification found (e.g. 'file exists, 45 lines', "
                    "'all 12 tests pass'). Optional."
                ),
            ),
        ] = None,
        criteria_results: Annotated[
            list[dict[str, Any]],
            Field(
                description=(
                    "EASD criterion results: criterion_id, "
                    "passed|failed|inconclusive result, summary, evidence_ids."
                )
            ),
        ] = [],  # noqa: B006
        deviations: Annotated[
            list[str],
            Field(description="EASD scope/spec deviations discovered by the mission."),
        ] = [],  # noqa: B006
        _state: Annotated[Any, InjectedArg()] = None,
    ) -> str:
        """Deliver a structured work artifact to teammates."""
        from app.agent.mode.team.mailbox import Message
        from app.agent.mode.team.tools import _recipient_error, _resolve

        # Validate confidence range
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            return "Error: confidence must be between 0.0 and 1.0."

        # Resolve recipients
        requested = [r for r in to if r != agent_name]
        if not requested:
            return "No valid recipients (cannot handoff to yourself)."

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

        linked_task_id = task_id
        linked_task = None
        if team is not None:
            if linked_task_id is not None and len(resolved) != 1:
                return "Error: a task-linked handoff must have exactly one recipient."
            if linked_task_id is None:
                matches = [
                    (recipient, candidate)
                    for recipient in resolved
                    for candidate in team.pending_delegation_task_ids(
                        recipient, agent_name
                    )
                ]
                if len(matches) > 1:
                    return (
                        "Error: multiple pending delegation tasks match this handoff; "
                        "pass the exact task_id."
                    )
                if len(matches) == 1:
                    if len(resolved) != 1:
                        return "Error: a task-linked handoff must have exactly one recipient."
                    linked_task_id = matches[0][1]
            if linked_task_id is not None:
                try:
                    linked_task = await team.validate_delegation(
                        task_id=linked_task_id,
                        delegator=resolved[0],
                        recipient=agent_name,
                        allow_completed=status == "final",
                    )
                except (TypeError, ValueError) as exc:
                    return f"Error: {exc}"

        contract = (
            _state.metadata.get("completion_contract") if _state is not None else None
        )
        machine_verified = isinstance(contract, dict) and contract.get("passed") is True

        # Build verification from machine evidence when available. Self-reported
        # fields remain useful for non-coding/research handoffs only.
        verification: Verification | None = None
        if machine_verified:
            records = [
                item for item in contract.get("evidence", []) if isinstance(item, dict)
            ]
            verification = Verification(
                verified=True,
                method="completion_contract",
                result=f"{len(records)} deterministic check(s) passed.",
                command_ids=[
                    str(item["command_id"])
                    for item in records
                    if item.get("command_id")
                ],
                exit_codes=[
                    int(item["exit_code"])
                    for item in records
                    if isinstance(item.get("exit_code"), int)
                ],
                revision=next(
                    (str(item["revision"]) for item in records if item.get("revision")),
                    None,
                ),
                artifact_hash=str(contract.get("artifact_hash") or "") or None,
                completion_contract=contract,
            )
        elif verified is not None:
            verification = Verification(
                verified=verified,
                method=verification_method
                or ("unspecified" if verified else "skipped"),
                result=verification_result,
            )

        # ── System-level quality gate ────────────────────────────────────
        # Reject obviously inadequate handoffs at the tool level so the LLM
        # cannot bypass quality requirements via social agreement.
        if status == "final":
            quality_issues: list[str] = []
            if not findings:
                quality_issues.append(
                    "A final handoff must include at least one finding. "
                    "List your key conclusions or results in 'findings'."
                )
            if not summary.strip() or len(summary.strip()) < 20:
                quality_issues.append(
                    "Summary is too short — provide a meaningful 1–3 sentence TL;DR "
                    "(at least 20 characters)."
                )
            # Members delivering final work that mutated state MUST verify
            if role == "member" and verification is None:
                quality_issues.append(
                    "Final deliverables require a verification record. "
                    "Set verified=True/False with verification_method describing "
                    "how you checked your work (or why you didn't)."
                )
            changed_files = (
                _state.metadata.get("_verification_changed_files")
                if _state is not None
                else None
            )
            if role == "member" and changed_files and not machine_verified:
                quality_issues.append(
                    "Changed-file deliverables require a passing machine-generated "
                    "CompletionContract; self-reported verification is not sufficient."
                )
            trace_assigned = (
                [
                    str(item)
                    for item in linked_task.spec.get("acceptance_criteria", [])
                    if isinstance(item, str)
                ]
                if linked_task is not None and linked_task.trace_run_id is not None
                else []
            )
            try:
                parsed_criteria = [
                    CriterionResult.model_validate(item) for item in criteria_results
                ]
            except ValueError as exc:
                quality_issues.append(f"Invalid EASD criteria_results: {exc}")
                parsed_criteria = []
            if trace_assigned:
                provided = {item.criterion_id for item in parsed_criteria}
                missing = sorted(set(trace_assigned) - provided)
                if missing:
                    quality_issues.append(
                        "EASD final handoff must report every assigned criterion: "
                        + ", ".join(missing)
                    )
            if quality_issues:
                return (
                    "HANDOFF BLOCKED — quality gate failed:\n"
                    + "\n".join(f"• {q}" for q in quality_issues)
                    + "\n\nFix these issues and call team_handoff again."
                )
        # ─────────────────────────────────────────────────────────────────

        # Build artifact
        parsed_criteria = [
            CriterionResult.model_validate(item) for item in criteria_results
        ]
        artifact = HandoffArtifact(
            task_id=linked_task_id,
            summary=summary,
            status=status,
            findings=list(findings),
            evidence=list(evidence),
            confidence=confidence,
            next_actions=list(next_actions),
            raw_data=raw_data,
            verification=verification,
            criteria_results=parsed_criteria,
            deviations=list(deviations),
        )

        artifact_json = artifact.model_dump(mode="json", exclude_none=True)
        formatted = format_handoff_message(agent_name, artifact)

        if team is not None and status == "final" and linked_task_id is not None:
            try:
                linked_task = await team.complete_delegation(
                    task_id=linked_task_id,
                    delegator=resolved[0],
                    recipient=agent_name,
                    artifact=artifact_json,
                )
                artifact = HandoffArtifact.model_validate(artifact_json)
                formatted = format_handoff_message(agent_name, artifact)
            except (TypeError, ValueError, RuntimeError) as exc:
                return f"Error: {exc}"

        # Emit only after the durable state transition succeeds.
        _emit_handoff_event(team, agent_name, resolved, artifact_json)

        for recipient in resolved:
            message_id = None
            if status == "final" and linked_task_id and linked_task is not None:
                message_id = f"{linked_task_id}:handoff:{linked_task.attempt}"
            message_extra = {
                "kind": "handoff",
                "task_id": linked_task_id,
                "_handoff_artifact": artifact_json,
            }
            if message_id:
                msg = Message(
                    id=message_id,
                    from_agent=agent_name,
                    to_agent=recipient,
                    content=formatted,
                    extra=message_extra,
                )
            else:
                msg = Message(
                    from_agent=agent_name,
                    to_agent=recipient,
                    content=formatted,
                    extra=message_extra,
                )
            await mailbox.send(to=recipient, message=msg)

        if _state is not None and status == "final" and linked_task_id is not None:
            # The durable task is complete and its handoff is delivered. Ask
            # the loop to stop after persisting this tool result instead of
            # making another model call that can duplicate work or fail after
            # success.
            _state.metadata["stop_after_tool_call"] = "team_handoff"

        return f"Handoff delivered to {', '.join(resolved)}."

    description = (
        _HANDOFF_LEAD_DESCRIPTION if role == "lead" else _HANDOFF_MEMBER_DESCRIPTION
    )
    return Tool(team_handoff, name="team_handoff", description=description)


# ── SSE event emission ───────────────────────────────────────────────────────


def _emit_handoff_event(
    team: "AgentTeam | None",
    from_agent: str,
    to_agents: list[str],
    artifact: dict,
) -> None:
    """Push a ``handoff`` SSE event to the stream store (fire-and-forget).

    Uses ``from_parts`` because the handoff event carries team-specific
    fields not worth a full typed event class in ``events.py`` — the same
    pattern used for ``inbox`` events.
    """
    if team is None:
        return
    try:
        import asyncio

        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        lead_session = team.lead.session_id
        env = StreamEnvelope.from_parts(
            "handoff",
            {
                "type": "handoff",
                "from_agent": from_agent,
                "to_agents": to_agents,
                "artifact": artifact,
            },
        )
        # Use create_task so we don't block the tool return
        asyncio.create_task(stream_store.push_event(lead_session, env))
    except Exception:
        logger.debug("handoff_event_emit_skipped agent={}", from_agent)
