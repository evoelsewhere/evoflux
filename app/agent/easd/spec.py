"""Standalone EASD specification submission tool.

Decoupled from team orchestration — uses EasdContext instead of
direct AgentTeam reference. Works in both single-agent and
multi-agent modes. Lead-only: only the primary agent can author specs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field

from app.agent.easd.context import EasdContext
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool
from app.agent.verification import probe_verification_commands
from app.core.db import resolve_db_factory
from app.services.trace_contracts import (
    TraceSpecification,
    TraceVerificationProbe,
    validate_delivery_flow_reasoning,
    validate_verification_probes,
)
from app.services.trace_service import (
    TraceConflict,
    TraceNotFound,
    TraceValidationError,
    submit_authored_specification,
)


def make_easd_spec_tool(ctx: EasdContext, *, agent_name: str) -> Tool:
    async def easd_submit_specification(
        run_id: Annotated[
            str,
            Field(description="EASD run UUID from the specification-authoring prompt."),
        ],
        specification: Annotated[
            TraceSpecification,
            Field(
                description=(
                    "Complete provider-neutral specification payload to persist "
                    "and attach to the current EASD run."
                )
            ),
        ],
        summary: Annotated[
            str,
            Field(
                min_length=20,
                max_length=2_000,
                description="Concise grounding and key decisions for human review.",
            ),
        ],
        confidence: Annotated[
            float,
            Field(
                ge=0,
                le=1,
                description="Confidence after clarification and repository inspection.",
            ),
        ],
        _state: Annotated[Any, InjectedArg()] = None,
    ) -> str:
        """Persist one complete specification draft for explicit user approval."""

        # Authoring is read-only, so the runtime — not the agent — executes the
        # proposed verification commands. That keeps the measurement on the
        # runtime side and avoids demanding proof the phase cannot produce.
        workspace = get_sandbox().workspace_root
        measured = await probe_verification_commands(
            workspace, list(specification.verification_commands)
        )
        probes = [
            TraceVerificationProbe(command=command, exit_code=exit_code, detail=detail)
            for command, exit_code, detail in measured
        ]
        blocking = [
            *validate_delivery_flow_reasoning(specification.delivery_flow),
            *validate_verification_probes(specification, probes),
        ]
        if blocking:
            return (
                "Rejected: the specification is not admissible yet. Fix these and "
                "call easd_submit_specification again.\n"
                + "\n".join(f"- {problem}" for problem in blocking)
            )

        db_factory = resolve_db_factory(ctx.db_factory)
        try:
            async with db_factory() as db:
                try:
                    revision = await submit_authored_specification(
                        db,
                        run_id=run_id,
                        session_id=ctx.session_id,
                        specification=specification,
                        authoring={
                            "mode": "agent_chat",
                            "agent": agent_name,
                            "session_id": ctx.session_id,
                            "summary": summary.strip(),
                            "confidence": confidence,
                            "submitted_at": datetime.now(UTC).isoformat(),
                            "verification_probe": [
                                probe.model_dump() for probe in probes
                            ],
                        },
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
            # Name the failure class so a retry loop is visible in the
            # transcript instead of reading as a silent no-op.
            return f"Rejected ({type(exc).__name__}): {exc}"
        if _state is not None:
            _state.metadata["stop_after_tool_call"] = "easd_submit_specification"
        proven = ", ".join(
            f"{probe.command} -> exit {probe.exit_code}" for probe in probes
        )
        # Reported as runtime-measured so the reviewer knows it is not a claim.
        return (
            "Accepted: specification draft persisted for user review. "
            f"revision={revision.id} hash={revision.content_hash} "
            f"flow={specification.delivery_flow.mode}. "
            + (f"Runtime-measured verification: {proven}. " if proven else "")
            + "Do not approve it; stop and ask the user to review the draft."
        )

    return Tool(
        easd_submit_specification,
        name="easd_submit_specification",
        lead_only=True,
        description=(
            "Persist the complete specification for the current EASD authoring "
            "run and move it to user review. This never approves the spec or "
            "starts implementation."
        ),
    )


__all__ = ["make_easd_spec_tool"]
