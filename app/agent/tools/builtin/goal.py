"""Lead-only tools for inspecting and completing durable session goals."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool
from app.agent.goal_status import publish_goal_status
from app.core.db import resolve_db_factory
from app.services import goal_service


def _session_id(state: Any) -> UUID:
    metadata = state.metadata if state is not None else {}
    raw = metadata.get("stream_session_id") or metadata.get("session_id")
    if not raw:
        raise goal_service.GoalValidationError("Goal tools require an active session.")
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise goal_service.GoalValidationError("Invalid active session id.") from exc


async def _get_goal(
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Read the current session goal, status, budget, usage, and progress."""

    session_id = _session_id(_state)
    db_factory = resolve_db_factory(None)
    async with db_factory() as db:
        goal = await goal_service.get_goal(db, session_id)
        if goal is None:
            return '{"goal":null}'
        return goal_service.snapshot(goal).model_dump_json()


async def _update_goal(
    status: Annotated[
        Literal["complete", "blocked"],
        Field(
            description=(
                "Terminal status to request. Complete requires verified finished "
                "work; blocked requires the same concrete blocker for three "
                "consecutive goal turns."
            )
        ),
    ],
    summary: Annotated[
        str,
        Field(description="Required completion summary when status is complete."),
    ] = "",
    evidence: Annotated[
        list[str] | None,
        Field(description="Concrete verification evidence for completion."),
    ] = None,
    blocker: Annotated[
        str,
        Field(description="Concrete external blocker when status is blocked."),
    ] = "",
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Mark the active goal complete or report a persistent external blocker."""

    session_id = _session_id(_state)
    db_factory = resolve_db_factory(None)
    async with db_factory() as db:
        if status == "complete":
            goal = await goal_service.complete_goal(
                db,
                session_id,
                summary=summary,
                evidence=evidence,
            )
        else:
            if _state is not None and _state.metadata.get("_goal_blocker_reported"):
                goal = await goal_service.require_goal(db, session_id)
                current = goal_service.snapshot(goal)
                return (
                    "A blocker was already recorded in this goal turn; the streak "
                    f"remains {current.blocker_streak}/3. " + current.model_dump_json()
                )
            goal = await goal_service.request_blocked(
                db,
                session_id,
                blocker=blocker,
            )
            if _state is not None:
                _state.metadata["_goal_blocker_reported"] = True
        await db.commit()
        current = goal_service.snapshot(goal)

    await publish_goal_status(str(session_id), goal, source="agent_tool")

    if status == "blocked" and current.status == "active":
        return (
            f"Blocker recorded for this goal turn ({current.blocker_streak}/3). "
            "The goal remains active. " + current.model_dump_json()
        )
    return current.model_dump_json()


get_goal = Tool(
    _get_goal,
    name="get_goal",
    lead_only=True,
    read_only=True,
    concurrency_safe=True,
    description=(
        "Read the durable goal attached to the current session, including its "
        "objective, status, token budget, usage, elapsed time, and blocker streak."
    ),
)

update_goal = Tool(
    _update_goal,
    name="update_goal",
    lead_only=True,
    description=(
        "Update the current durable goal to complete or report it blocked. Use "
        "complete only after the objective is genuinely achieved and verified. "
        "Blocked becomes terminal only after the same blocker is reported in "
        "three consecutive goal turns."
    ),
)
