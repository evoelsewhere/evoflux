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
from app.agent.tools.registry import InjectedArg, Tool
from app.core.db import resolve_db_factory
from app.services.trace_contracts import TraceSpecification
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
                        },
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
            return f"Error: {exc}"
        if _state is not None:
            _state.metadata["stop_after_tool_call"] = "easd_submit_specification"
        return (
            "Specification draft persisted for user review. "
            f"revision={revision.id} hash={revision.content_hash}. "
            "Do not approve it; stop and ask the user to review the draft."
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
