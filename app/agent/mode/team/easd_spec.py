"""Lead-only EASD specification submission tool for authoring chats."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool
from app.core.db import resolve_db_factory
from app.services.trace_contracts import TraceSpecification
from app.services.trace_service import (
    TraceConflict,
    TraceNotFound,
    TraceValidationError,
    submit_authored_specification,
)


def make_easd_spec_tool(team, *, agent_name: str) -> Tool:
    async def easd_submit_specification(
        run_id: Annotated[
            str,
            Field(description="EASD run UUID from the specification-authoring prompt."),
        ],
        specification: Annotated[
            TraceSpecification,
            Field(
                description=(
                    "Complete provider-neutral specification drafted from the "
                    "persisted Intent and authorized repository evidence."
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
        """Submit a complete EASD specification draft for user review.

        Use only during a specification-authoring chat. Inspect authorized
        instructions, docs, source and tests first; ask the user when a product
        decision remains ambiguous. This tool persists a draft but never
        approves it and never authorizes implementation.
        """

        db_factory = resolve_db_factory(team._db_factory or team.lead.db_factory)
        try:
            async with db_factory() as db:
                try:
                    revision = await submit_authored_specification(
                        db,
                        run_id=run_id,
                        session_id=team.lead.session_id,
                        specification=specification,
                        authoring={
                            "mode": "agent_chat",
                            "agent": agent_name,
                            "session_id": team.lead.session_id,
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
            "Do not implement or approve it; stop and ask the user to review."
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
