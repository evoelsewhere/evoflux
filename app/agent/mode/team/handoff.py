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

from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import BaseModel, Field

from app.agent.tools.registry import Tool

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


class HandoffArtifact(BaseModel):
    """Structured deliverable passed between agents via ``team_handoff``.

    Fields are intentionally flat and optional (except ``summary``) so the
    LLM can fill what's relevant without boilerplate.  The schema is kept
    simple to maximise adoption — overly complex schemas cause LLMs to
    fall back to ``team_message`` instead.
    """

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

        # Build verification if provided
        verification: Verification | None = None
        if verified is not None:
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
            if role == "member" and verified is None:
                quality_issues.append(
                    "Final deliverables require a verification record. "
                    "Set verified=True/False with verification_method describing "
                    "how you checked your work (or why you didn't)."
                )
            if quality_issues:
                return (
                    "HANDOFF BLOCKED — quality gate failed:\n"
                    + "\n".join(f"• {q}" for q in quality_issues)
                    + "\n\nFix these issues and call team_handoff again."
                )
        # ─────────────────────────────────────────────────────────────────

        # Build artifact
        artifact = HandoffArtifact(
            summary=summary,
            status=status,
            findings=list(findings),
            evidence=list(evidence),
            confidence=confidence,
            next_actions=list(next_actions),
            raw_data=raw_data,
            verification=verification,
        )

        # Format the message content: human-readable summary + structured payload
        # The text content includes the summary so agents without handoff parsing
        # (older versions, tests) still see useful output.
        artifact_json = artifact.model_dump(mode="json", exclude_none=True)
        status_label = "📋 PARTIAL" if status == "partial" else "📋 FINAL"
        formatted_lines = [
            f"[{agent_name}] {status_label} HANDOFF:",
            f"Summary: {summary}",
        ]
        if findings:
            formatted_lines.append("Findings:")
            for f in findings:
                formatted_lines.append(f"  • {f}")
        if evidence:
            formatted_lines.append("Evidence:")
            for e in evidence:
                formatted_lines.append(f"  ◦ {e}")
        if confidence is not None:
            formatted_lines.append(f"Confidence: {confidence:.0%}")
        if next_actions:
            formatted_lines.append("Next actions:")
            for a in next_actions:
                formatted_lines.append(f"  → {a}")
        if verification is not None:
            if verification.verified:
                v_line = f"Verification: ✅ {verification.method}"
                if verification.result:
                    v_line += f" — {verification.result}"
            else:
                v_line = f"Verification: ⚠️ Not verified ({verification.method})"
                if verification.result:
                    v_line += f" — {verification.result}"
            formatted_lines.append(v_line)

        formatted = "\n".join(formatted_lines)

        # Emit SSE handoff event for the UI
        _emit_handoff_event(team, agent_name, resolved, artifact_json)

        for recipient in resolved:
            msg = Message(
                from_agent=agent_name,
                to_agent=recipient,
                content=formatted,
            )
            # Stash structured artifact in the message for DB persistence
            msg.__dict__["_handoff_artifact"] = artifact_json
            await mailbox.send(to=recipient, message=msg)

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
