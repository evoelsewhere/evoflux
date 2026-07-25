"""Resolve effective AIM claims and clean projections left by dead executions."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import col, select

from app.models.aim import AimClaim
from app.models.workflow import WorkflowExecution


async def effective_project_claims(db, project_id: UUID) -> list[AimClaim]:  # noqa: ANN001
    """Return only claims owned by executions this process is actively driving.

    Claims are lease-backed for crash safety, but an interrupted process can
    leave a future lease behind. Such claims must not hide runnable options for
    hours merely because their owner row still says ``running``.
    """
    from app.workflow.runner import runner

    now = datetime.now(timezone.utc)
    claims = (
        await db.exec(select(AimClaim).where(AimClaim.project_id == project_id))
    ).all()
    execution_ids = {claim.workflow_execution_id for claim in claims}
    executions: list[WorkflowExecution] = []
    if execution_ids:
        executions = (
            await db.exec(
                select(WorkflowExecution).where(
                    col(WorkflowExecution.id).in_(execution_ids)
                )
            )
        ).all()
    by_id = {execution.id: execution for execution in executions}

    effective: list[AimClaim] = []
    stale: list[AimClaim] = []
    for claim in claims:
        execution = by_id.get(claim.workflow_execution_id)
        is_live = (
            claim.lease_expires_at > now
            and execution is not None
            and execution.status in {"running", "waiting_gate"}
            and runner.is_execution_driving(claim.workflow_execution_id)
        )
        if is_live:
            effective.append(claim)
        else:
            stale.append(claim)

    for claim in stale:
        await db.delete(claim)
    if stale:
        await db.commit()
    return effective
