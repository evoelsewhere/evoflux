"""Runtime-identified EASD review evidence submission tool."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.agent.tools.registry import Tool
from app.core.db import resolve_db_factory
from app.services.trace_contracts import TraceReviewCriterion
from app.services.trace_service import (
    TraceConflict,
    TraceNotFound,
    TraceValidationError,
    submit_review_evidence,
)


def make_easd_review_tool(team, *, agent_name: str, role: str) -> Tool:
    async def easd_submit_review(
        run_id: Annotated[str, Field(description="Current EASD run UUID.")],
        spec_hash: Annotated[
            str,
            Field(
                min_length=64, max_length=64, description="Exact accepted spec hash."
            ),
        ],
        criteria_results: Annotated[
            list[TraceReviewCriterion],
            Field(min_length=1, max_length=100),
        ],
        findings: Annotated[list[str], Field(default_factory=list, max_length=100)],
        sources: Annotated[list[str], Field(min_length=1, max_length=200)],
        summary: Annotated[str, Field(min_length=20, max_length=4_000)],
        revision: Annotated[
            str,
            Field(min_length=1, max_length=120, description="Reviewed Git revision."),
        ],
        artifact_hash: Annotated[str | None, Field(max_length=128)] = None,
        confidence: Annotated[float | None, Field(ge=0, le=1)] = None,
        delegation_task_id: Annotated[UUID | None, Field(default=None)] = None,
    ) -> str:
        """Persist cited per-AC review evidence without claiming convergence."""

        db_factory = resolve_db_factory(team._db_factory or team.lead.db_factory)
        try:
            async with db_factory() as db:
                try:
                    rows = await submit_review_evidence(
                        db,
                        run_id=run_id,
                        spec_hash=spec_hash,
                        reviewer=agent_name,
                        reviewer_role="lead" if role == "lead" else "member",
                        criteria_results=criteria_results,
                        findings=findings,
                        sources=sources,
                        summary=summary,
                        revision=revision,
                        artifact_hash=artifact_hash,
                        confidence=confidence,
                        delegation_task_id=delegation_task_id,
                    )
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
        except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
            return f"Error: {exc}"
        independent = any(item.payload.get("independent") is True for item in rows)
        return (
            f"Review evidence persisted for {len(rows)} criteria; "
            f"independent={str(independent).lower()}. "
            "The user still controls Run verify and Converge."
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
