"""Standalone EASD plan submission tool.

Decoupled from team orchestration — uses a protocol-based context
instead of direct AgentTeam reference. Works in both single-agent
and multi-agent modes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field

from app.agent.easd.context import EasdContext
from app.agent.tools.registry import InjectedArg, Tool
from app.core.db import resolve_db_factory
from app.services.trace_contracts import TracePlan
from app.services.trace_service import (
    TraceConflict,
    TraceNotFound,
    TraceValidationError,
    submit_authored_plan,
)


def make_easd_plan_tool(ctx: EasdContext, *, agent_name: str) -> Tool:
    async def easd_submit_plan(
        run_id: Annotated[
            str,
            Field(description="EASD run UUID from the planning prompt."),
        ],
        plan: Annotated[
            TracePlan,
            Field(
                description=(
                    "Complete provider-neutral mission graph derived from the "
                    "exact accepted specification hash."
                )
            ),
        ],
        summary: Annotated[
            str,
            Field(
                min_length=20,
                max_length=2_000,
                description="Concise coverage, dependency, and risk summary.",
            ),
        ],
        confidence: Annotated[
            float,
            Field(ge=0, le=1, description="Confidence after plan self-review."),
        ],
        _state: Annotated[Any, InjectedArg()] = None,
    ) -> str:
        """Submit one complete plan draft for explicit user approval."""

        db_factory = resolve_db_factory(ctx.db_factory)
        try:
            async with db_factory() as db:
                try:
                    revision = await submit_authored_plan(
                        db,
                        run_id=run_id,
                        session_id=ctx.session_id,
                        plan=plan,
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
            _state.metadata["stop_after_tool_call"] = "easd_submit_plan"
        return (
            "Plan draft persisted for user review. "
            f"revision={revision.id} hash={revision.content_hash}. "
            "Do not implement or approve it; stop and ask the user to review."
        )

    return Tool(
        easd_submit_plan,
        name="easd_submit_plan",
        lead_only=True,
        description=(
            "Persist the complete mission plan for the current EASD planning "
            "run and move it to human review. This never approves the plan or "
            "starts implementation."
        ),
    )


__all__ = ["make_easd_plan_tool"]
