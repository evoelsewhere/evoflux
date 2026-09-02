"""Standalone EASD review evidence submission tool.

Decoupled from team orchestration — uses EasdContext instead of
direct AgentTeam reference. Works in both single-agent and
multi-agent modes. Runtime-identified: any agent can submit reviews.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from app.agent.easd.context import EasdContext
from app.agent.tools.registry import InjectedArg, Tool
from app.core.db import resolve_db_factory
from app.services.trace_contracts import TraceReviewCriterion
from app.services.trace_service import (
    TraceConflict,
    TraceNotFound,
    TraceValidationError,
    submit_review_evidence,
)


def make_easd_review_tool(
    ctx: EasdContext, *, agent_name: str, role: Literal["lead", "member"]
) -> Tool:
    async def easd_submit_review(
        run_id: Annotated[
            str,
            Field(description="Current EASD run UUID."),
        ],
        spec_hash: Annotated[
            str,
            Field(
                min_length=64,
                max_length=64,
                description="Exact accepted spec hash.",
            ),
        ],
        criteria_results: Annotated[
            list[TraceReviewCriterion],
            Field(
                description=(
                    "One cited review verdict submitted by a runtime-identified reviewer."
                )
            ),
        ],
        sources: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=200,
                description="Review evidence sources with stable references.",
            ),
        ],
        summary: Annotated[
            str,
            Field(
                min_length=20, max_length=4_000, description="Concise review summary."
            ),
        ],
        revision: Annotated[
            str,
            Field(min_length=1, max_length=120, description="Reviewed Git revision."),
        ],
        artifact_hash: Annotated[
            str | None,
            Field(max_length=128, description="Artifact hash under review."),
        ] = None,
        confidence: Annotated[
            float | None,
            Field(ge=0, le=1, description="Reviewer confidence score."),
        ] = None,
        delegation_task_id: Annotated[
            UUID | None,
            Field(
                description="Optional EASD delegation task UUID to attach evidence to.",
            ),
        ] = None,
        findings: Annotated[
            list[str],
            Field(max_length=100, description="Key review findings."),
        ] = [],
        _state: Annotated[Any, InjectedArg()] = None,
    ) -> str:
        """Persist cited per-AC review results for the current EASD Review phase."""

        db_factory = resolve_db_factory(ctx.db_factory)
        try:
            async with db_factory() as db:
                try:
                    evidence_list = await submit_review_evidence(
                        db,
                        run_id=run_id,
                        spec_hash=spec_hash,
                        reviewer=agent_name,
                        reviewer_role=role,
                        criteria_results=criteria_results,
                        sources=sources,
                        summary=summary.strip(),
                        revision=revision.strip(),
                        artifact_hash=artifact_hash,
                        confidence=confidence,
                        delegation_task_id=delegation_task_id,
                        findings=findings or [],
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
            return f"Error: {exc}"
        if _state is not None:
            _state.metadata["stop_after_tool_call"] = "easd_submit_review"
        count = len(evidence_list) if evidence_list else 0
        return (
            f"Review results persisted: {count} evidence items submitted. "
            f"spec_hash={spec_hash}. "
            "Do not fix code or start Verify; stop and ask the user to continue."
        )

    return Tool(
        easd_submit_review,
        name="easd_submit_review",
        description=(
            "Persist cited per-AC review results for the current EASD Review "
            "phase using runtime reviewer identity. This never fixes code, "
            "starts Verify, or converges the run."
        ),
    )


__all__ = ["make_easd_review_tool"]
