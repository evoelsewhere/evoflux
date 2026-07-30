"""Database operations for the durable team delegation ledger."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import _utcnow
from app.models.team import DelegationTask

OPEN_STATUSES = ("blocked", "pending")


def parse_task_id(task_id: str) -> UUID:
    try:
        return UUID(task_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid delegation task ID: {task_id!r}.") from exc


async def expire_overdue_tasks(
    db: AsyncSession, lead_session_id: UUID, *, now: datetime | None = None
) -> list[DelegationTask]:
    """Fail open tasks whose explicit deadline has elapsed."""
    current = now or _utcnow()
    rows = (
        await db.exec(
            select(DelegationTask).where(
                DelegationTask.lead_session_id == lead_session_id,
                col(DelegationTask.status).in_(OPEN_STATUSES),
                col(DelegationTask.deadline_at).is_not(None),
                col(DelegationTask.deadline_at) <= current,
            )
        )
    ).all()
    for row in rows:
        row.status = "failed"
        row.result = {"error": "delegation deadline expired"}
        row.completed_at = current
        row.updated_at = current
        db.add(row)
    return list(rows)


async def load_open_tasks(
    db: AsyncSession, lead_session_id: UUID
) -> list[DelegationTask]:
    await expire_overdue_tasks(db, lead_session_id)
    rows = (
        await db.exec(
            select(DelegationTask)
            .where(
                DelegationTask.lead_session_id == lead_session_id,
                col(DelegationTask.status).in_(OPEN_STATUSES),
            )
            .order_by(col(DelegationTask.created_at).asc())
        )
    ).all()
    return list(rows)


async def create_tasks(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    delegator: str,
    recipients: list[str],
    spec: dict,
    dependencies: list[str],
    deadline_at: datetime | None,
) -> list[DelegationTask]:
    """Create one independently trackable task per recipient."""
    await _validate_path_claims(
        db,
        lead_session_id=lead_session_id,
        recipients=recipients,
        spec=spec,
    )
    dependency_ids = [parse_task_id(task_id) for task_id in dependencies]
    dependency_rows: list[DelegationTask] = []
    if dependency_ids:
        dependency_rows = list(
            (
                await db.exec(
                    select(DelegationTask).where(
                        DelegationTask.lead_session_id == lead_session_id,
                        col(DelegationTask.id).in_(dependency_ids),
                    )
                )
            ).all()
        )
        found = {row.id for row in dependency_rows}
        missing = [str(task_id) for task_id in dependency_ids if task_id not in found]
        if missing:
            raise ValueError(
                "Unknown delegation dependencies in this session: "
                + ", ".join(missing)
                + "."
            )

    blocked = any(row.status != "completed" for row in dependency_rows)
    task_spec = dict(spec)
    if dependency_rows and not blocked:
        task_spec["dependency_results"] = [
            {
                "task_id": str(row.id),
                "recipient": row.recipient,
                "result": row.result,
            }
            for row in dependency_rows
        ]
    tasks: list[DelegationTask] = []
    for recipient in recipients:
        task = DelegationTask(
            lead_session_id=lead_session_id,
            delegator=delegator,
            recipient=recipient,
            status="blocked" if blocked else "pending",
            spec=task_spec,
            dependencies=[str(task_id) for task_id in dependency_ids],
            deadline_at=deadline_at,
            dispatched_at=None,
        )
        db.add(task)
        tasks.append(task)
    await db.flush()
    return tasks


async def _validate_path_claims(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    recipients: list[str],
    spec: dict,
) -> None:
    new_paths = [
        str(path)
        for path in spec.get("target_paths", [])
        if isinstance(path, str) and path
    ]
    if not new_paths or spec.get("exclusive_paths", True) is not True:
        return
    open_tasks = await load_open_tasks(db, lead_session_id)
    conflicts: list[str] = []
    for row in open_tasks:
        if row.recipient in recipients:
            continue
        if row.spec.get("exclusive_paths", True) is not True:
            continue
        existing = [
            str(path)
            for path in row.spec.get("target_paths", [])
            if isinstance(path, str) and path
        ]
        for requested in new_paths:
            for claimed in existing:
                if _paths_overlap(requested, claimed):
                    conflicts.append(
                        f"{requested!r} overlaps {claimed!r} claimed by "
                        f"{row.recipient} (task {row.id})"
                    )
    if conflicts:
        raise ValueError("Conflicting delegation path claims: " + "; ".join(conflicts))


def _paths_overlap(left: str, right: str) -> bool:
    left_parts = tuple(part for part in left.strip("/").split("/") if part)
    right_parts = tuple(part for part in right.strip("/").split("/") if part)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


async def get_task(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    task_id: str,
) -> DelegationTask:
    row = await db.get(DelegationTask, parse_task_id(task_id))
    if row is None or row.lead_session_id != lead_session_id:
        raise ValueError(f"Delegation task '{task_id}' was not found in this session.")
    return row


async def complete_task(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    task_id: str,
    delegator: str,
    recipient: str,
    result: dict,
) -> DelegationTask:
    """Complete exactly one pending assignment with a final handoff."""
    row = await get_task(db, lead_session_id=lead_session_id, task_id=task_id)
    if row.delegator != delegator or row.recipient != recipient:
        raise ValueError(
            f"Delegation task '{task_id}' belongs to "
            f"{row.delegator} -> {row.recipient}, not {delegator} -> {recipient}."
        )
    if row.status == "completed":
        if row.result != dict(result):
            raise ValueError(
                f"Delegation task '{task_id}' is already completed with a "
                "different final result. Reject/reopen it before replacing the result."
            )
        return row
    if row.status != "pending":
        raise ValueError(f"Delegation task '{task_id}' is {row.status}, not pending.")
    now = _utcnow()
    row.status = "completed"
    row.result = dict(result)
    row.completed_at = now
    row.updated_at = now
    db.add(row)
    return row


async def completed_tasks_for_pair(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    delegator: str,
    recipient: str,
) -> list[DelegationTask]:
    rows = (
        await db.exec(
            select(DelegationTask)
            .where(
                DelegationTask.lead_session_id == lead_session_id,
                DelegationTask.delegator == delegator,
                DelegationTask.recipient == recipient,
                DelegationTask.status == "completed",
            )
            .order_by(col(DelegationTask.completed_at).desc())
        )
    ).all()
    return list(rows)


async def reopen_task(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    task_id: str,
    delegator: str,
    recipient: str,
    feedback: dict,
) -> DelegationTask:
    """Reopen a completed task after rejection and increment its attempt."""
    row = await get_task(db, lead_session_id=lead_session_id, task_id=task_id)
    if row.delegator != delegator or row.recipient != recipient:
        raise ValueError(
            f"Delegation task '{task_id}' belongs to "
            f"{row.delegator} -> {row.recipient}, not {delegator} -> {recipient}."
        )
    if row.status != "completed":
        raise ValueError(f"Delegation task '{task_id}' is {row.status}, not completed.")
    now = _utcnow()
    row.status = "pending"
    row.attempt += 1
    row.last_rejection = dict(feedback)
    row.completed_at = None
    row.final_handoff_message_id = None
    row.dispatched_at = None
    row.updated_at = now
    db.add(row)
    return row


async def release_ready_tasks(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    live_recipients: set[str],
) -> tuple[list[DelegationTask], list[DelegationTask]]:
    """Release satisfied tasks and fail tasks with terminal dependencies."""
    blocked = list(
        (
            await db.exec(
                select(DelegationTask).where(
                    DelegationTask.lead_session_id == lead_session_id,
                    DelegationTask.status == "blocked",
                )
            )
        ).all()
    )
    dependency_ids = {
        parse_task_id(task_id) for row in blocked for task_id in row.dependencies
    }
    dependency_rows: list[DelegationTask] = []
    if dependency_ids:
        dependency_rows = list(
            (
                await db.exec(
                    select(DelegationTask).where(
                        DelegationTask.lead_session_id == lead_session_id,
                        col(DelegationTask.id).in_(dependency_ids),
                    )
                )
            ).all()
        )
    statuses = {str(row.id): row.status for row in dependency_rows}
    dependencies_by_id = {str(row.id): row for row in dependency_rows}
    now = _utcnow()
    ready: list[DelegationTask] = []
    failed: list[DelegationTask] = []
    for row in blocked:
        dependency_statuses = [statuses.get(task_id) for task_id in row.dependencies]
        if any(
            status in {None, "cancelled", "failed"} for status in dependency_statuses
        ):
            row.status = "failed"
            row.result = {
                "error": "delegation dependency failed",
                "dependencies": dict(zip(row.dependencies, dependency_statuses)),
            }
            row.completed_at = now
            row.updated_at = now
            db.add(row)
            failed.append(row)
            continue
        if not all(status == "completed" for status in dependency_statuses):
            continue
        if row.recipient not in live_recipients:
            continue
        row.status = "pending"
        spec = dict(row.spec)
        spec["dependency_results"] = [
            {
                "task_id": task_id,
                "recipient": dependencies_by_id[task_id].recipient,
                "result": dependencies_by_id[task_id].result,
            }
            for task_id in row.dependencies
        ]
        row.spec = spec
        row.dispatched_at = None
        row.updated_at = now
        db.add(row)
        ready.append(row)
    return ready, failed


async def load_undelivered_tasks(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    live_recipients: set[str],
) -> list[DelegationTask]:
    if not live_recipients:
        return []
    rows = (
        await db.exec(
            select(DelegationTask)
            .where(
                DelegationTask.lead_session_id == lead_session_id,
                DelegationTask.status == "pending",
                col(DelegationTask.dispatched_at).is_(None),
                col(DelegationTask.recipient).in_(live_recipients),
            )
            .order_by(col(DelegationTask.created_at).asc())
        )
    ).all()
    return list(rows)


async def load_unacknowledged_handoffs(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    live_recipients: set[str],
) -> list[DelegationTask]:
    """Return completed tasks whose final handoff has not reached history."""
    if not live_recipients:
        return []
    rows = (
        await db.exec(
            select(DelegationTask)
            .where(
                DelegationTask.lead_session_id == lead_session_id,
                DelegationTask.status == "completed",
                col(DelegationTask.final_handoff_message_id).is_(None),
                col(DelegationTask.delegator).in_(live_recipients),
                col(DelegationTask.result).is_not(None),
            )
            .order_by(col(DelegationTask.completed_at).asc())
        )
    ).all()
    return list(rows)


async def mark_task_dispatched(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    task_id: str,
) -> None:
    row = await get_task(db, lead_session_id=lead_session_id, task_id=task_id)
    if row.status != "pending":
        return
    now = _utcnow()
    row.dispatched_at = now
    row.updated_at = now
    db.add(row)


async def attach_handoff_message(
    db: AsyncSession,
    *,
    lead_session_id: UUID,
    task_id: str,
    message_id: UUID,
) -> None:
    row = await get_task(db, lead_session_id=lead_session_id, task_id=task_id)
    if row.final_handoff_message_id == message_id:
        return
    row.final_handoff_message_id = message_id
    row.updated_at = _utcnow()
    db.add(row)
