"""Durable state transitions and accounting for session Goal mode."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession
from app.models.goal import SessionGoal

GoalStatus = Literal["active", "paused", "complete", "blocked"]

GOAL_OBJECTIVE_MAX_CHARS = 4_000
BLOCKED_STREAK_REQUIRED = 3
_TERMINAL_STATUSES = frozenset({"complete", "blocked"})


class GoalError(RuntimeError):
    """Base error for invalid goal operations."""


class GoalNotFoundError(GoalError):
    pass


class GoalConflictError(GoalError):
    pass


class GoalValidationError(GoalError):
    pass


class GoalSnapshot(BaseModel):
    """Transport-neutral view with live elapsed time folded in."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID
    objective: str
    status: GoalStatus
    token_budget: int | None
    tokens_used: int
    time_used_seconds: float
    pause_reason: str | None
    blocker_streak: int
    status_details: dict | None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_now(now: datetime | None) -> datetime:
    value = now or utcnow()
    if value.tzinfo is None:
        raise GoalValidationError("Goal timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _validate_objective(objective: str) -> str:
    value = objective.strip()
    if not value:
        raise GoalValidationError("Goal objective must not be empty.")
    if len(value) > GOAL_OBJECTIVE_MAX_CHARS:
        raise GoalValidationError(
            f"Goal objective must be at most {GOAL_OBJECTIVE_MAX_CHARS} characters."
        )
    return value


def _validate_budget(token_budget: int | None) -> int | None:
    if token_budget is not None and token_budget <= 0:
        raise GoalValidationError("Goal token budget must be greater than zero.")
    return token_budget


def _elapsed(goal: SessionGoal, now: datetime) -> float:
    elapsed = float(goal.time_used_seconds)
    if goal.status == "active" and goal.active_started_at is not None:
        elapsed += max((now - goal.active_started_at).total_seconds(), 0.0)
    return elapsed


def snapshot(goal: SessionGoal, *, now: datetime | None = None) -> GoalSnapshot:
    current = _validate_now(now)
    return GoalSnapshot(
        session_id=goal.session_id,
        objective=goal.objective,
        status=cast(GoalStatus, goal.status),
        token_budget=goal.token_budget,
        tokens_used=goal.tokens_used,
        time_used_seconds=_elapsed(goal, current),
        pause_reason=goal.pause_reason,
        blocker_streak=goal.blocker_streak,
        status_details=dict(goal.status_details) if goal.status_details else None,
        version=goal.version,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
        completed_at=goal.completed_at,
    )


async def get_goal(db: AsyncSession, session_id: UUID) -> SessionGoal | None:
    return await db.get(SessionGoal, session_id)


async def require_goal(db: AsyncSession, session_id: UUID) -> SessionGoal:
    goal = await get_goal(db, session_id)
    if goal is None:
        raise GoalNotFoundError("No goal is attached to this session.")
    return goal


def _check_version(goal: SessionGoal, expected_version: int | None) -> None:
    if expected_version is not None and goal.version != expected_version:
        raise GoalConflictError(
            f"Goal changed concurrently (expected version {expected_version}, "
            f"found {goal.version})."
        )


def _touch(goal: SessionGoal, now: datetime) -> None:
    goal.version += 1
    goal.updated_at = now


def _stop_clock(goal: SessionGoal, now: datetime) -> None:
    if goal.active_started_at is not None:
        goal.time_used_seconds += max(
            (now - goal.active_started_at).total_seconds(), 0.0
        )
    goal.active_started_at = None


async def replace_goal(
    db: AsyncSession,
    session_id: UUID,
    objective: str,
    *,
    token_budget: int | None = None,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    """Create or explicitly replace a goal, resetting all usage accounting."""

    current = _validate_now(now)
    normalized = _validate_objective(objective)
    budget = _validate_budget(token_budget)
    if await db.get(ChatSession, session_id) is None:
        raise GoalNotFoundError("Session not found.")

    goal = await get_goal(db, session_id)
    if goal is None:
        goal = SessionGoal(
            session_id=session_id,
            objective=normalized,
            token_budget=budget,
            active_started_at=current,
            created_at=current,
            updated_at=current,
        )
    else:
        _check_version(goal, expected_version)
        goal.objective = normalized
        goal.status = "active"
        goal.token_budget = budget
        goal.tokens_used = 0
        goal.time_used_seconds = 0.0
        goal.active_started_at = current
        goal.pause_reason = None
        goal.blocker_fingerprint = None
        goal.blocker_streak = 0
        goal.status_details = None
        goal.completed_at = None
        _touch(goal, current)
    db.add(goal)
    await db.flush()
    return goal


async def pause_goal(
    db: AsyncSession,
    session_id: UUID,
    *,
    reason: str = "user",
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    current = _validate_now(now)
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    if goal.status in _TERMINAL_STATUSES:
        raise GoalConflictError(f"Cannot pause a {goal.status} goal.")
    if goal.status == "active":
        _stop_clock(goal, current)
        goal.status = "paused"
        goal.pause_reason = reason[:50]
        _touch(goal, current)
        db.add(goal)
        await db.flush()
    return goal


async def resume_goal(
    db: AsyncSession,
    session_id: UUID,
    *,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    current = _validate_now(now)
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    if goal.status == "complete":
        raise GoalConflictError(
            "A complete goal cannot be resumed; replace it instead."
        )
    if goal.status != "active":
        goal.status = "active"
        goal.active_started_at = current
        goal.pause_reason = None
        goal.blocker_fingerprint = None
        goal.blocker_streak = 0
        goal.status_details = None
        goal.completed_at = None
        _touch(goal, current)
        db.add(goal)
        await db.flush()
    return goal


async def complete_goal(
    db: AsyncSession,
    session_id: UUID,
    *,
    summary: str,
    evidence: list[str] | None = None,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    current = _validate_now(now)
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    if goal.status != "active":
        raise GoalConflictError("Only an active goal can be completed.")
    completion_summary = summary.strip()
    if not completion_summary:
        raise GoalValidationError("Completion summary must not be empty.")
    _stop_clock(goal, current)
    goal.status = "complete"
    goal.pause_reason = None
    goal.status_details = {
        "summary": completion_summary,
        "evidence": [item.strip() for item in (evidence or []) if item.strip()],
    }
    goal.completed_at = current
    _touch(goal, current)
    db.add(goal)
    await db.flush()
    return goal


def _blocker_fingerprint(blocker: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", blocker.strip().lower())
    if not normalized:
        raise GoalValidationError("Blocked status requires a concrete blocker.")
    return normalized, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def request_blocked(
    db: AsyncSession,
    session_id: UUID,
    *,
    blocker: str,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    """Record a blocker; terminal ``blocked`` requires three matching turns."""

    current = _validate_now(now)
    normalized, fingerprint = _blocker_fingerprint(blocker)
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    if goal.status != "active":
        raise GoalConflictError("Only an active goal can become blocked.")

    goal.blocker_streak = (
        goal.blocker_streak + 1 if goal.blocker_fingerprint == fingerprint else 1
    )
    goal.blocker_fingerprint = fingerprint
    goal.status_details = {
        "blocker": blocker.strip(),
        "normalized_blocker": normalized,
        "required_streak": BLOCKED_STREAK_REQUIRED,
    }
    if goal.blocker_streak >= BLOCKED_STREAK_REQUIRED:
        _stop_clock(goal, current)
        goal.status = "blocked"
        goal.completed_at = current
    _touch(goal, current)
    db.add(goal)
    await db.flush()
    return goal


async def set_token_budget(
    db: AsyncSession,
    session_id: UUID,
    token_budget: int | None,
    *,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> SessionGoal:
    current = _validate_now(now)
    budget = _validate_budget(token_budget)
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    goal.token_budget = budget
    if goal.status == "active" and budget is not None and goal.tokens_used >= budget:
        _stop_clock(goal, current)
        goal.status = "paused"
        goal.pause_reason = "token_budget"
    _touch(goal, current)
    db.add(goal)
    await db.flush()
    return goal


async def add_usage(
    db: AsyncSession,
    session_id: UUID,
    tokens: int,
    *,
    now: datetime | None = None,
) -> SessionGoal | None:
    """Atomically add model tokens and pause an exhausted active goal."""

    if tokens < 0:
        raise GoalValidationError("Token usage must not be negative.")
    current = _validate_now(now)
    goal = await get_goal(db, session_id)
    if goal is None:
        return None
    if tokens:
        table = SessionGoal.__table__  # ty: ignore[unresolved-attribute]
        await db.exec(
            sa.update(SessionGoal)
            .where(table.c.session_id == session_id)
            .values(
                tokens_used=table.c.tokens_used + tokens,
                version=table.c.version + 1,
                updated_at=current,
            )
        )
        await db.flush()
        await db.refresh(goal)

    if (
        goal.status == "active"
        and goal.token_budget is not None
        and goal.tokens_used >= goal.token_budget
    ):
        _stop_clock(goal, current)
        goal.status = "paused"
        goal.pause_reason = "token_budget"
        _touch(goal, current)
        db.add(goal)
        await db.flush()
    return goal


async def clear_goal(
    db: AsyncSession,
    session_id: UUID,
    *,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> GoalSnapshot:
    goal = await require_goal(db, session_id)
    _check_version(goal, expected_version)
    result = snapshot(goal, now=now)
    await db.delete(goal)
    await db.flush()
    return result
