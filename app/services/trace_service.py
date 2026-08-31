"""EASD Development Run lifecycle, evidence matrix, and convergence gates."""

from __future__ import annotations

import hashlib
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from uuid import UUID

from loguru import logger
import yaml
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import ChatSession, _utcnow
from app.models.team import DelegationTask
from app.models.trace import (
    TraceDeviation,
    TraceEvidence,
    TracePlanRevision,
    TraceRun,
    TraceSpecRevision,
)
from app.core.metrics import TRACE_OPERATIONS
from app.services.coding_project_service import (
    get_project,
    get_project_workspaces,
    get_project_workspace_paths,
)
from app.services.trace_contracts import (
    TraceEvidenceKind,
    TraceEvidenceResult,
    TracePlan,
    TraceReviewCriterion,
    TraceRiskTier,
    TraceSpecification,
)
from app.services.easd_repository_sync import (
    enqueue_artifact,
    enqueue_artifact_update,
    enqueue_convergence,
    enqueue_revision_create,
    enqueue_revision_update,
    enqueue_run_create,
    enqueue_run_update,
    enqueue_spec_publication,
)
from app.services.easd_repository_store import (
    EasdRepositoryStore,
    EasdStoreError,
    EasdStoredRun,
    registered_run_root,
    spec_catalog_directory,
)
from app.services.easd_projection_state import (
    RUN_GENERATIONS as _REPOSITORY_RUN_GENERATIONS,
    RUN_HASHES as _REPOSITORY_RUN_HASHES,
    RUN_MISSIONS as _REPOSITORY_MISSIONS,
)

ACTIVE_RUN_STATUSES = frozenset(
    {"planning", "plan_review", "planned", "active", "reviewing", "verifying"}
)
MISSION_RUN_STATUSES = frozenset({"active", "reviewing", "verifying"})
EVIDENCE_RUN_STATUSES = frozenset({"active", "reviewing", "verifying"})
SESSION_OWNING_RUN_STATUSES = frozenset(
    {
        "authoring",
        "draft",
        "accepted",
        "planning",
        "plan_review",
        "planned",
        "active",
        "reviewing",
        "verifying",
    }
)
DEVIATION_STATUSES = frozenset({"open", "approved", "rejected", "resolved"})
TERMINAL_MISSION_STATUSES = frozenset({"completed", "cancelled"})


class TraceError(RuntimeError):
    """Base class for EASD domain failures."""


class TraceNotFound(TraceError):
    pass


class TraceConflict(TraceError):
    pass


class TraceValidationError(TraceError):
    pass


class TraceConvergenceError(TraceConflict):
    def __init__(self, reasons: list[dict[str, Any]]) -> None:
        self.reasons = reasons
        super().__init__("EASD convergence gates are not satisfied")


class TraceSessionMismatch(TraceConflict):
    def __init__(self, *, run_id: UUID, current_session_id: UUID) -> None:
        self.run_id = run_id
        self.current_session_id = current_session_id
        super().__init__("EASD run belongs to another Coding session")


@dataclass(frozen=True, slots=True)
class _TraceContext:
    run: TraceRun
    revision: TraceSpecRevision
    specification: TraceSpecification


@dataclass(frozen=True, slots=True)
class _TracePlanContext:
    run: TraceRun
    spec_revision: TraceSpecRevision
    specification: TraceSpecification
    plan_revision: TracePlanRevision
    plan: TracePlan


@dataclass(frozen=True, slots=True)
class _TraceMissionContext:
    run: TraceRun
    spec_revision: TraceSpecRevision
    specification: TraceSpecification
    plan_revision: TracePlanRevision | None
    plan: TracePlan | None


@dataclass(frozen=True, slots=True)
class EasdRuntimeContract:
    """Accepted EASD data required by one Coding runtime turn."""

    run_id: str
    run_status: str
    spec_hash: str
    plan_hash: str | None
    prompt: str
    verification_commands: tuple[str, ...]
    impact_targets: tuple[dict[str, Any], ...]
    repository_roots: tuple[dict[str, str], ...]


def _normalize_workspace(workspace: str) -> str:
    return str(Path(workspace).expanduser().resolve(strict=False))


def _uuid(value: str | UUID, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except (TypeError, ValueError) as exc:
        raise TraceValidationError(f"Invalid {label}: {value!r}") from exc


def _direct_flow_blockers(specification: TraceSpecification) -> list[str]:
    """Return deterministic reasons a specification cannot safely skip Plan."""

    if specification.delivery_flow.mode != "direct":
        return []
    blockers: list[str] = []
    if specification.risk_tier in {"cross_layer", "critical"}:
        blockers.append(f"risk:{specification.risk_tier}")
    repositories = {target.repository for target in specification.impact_targets}
    if len(repositories) != 1:
        blockers.append("multi_repository")
    modules = {
        target.module for target in specification.impact_targets if target.module
    }
    top_level_paths = {
        PurePosixPath(target.path).parts[0]
        for target in specification.impact_targets
        if PurePosixPath(target.path).parts
    }
    if len(modules) > 1 or len(top_level_paths) > 1:
        blockers.append("multi_boundary")
    plan_constraint_kinds = {"architecture", "compatibility", "security", "operational"}
    constrained = sorted(
        {constraint.kind for constraint in specification.constraints}
        & plan_constraint_kinds
    )
    blockers.extend(f"constraint:{kind}" for kind in constrained)
    return blockers


def _validate_delivery_flow(specification: TraceSpecification) -> None:
    blockers = _direct_flow_blockers(specification)
    if blockers:
        raise TraceValidationError(
            "EASD direct flow cannot skip Plan for this specification: "
            + ", ".join(blockers)
        )


def _repository_run_payload(
    run: TraceRun,
    *,
    delivery_flow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Portable run projection; machine-local scope/session fields stay local."""

    return {
        "id": str(run.id),
        "title": run.title,
        "owner_repository": Path(run.workspace).name,
        "status": run.status,
        "delivery_flow": delivery_flow,
        "risk_tier": run.risk_tier,
        "active_spec_revision_id": (
            str(run.active_spec_revision_id) if run.active_spec_revision_id else None
        ),
        "spec_catalog_index": (
            f"{spec_catalog_directory(run.title, run.id)}/index.yaml"
            if run.active_spec_revision_id
            else None
        ),
        "active_plan_revision_id": (
            str(run.active_plan_revision_id) if run.active_plan_revision_id else None
        ),
        "convergence_report": run.convergence_report,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "converged_at": run.converged_at.isoformat() if run.converged_at else None,
    }


def _repository_revision_payload(revision: TraceSpecRevision) -> dict[str, Any]:
    return serialize_revision(revision)


def _repository_plan_payload(revision: TracePlanRevision) -> dict[str, Any]:
    return serialize_plan_revision(revision)


def _queue_run_state(
    db: AsyncSession,
    run: TraceRun,
    *,
    from_status: str | None,
    event: str,
    actor: str,
    delivery_flow: dict[str, Any] | None = None,
    entity_refs: list[str] | None = None,
    event_data: dict[str, Any] | None = None,
) -> None:
    enqueue_run_update(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        run=_repository_run_payload(run, delivery_flow=delivery_flow),
        event_payload={
            "event": event,
            "from_status": from_status,
            "to_status": run.status,
            "actor": actor,
            "created_at": _utcnow().isoformat(),
            "entity_refs": entity_refs or [f"run:{run.id}"],
            **(event_data or {}),
        },
        expected_hash=_REPOSITORY_RUN_HASHES.get(run.id),
    )


async def _validate_scope(
    db: AsyncSession,
    *,
    workspace: str,
    project_id: UUID | None,
    session_id: UUID | None,
) -> None:
    if project_id is not None:
        project = await get_project(db, project_id)
        if project is None or project.kind != "coding":
            raise TraceValidationError("EASD project must be a live Coding project")
        authorized = {
            _normalize_workspace(item)
            for item in await get_project_workspace_paths(db, project_id)
        }
        if workspace not in authorized:
            raise TraceValidationError(
                "EASD workspace must belong to the selected Coding project"
            )
    if session_id is not None:
        session = await db.get(ChatSession, session_id)
        if session is None or session.mode != "coding":
            raise TraceValidationError("EASD session must be a live Coding session")
        if session.project_id != project_id:
            raise TraceValidationError("EASD session belongs to a different project")
        if (
            project_id is None
            and session.workspace
            and _normalize_workspace(session.workspace) != workspace
        ):
            raise TraceValidationError("EASD session belongs to a different workspace")


async def create_run(
    db: AsyncSession,
    *,
    workspace: str,
    title: str,
    risk_tier: TraceRiskTier,
    specification: TraceSpecification,
    authoring: dict[str, Any] | None = None,
    project_id: UUID | None = None,
    session_id: UUID | None = None,
) -> TraceRun:
    root = _normalize_workspace(workspace)
    if not Path(root).is_dir():
        raise TraceValidationError(
            "EASD workspace does not exist or is not a directory"
        )
    await _validate_scope(
        db,
        workspace=root,
        project_id=project_id,
        session_id=session_id,
    )
    normalized_title = title.strip()
    if not normalized_title:
        raise TraceValidationError("EASD run title must not be blank")
    _validate_delivery_flow(specification)
    run = TraceRun(
        project_id=project_id,
        workspace=root,
        session_id=session_id,
        title=normalized_title,
        intent={
            "title": specification.title,
            "problem": specification.problem,
            "outcome": specification.outcome,
        },
        status="draft",
        risk_tier=risk_tier,
    )
    db.add(run)
    await db.flush()
    revision = TraceSpecRevision(
        run_id=run.id,
        version=1,
        status="draft",
        spec=specification.normalized(),
        authoring=authoring,
        content_hash=specification.content_hash(),
    )
    db.add(revision)
    await db.flush()
    enqueue_run_create(
        db,
        workspace=run.workspace,
        run=_repository_run_payload(
            run,
            delivery_flow=specification.delivery_flow.model_dump(mode="json"),
        ),
        intent=run.intent,
    )
    enqueue_revision_create(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        kind="specifications",
        version=revision.version,
        revision=_repository_revision_payload(revision),
    )
    logger.info(
        "trace_run_created run_id={} project_id={} risk_tier={} criteria={}",
        run.id,
        project_id,
        risk_tier,
        len(specification.criteria),
    )
    TRACE_OPERATIONS.labels(
        operation="run_create", status="ok", risk_tier=risk_tier
    ).inc()
    return run


async def create_intent_run(
    db: AsyncSession,
    *,
    workspace: str,
    title: str,
    problem: str,
    outcome: str = "",
    project_id: UUID | None = None,
    session_id: UUID | None = None,
) -> TraceRun:
    """Create a run from minimal user Intent without inventing a specification."""

    root = _normalize_workspace(workspace)
    if not Path(root).is_dir():
        raise TraceValidationError(
            "EASD workspace does not exist or is not a directory"
        )
    await _validate_scope(
        db,
        workspace=root,
        project_id=project_id,
        session_id=session_id,
    )
    normalized_title = title.strip()
    normalized_problem = problem.strip()
    normalized_outcome = outcome.strip()
    if not normalized_title or not normalized_problem:
        raise TraceValidationError("EASD Intent requires title and problem")
    run = TraceRun(
        project_id=project_id,
        workspace=root,
        session_id=session_id,
        title=normalized_title,
        intent={
            "title": normalized_title,
            "problem": normalized_problem,
            "outcome": normalized_outcome,
        },
        status="intent",
        risk_tier="standard",
    )
    db.add(run)
    await db.flush()
    enqueue_run_create(
        db,
        workspace=run.workspace,
        run=_repository_run_payload(run),
        intent=run.intent,
    )
    logger.info(
        "trace_intent_created run_id={} project_id={} outcome_provided={}",
        run.id,
        project_id,
        bool(normalized_outcome),
    )
    TRACE_OPERATIONS.labels(
        operation="intent_create", status="ok", risk_tier="standard"
    ).inc()
    return run


async def get_run(db: AsyncSession, run_id: str | UUID) -> TraceRun:
    normalized_id = _uuid(run_id, label="EASD run ID")
    root = registered_run_root(normalized_id)
    if root is not None and not db.in_transaction():
        try:
            snapshot = await asyncio.to_thread(
                EasdRepositoryStore(root).load_run, normalized_id
            )
        except EasdStoreError as exc:
            raise TraceConflict(
                "EASD repository state is unavailable; reload after resolving the "
                f"repository conflict: {exc}"
            ) from exc
        await _materialize_repository_snapshots(db, [snapshot], project_id=None)
    row = await db.get(TraceRun, normalized_id)
    if row is None:
        raise TraceNotFound(f"EASD run '{run_id}' was not found")
    return row


def _repository_snapshots(roots: list[str]) -> list[EasdStoredRun]:
    snapshots: list[EasdStoredRun] = []
    for root in dict.fromkeys(roots):
        try:
            snapshots.extend(EasdRepositoryStore(root).list_runs())
        except EasdStoreError:
            continue
    return snapshots


def _repository_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TraceValidationError(
                f"Invalid repository EASD timestamp: {value}"
            ) from exc
    raise TraceValidationError("Repository EASD timestamps must be RFC3339 strings")


def _repository_bundles(
    snapshots: list[EasdStoredRun],
) -> list[
    tuple[
        EasdStoredRun,
        dict[str, Any] | None,
        list[dict],
        list[dict],
        list[dict],
        list[dict],
        list[dict],
    ]
]:
    bundles = []
    for stored in snapshots:
        intent: dict[str, Any] | None = None
        intent_path = stored.directory / "intent.yaml"
        if intent_path.is_file() and not intent_path.is_symlink():
            raw = yaml.safe_load(intent_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                intent = raw
        store = EasdRepositoryStore(stored.root)
        bundles.append(
            (
                stored,
                intent,
                store.read_revisions(stored.run["id"], "specifications"),
                store.read_revisions(stored.run["id"], "plans"),
                store.read_artifacts(stored.run["id"], "missions"),
                store.read_artifacts(stored.run["id"], "evidence"),
                store.read_artifacts(stored.run["id"], "deviations"),
            )
        )
    return bundles


async def _materialize_repository_snapshots(
    db: AsyncSession,
    snapshots: list[EasdStoredRun],
    *,
    project_id: UUID | None,
) -> None:
    """Rebuild the local runtime index from repository-owned documents."""

    bundles = await asyncio.to_thread(_repository_bundles, snapshots)
    for (
        stored,
        raw_intent,
        stored_specs,
        stored_plans,
        stored_missions,
        stored_evidence,
        stored_deviations,
    ) in bundles:
        payload = stored.run
        run_id = _uuid(str(payload.get("id")), label="repository EASD run ID")
        _REPOSITORY_RUN_HASHES[run_id] = str(payload.get("document_hash") or "")
        _REPOSITORY_RUN_GENERATIONS[run_id] = int(payload.get("store_generation") or 0)
        _REPOSITORY_MISSIONS[run_id] = stored_missions
        intent_payload: dict[str, Any] | None = None
        if isinstance(raw_intent, dict):
            intent_payload = {
                key: raw_intent.get(key)
                for key in ("title", "problem", "outcome")
                if key in raw_intent
            }
        existing = await db.get(TraceRun, run_id)
        values = {
            "project_id": (
                project_id
                if project_id is not None
                else existing.project_id
                if existing is not None
                else None
            ),
            "workspace": str(stored.root),
            "title": str(payload.get("title") or "Untitled EASD run"),
            "intent": intent_payload,
            "status": str(payload.get("status") or "intent"),
            "risk_tier": str(payload.get("risk_tier") or "standard"),
            "active_spec_revision_id": (
                _uuid(
                    str(payload["active_spec_revision_id"]),
                    label="active repository spec revision",
                )
                if payload.get("active_spec_revision_id")
                else None
            ),
            "active_plan_revision_id": (
                _uuid(
                    str(payload["active_plan_revision_id"]),
                    label="active repository plan revision",
                )
                if payload.get("active_plan_revision_id")
                else None
            ),
            "convergence_report": payload.get("convergence_report"),
            "created_at": _repository_datetime(payload.get("created_at")) or _utcnow(),
            "updated_at": _repository_datetime(payload.get("updated_at")) or _utcnow(),
            "converged_at": _repository_datetime(payload.get("converged_at")),
        }
        if existing is None:
            existing = TraceRun.model_validate({"id": run_id, **values})
        else:
            local_session_id = existing.session_id
            for key, value in values.items():
                setattr(existing, key, value)
            existing.session_id = local_session_id
        db.add(existing)

        for raw in stored_specs:
            revision_id = _uuid(str(raw.get("id")), label="repository spec revision")
            row = await db.get(TraceSpecRevision, revision_id)
            values = {
                key: raw.get(key)
                for key in (
                    "run_id",
                    "version",
                    "status",
                    "spec",
                    "authoring",
                    "content_hash",
                    "created_at",
                    "accepted_at",
                )
            }
            values["created_at"] = _repository_datetime(values["created_at"])
            values["accepted_at"] = _repository_datetime(values["accepted_at"])
            values["run_id"] = run_id
            if (
                values["status"] == "accepted"
                and payload.get("active_spec_revision_id")
                and revision_id
                != _uuid(
                    str(payload["active_spec_revision_id"]),
                    label="active repository spec revision",
                )
            ):
                values["status"] = "superseded"
            if row is None:
                row = TraceSpecRevision.model_validate({"id": revision_id, **values})
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.add(row)
        for raw in stored_evidence:
            evidence_id = _uuid(str(raw.get("id")), label="repository evidence")
            row = await db.get(TraceEvidence, evidence_id)
            delegation_task_id = raw.get("delegation_task_id")
            if (
                delegation_task_id is not None
                and await db.get(
                    DelegationTask, _uuid(str(delegation_task_id), label="mission ID")
                )
                is None
            ):
                delegation_task_id = None
            values = {
                "run_id": run_id,
                "delegation_task_id": delegation_task_id,
                **{
                    key: raw.get(key)
                    for key in (
                        "spec_hash",
                        "criterion_ids",
                        "producer",
                        "kind",
                        "result",
                        "summary",
                        "revision",
                        "artifact_hash",
                        "payload",
                        "source_key",
                        "created_at",
                    )
                },
            }
            values["created_at"] = _repository_datetime(values["created_at"])
            if row is None:
                row = TraceEvidence.model_validate({"id": evidence_id, **values})
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.add(row)
        for raw in stored_deviations:
            deviation_id = _uuid(str(raw.get("id")), label="repository deviation")
            row = await db.get(TraceDeviation, deviation_id)
            delegation_task_id = raw.get("delegation_task_id")
            if (
                delegation_task_id is not None
                and await db.get(
                    DelegationTask, _uuid(str(delegation_task_id), label="mission ID")
                )
                is None
            ):
                delegation_task_id = None
            values = {
                "run_id": run_id,
                "delegation_task_id": delegation_task_id,
                **{
                    key: raw.get(key)
                    for key in (
                        "spec_hash",
                        "criterion_id",
                        "status",
                        "blocking",
                        "description",
                        "proposed_change",
                        "resolution",
                        "resolved_spec_hash",
                        "created_at",
                        "updated_at",
                        "resolved_at",
                    )
                },
            }
            for key in ("created_at", "updated_at", "resolved_at"):
                values[key] = _repository_datetime(values[key])
            if row is None:
                row = TraceDeviation.model_validate({"id": deviation_id, **values})
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.add(row)
        for raw in stored_plans:
            revision_id = _uuid(str(raw.get("id")), label="repository plan revision")
            row = await db.get(TracePlanRevision, revision_id)
            values = {
                key: raw.get(key)
                for key in (
                    "run_id",
                    "version",
                    "status",
                    "spec_hash",
                    "plan",
                    "authoring",
                    "content_hash",
                    "created_at",
                    "accepted_at",
                )
            }
            values["created_at"] = _repository_datetime(values["created_at"])
            values["accepted_at"] = _repository_datetime(values["accepted_at"])
            values["run_id"] = run_id
            if values["status"] == "accepted" and (
                not payload.get("active_plan_revision_id")
                or revision_id
                != _uuid(
                    str(payload["active_plan_revision_id"]),
                    label="active repository plan revision",
                )
            ):
                values["status"] = "superseded"
            if row is None:
                row = TracePlanRevision.model_validate({"id": revision_id, **values})
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.add(row)
    await db.flush()


async def list_runs(
    db: AsyncSession,
    *,
    workspace: str | None = None,
    project_id: UUID | None = None,
    limit: int = 100,
) -> list[TraceRun]:
    roots: list[str] = []
    if workspace is not None:
        roots = [_normalize_workspace(workspace)]
    elif project_id is not None:
        roots = [
            _normalize_workspace(item)
            for item in await get_project_workspace_paths(db, project_id)
        ]
        # End the read transaction before repository filesystem scans.
        await db.rollback()
    snapshots = await asyncio.to_thread(_repository_snapshots, roots)
    if snapshots:
        await _materialize_repository_snapshots(
            db,
            snapshots,
            project_id=project_id,
        )
    stmt = select(TraceRun)
    if workspace is not None:
        stmt = stmt.where(TraceRun.workspace == _normalize_workspace(workspace))
    if project_id is not None:
        stmt = stmt.where(TraceRun.project_id == project_id)
    stmt = stmt.order_by(col(TraceRun.updated_at).desc()).limit(limit)
    return list((await db.exec(stmt)).all())


async def create_revision(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    specification: TraceSpecification,
    authoring: dict[str, Any] | None = None,
) -> TraceSpecRevision:
    run = await get_run(db, run_id)
    from_status = run.status
    if run.status in {"converged", "cancelled"}:
        raise TraceConflict(f"Cannot revise a {run.status} EASD run")
    await _validate_spec_repository_scope(
        db,
        run=run,
        specification=specification,
    )
    _validate_delivery_flow(specification)
    drafts = list(
        (
            await db.exec(
                select(TraceSpecRevision)
                .where(
                    TraceSpecRevision.run_id == run.id,
                    TraceSpecRevision.status == "draft",
                )
                .order_by(col(TraceSpecRevision.version).desc())
            )
        ).all()
    )
    content_hash = specification.content_hash()
    if drafts and drafts[0].content_hash == content_hash:
        return drafts[0]
    latest_version = (
        await db.exec(
            select(TraceSpecRevision.version)
            .where(TraceSpecRevision.run_id == run.id)
            .order_by(col(TraceSpecRevision.version).desc())
        )
    ).first()
    revision = TraceSpecRevision(
        run_id=run.id,
        version=int(latest_version or 0) + 1,
        status="draft",
        spec=specification.normalized(),
        authoring=authoring,
        content_hash=content_hash,
    )
    for draft in drafts:
        draft.status = "superseded"
        db.add(draft)
    db.add(revision)
    if run.status in {
        "intent",
        "authoring",
        "draft",
        "accepted",
        "planning",
        "plan_review",
        "planned",
    }:
        run.status = "draft"
        run.active_plan_revision_id = None
        run.title = specification.title
        run.intent = {
            "title": specification.title,
            "problem": specification.problem,
            "outcome": specification.outcome,
        }
    run.risk_tier = specification.risk_tier
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    for draft in drafts:
        enqueue_revision_update(
            db,
            workspace=run.workspace,
            run_id=str(run.id),
            kind="specifications",
            version=draft.version,
            revision=_repository_revision_payload(draft),
        )
    enqueue_revision_create(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        kind="specifications",
        version=revision.version,
        revision=_repository_revision_payload(revision),
    )
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="specification_draft_created",
        actor="agent" if authoring else "human",
        delivery_flow=specification.delivery_flow.model_dump(mode="json"),
        entity_refs=[f"run:{run.id}", f"spec:{revision.id}"],
        event_data={
            "revision_id": str(revision.id),
            "version": revision.version,
            "content_hash": revision.content_hash,
        },
    )
    return revision


async def _validate_spec_repository_scope(
    db: AsyncSession,
    *,
    run: TraceRun,
    specification: TraceSpecification,
) -> None:
    allowed = {item["repository"] for item in await _repository_roots_for_run(db, run)}
    unknown = sorted(
        {
            target.repository
            for target in specification.impact_targets
            if target.repository not in allowed
        }
    )
    if unknown:
        raise TraceValidationError(
            "EASD specification targets repositories outside the run scope: "
            + ", ".join(unknown)
        )


async def submit_authored_specification(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
    specification: TraceSpecification,
    authoring: dict[str, Any],
) -> TraceSpecRevision:
    """Persist an agent-authored draft and move the run to human review."""

    run = await get_run(db, run_id)
    await _session_for_run(db, run, session_id)
    if run.status not in {"authoring", "draft"}:
        raise TraceConflict(
            f"Cannot submit a specification while EASD run is {run.status}"
        )
    intent = run.intent if isinstance(run.intent, dict) else {}
    if specification.title.strip() != run.title:
        raise TraceValidationError(
            "Submitted specification title must match the persisted EASD Intent"
        )
    if intent.get("problem") and not specification.problem.strip():
        raise TraceValidationError(
            "Submitted specification must address the Intent problem"
        )
    await _validate_spec_repository_scope(
        db,
        run=run,
        specification=specification,
    )
    if run.status == "draft":
        latest_draft = (
            await db.exec(
                select(TraceSpecRevision)
                .where(
                    TraceSpecRevision.run_id == run.id,
                    TraceSpecRevision.status == "draft",
                )
                .order_by(col(TraceSpecRevision.version).desc())
            )
        ).first()
        if (
            latest_draft is not None
            and latest_draft.content_hash == specification.content_hash()
        ):
            return latest_draft
        raise TraceConflict(
            "Specification draft is already awaiting user review; "
            "agent overwrite refused"
        )
    revision = await create_revision(
        db,
        run_id=run.id,
        specification=specification,
        authoring=authoring,
    )
    run.status = "draft"
    run.risk_tier = specification.risk_tier
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    logger.info(
        "trace_agent_spec_submitted run_id={} revision_id={} spec_hash={}",
        run.id,
        revision.id,
        revision.content_hash[:12],
    )
    TRACE_OPERATIONS.labels(
        operation="agent_spec_submit",
        status="ok",
        risk_tier=run.risk_tier,
    ).inc()
    return revision


async def _revision_for_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    revision_id: str | UUID,
) -> TraceSpecRevision:
    row = await db.get(
        TraceSpecRevision, _uuid(revision_id, label="EASD spec revision ID")
    )
    if row is None or row.run_id != run_id:
        raise TraceNotFound("EASD spec revision was not found in this run")
    return row


async def accept_revision(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    revision_id: str | UUID,
    expected_hash: str,
) -> TraceSpecRevision:
    run = await get_run(db, run_id)
    from_status = run.status
    revision = await _revision_for_run(db, run_id=run.id, revision_id=revision_id)
    if revision.content_hash != expected_hash:
        raise TraceConflict("EASD spec hash changed before acceptance")
    if revision.status == "accepted" and run.active_spec_revision_id == revision.id:
        enqueue_spec_publication(
            db,
            workspace=run.workspace,
            run_id=str(run.id),
            revision=_repository_revision_payload(revision),
        )
        return revision
    if revision.status != "draft":
        raise TraceConflict(f"Cannot accept a {revision.status} spec revision")

    previous = list(
        (
            await db.exec(
                select(TraceSpecRevision).where(
                    TraceSpecRevision.run_id == run.id,
                    TraceSpecRevision.status == "accepted",
                )
            )
        ).all()
    )
    now = _utcnow()
    for item in previous:
        item.status = "superseded"
        db.add(item)
    previous_plans = list(
        (
            await db.exec(
                select(TracePlanRevision).where(
                    TracePlanRevision.run_id == run.id,
                    col(TracePlanRevision.status).in_({"draft", "accepted"}),
                )
            )
        ).all()
    )
    for item in previous_plans:
        item.status = "superseded"
        db.add(item)
    revision.status = "accepted"
    revision.accepted_at = now
    run.active_spec_revision_id = revision.id
    run.active_plan_revision_id = None
    run.status = "accepted"
    run.convergence_report = None
    run.converged_at = None
    run.updated_at = now
    db.add(revision)
    db.add(run)
    await db.flush()
    for item in previous_plans:
        if item.accepted_at is None:
            enqueue_revision_update(
                db,
                workspace=run.workspace,
                run_id=str(run.id),
                kind="plans",
                version=item.version,
                revision=_repository_plan_payload(item),
            )
    enqueue_revision_update(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        kind="specifications",
        version=revision.version,
        revision=_repository_revision_payload(revision),
    )
    accepted_specification = TraceSpecification.model_validate(revision.spec)
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="specification_accepted",
        actor="human",
        delivery_flow=accepted_specification.delivery_flow.model_dump(mode="json"),
        entity_refs=[f"run:{run.id}", f"spec:{revision.id}"],
        event_data={
            "revision_id": str(revision.id),
            "version": revision.version,
            "content_hash": revision.content_hash,
        },
    )
    logger.info(
        "trace_spec_accepted run_id={} version={} spec_hash={}",
        run.id,
        revision.version,
        revision.content_hash[:12],
    )
    TRACE_OPERATIONS.labels(
        operation="spec_accept", status="ok", risk_tier=run.risk_tier
    ).inc()
    return revision


async def _plan_revision_for_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    revision_id: str | UUID,
) -> TracePlanRevision:
    row = await db.get(
        TracePlanRevision, _uuid(revision_id, label="EASD plan revision ID")
    )
    if row is None or row.run_id != run_id:
        raise TraceNotFound("EASD plan revision was not found in this run")
    return row


async def _validate_plan_contract(
    db: AsyncSession,
    *,
    context: _TraceContext,
    plan: TracePlan,
) -> None:
    if plan.spec_hash != context.revision.content_hash:
        raise TraceConflict("EASD plan references a stale specification hash")
    known_criteria = context.specification.criterion_ids()
    unknown = sorted(plan.criterion_ids() - known_criteria)
    if unknown:
        raise TraceValidationError(
            "EASD plan references unknown acceptance criteria: " + ", ".join(unknown)
        )
    required = {
        criterion.id
        for criterion in context.specification.criteria
        if criterion.required
    }
    uncovered = sorted(required - plan.implementation_criterion_ids())
    if uncovered:
        raise TraceValidationError(
            "EASD plan leaves required criteria without implementation ownership: "
            + ", ".join(uncovered)
        )
    high_risk = context.run.risk_tier in {"cross_layer", "critical"}
    review_missions = [mission for mission in plan.missions if mission.kind == "review"]
    if high_risk and not plan.review_required:
        raise TraceValidationError(
            "Cross-layer and critical EASD plans must require independent review"
        )
    if not review_missions:
        raise TraceValidationError("Every EASD plan requires a review mission")
    verification_missions = [
        mission for mission in plan.missions if mission.kind == "verification"
    ]
    planned_verification_commands = {
        command
        for mission in verification_missions
        for command in mission.verification_commands
    }
    missing_verification_commands = sorted(
        set(context.specification.verification_commands) - planned_verification_commands
    )
    if missing_verification_commands:
        raise TraceValidationError(
            "EASD plan must assign every accepted Proof command to a verification "
            "mission: " + ", ".join(missing_verification_commands)
        )

    allowed_repositories = {
        target.repository for target in context.specification.impact_targets
    }
    accepted_targets = [
        (target.repository, _normalized_spec_path(target.path))
        for target in context.specification.impact_targets
    ]
    for mission in plan.missions:
        unknown_repositories = sorted(
            set(mission.target_repositories) - allowed_repositories
        )
        if unknown_repositories:
            raise TraceValidationError(
                f"EASD plan mission {mission.id} targets repositories outside "
                "the run scope: " + ", ".join(unknown_repositories)
            )
        if mission.kind in {"implementation", "integration"} and (
            not mission.target_repositories or not mission.target_paths
        ):
            raise TraceValidationError(
                f"EASD plan mission {mission.id} requires repository and path scope"
            )
        for target_path in mission.target_paths:
            normalized_path = _normalized_spec_path(target_path)
            if not any(
                (
                    not mission.target_repositories
                    or repository in mission.target_repositories
                )
                and _path_is_within_any(normalized_path, [accepted_path])
                for repository, accepted_path in accepted_targets
            ):
                raise TraceValidationError(
                    f"EASD plan mission {mission.id} target path exceeds the "
                    f"accepted Scope: {target_path}"
                )


async def create_plan_revision(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    plan: TracePlan,
    authoring: dict[str, Any] | None = None,
) -> TracePlanRevision:
    context = await active_context(db, run_id)
    run = context.run
    from_status = run.status
    if run.status not in {"accepted", "planning", "plan_review", "planned"}:
        raise TraceConflict(f"Cannot revise a plan while EASD run is {run.status}")
    await _validate_plan_contract(db, context=context, plan=plan)
    drafts = list(
        (
            await db.exec(
                select(TracePlanRevision)
                .where(
                    TracePlanRevision.run_id == run.id,
                    TracePlanRevision.status == "draft",
                )
                .order_by(col(TracePlanRevision.version).desc())
            )
        ).all()
    )
    content_hash = plan.content_hash()
    if drafts and drafts[0].content_hash == content_hash:
        return drafts[0]
    latest_version = (
        await db.exec(
            select(TracePlanRevision.version)
            .where(TracePlanRevision.run_id == run.id)
            .order_by(col(TracePlanRevision.version).desc())
        )
    ).first()
    revision = TracePlanRevision(
        run_id=run.id,
        version=int(latest_version or 0) + 1,
        status="draft",
        spec_hash=context.revision.content_hash,
        plan=plan.normalized(),
        authoring=authoring,
        content_hash=content_hash,
    )
    for draft in drafts:
        draft.status = "superseded"
        db.add(draft)
    db.add(revision)
    run.active_plan_revision_id = None
    run.status = "plan_review"
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    for draft in drafts:
        enqueue_revision_update(
            db,
            workspace=run.workspace,
            run_id=str(run.id),
            kind="plans",
            version=draft.version,
            revision=_repository_plan_payload(draft),
        )
    enqueue_revision_create(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        kind="plans",
        version=revision.version,
        revision=_repository_plan_payload(revision),
    )
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="plan_draft_created",
        actor="agent" if authoring else "human",
        delivery_flow=context.specification.delivery_flow.model_dump(mode="json"),
        entity_refs=[f"run:{run.id}", f"plan:{revision.id}"],
        event_data={
            "revision_id": str(revision.id),
            "version": revision.version,
            "content_hash": revision.content_hash,
            "spec_hash": revision.spec_hash,
        },
    )
    return revision


async def submit_authored_plan(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
    plan: TracePlan,
    authoring: dict[str, Any],
) -> TracePlanRevision:
    run = await get_run(db, run_id)
    await _session_for_run(db, run, session_id)
    if run.status not in {"planning", "plan_review"}:
        raise TraceConflict(f"Cannot submit a plan while EASD run is {run.status}")
    if run.status == "plan_review":
        latest_draft = (
            await db.exec(
                select(TracePlanRevision)
                .where(
                    TracePlanRevision.run_id == run.id,
                    TracePlanRevision.status == "draft",
                )
                .order_by(col(TracePlanRevision.version).desc())
            )
        ).first()
        if (
            latest_draft is not None
            and latest_draft.content_hash == plan.content_hash()
        ):
            return latest_draft
        raise TraceConflict(
            "Plan draft is already awaiting user review; agent overwrite refused"
        )
    revision = await create_plan_revision(
        db,
        run_id=run.id,
        plan=plan,
        authoring=authoring,
    )
    logger.info(
        "trace_agent_plan_submitted run_id={} revision_id={} plan_hash={}",
        run.id,
        revision.id,
        revision.content_hash[:12],
    )
    TRACE_OPERATIONS.labels(
        operation="agent_plan_submit",
        status="ok",
        risk_tier=run.risk_tier,
    ).inc()
    return revision


async def accept_plan_revision(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    revision_id: str | UUID,
    expected_hash: str,
) -> TracePlanRevision:
    context = await active_context(db, run_id)
    run = context.run
    from_status = run.status
    revision = await _plan_revision_for_run(
        db,
        run_id=run.id,
        revision_id=revision_id,
    )
    if revision.content_hash != expected_hash:
        raise TraceConflict("EASD plan hash changed before acceptance")
    if revision.spec_hash != context.revision.content_hash:
        raise TraceConflict("EASD plan was authored for another spec hash")
    if revision.status == "accepted" and run.active_plan_revision_id == revision.id:
        return revision
    if run.status != "plan_review" or revision.status != "draft":
        raise TraceConflict(
            f"Cannot accept a {revision.status} plan while run is {run.status}"
        )
    previous = list(
        (
            await db.exec(
                select(TracePlanRevision).where(
                    TracePlanRevision.run_id == run.id,
                    TracePlanRevision.status == "accepted",
                )
            )
        ).all()
    )
    now = _utcnow()
    for item in previous:
        item.status = "superseded"
        db.add(item)
    revision.status = "accepted"
    revision.accepted_at = now
    run.active_plan_revision_id = revision.id
    run.status = "planned"
    run.updated_at = now
    db.add(revision)
    db.add(run)
    await db.flush()
    enqueue_revision_update(
        db,
        workspace=run.workspace,
        run_id=str(run.id),
        kind="plans",
        version=revision.version,
        revision=_repository_plan_payload(revision),
    )
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="plan_accepted",
        actor="human",
        delivery_flow=context.specification.delivery_flow.model_dump(mode="json"),
        entity_refs=[f"run:{run.id}", f"plan:{revision.id}"],
        event_data={
            "revision_id": str(revision.id),
            "version": revision.version,
            "content_hash": revision.content_hash,
            "spec_hash": revision.spec_hash,
        },
    )
    logger.info(
        "trace_plan_accepted run_id={} version={} plan_hash={}",
        run.id,
        revision.version,
        revision.content_hash[:12],
    )
    TRACE_OPERATIONS.labels(
        operation="plan_accept", status="ok", risk_tier=run.risk_tier
    ).inc()
    return revision


async def _resolve_target_session(
    db: AsyncSession, run: TraceRun, session_id: str | UUID
) -> ChatSession:
    session = await db.get(ChatSession, _uuid(session_id, label="session_id"))
    if session is None or session.mode != "coding" or not session.workspace:
        raise TraceValidationError("EASD run requires a Coding session")
    if run.project_id is not None:
        if session.project_id != run.project_id:
            raise TraceValidationError("Coding session belongs to another EASD project")
    elif Path(session.workspace).resolve() != Path(run.workspace).resolve():
        raise TraceValidationError("Coding session belongs to another EASD workspace")

    # Auto-rebind when the old session has been deleted from the database.
    # We do NOT auto-rebind based on staleness — that requires human judgment.
    if run.session_id is not None and run.session_id != session.id:
        old_session = await db.get(ChatSession, run.session_id)
        if old_session is None:
            logger.info(
                "easd_run_auto_rebind run_id={} old_session_deleted new_session={}",
                run.id,
                session.id,
            )
            run.session_id = session.id
            run.updated_at = _utcnow()
            db.add(run)

    return session


async def _session_for_run(
    db: AsyncSession, run: TraceRun, session_id: str | UUID
) -> ChatSession:
    session = await _resolve_target_session(db, run, session_id)
    if run.session_id is not None and run.session_id != session.id:
        raise TraceSessionMismatch(run_id=run.id, current_session_id=run.session_id)
    return session


async def rebind_run_to_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
    force: bool = False,
) -> TraceRun:
    """Manually rebind an EASD run to a different Coding session.

    By default only allows rebinding when the old session is inactive.
    Pass ``force=True`` to rebind even when the old session is still active
    (requires the run to be in a non-terminal state).
    """
    run = await get_run(db, run_id)
    if run.status in {"converged", "archived", "failed", "cancelled"}:
        raise TraceConflict(
            f"Cannot rebind a terminal EASD run in status '{run.status}'"
        )

    session = await db.get(ChatSession, _uuid(session_id, label="session_id"))
    if session is None or session.mode != "coding" or not session.workspace:
        raise TraceValidationError("Target must be a Coding session")

    if (
        session.workspace
        and run.workspace
        and Path(session.workspace).resolve() != Path(run.workspace).resolve()
    ):
        raise TraceValidationError("Session belongs to a different workspace")

    if run.session_id == session.id:
        return run  # Already bound to this session.

    old_session_id = run.session_id
    if not force and old_session_id is not None:
        old_session = await db.get(ChatSession, old_session_id)
        if old_session is not None:
            raise TraceConflict(
                "Old session still exists. Use force=True to rebind anyway."
            )

    run.session_id = session.id
    run.updated_at = _utcnow()
    db.add(run)
    _queue_run_state(
        db,
        run,
        from_status=run.status,
        event="run_rebounded",
        actor="human",
    )
    logger.info(
        "easd_run_rebound run_id={} old_session={} new_session={}",
        run.id,
        old_session_id,
        session.id,
    )
    return run


async def start_plan_authoring_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Atomically bind an accepted spec to an idle Coding chat for planning."""

    context = await active_context(db, run_id)
    run = context.run
    from_status = run.status
    if context.specification.delivery_flow.mode != "planned":
        raise TraceConflict(
            "This accepted EASD specification uses direct flow and skips Plan"
        )
    session = await _session_for_run(db, run, session_id)
    if run.status == "planning":
        return run
    if run.status != "accepted":
        raise TraceConflict(f"Cannot plan while EASD run is {run.status}")
    if run.session_id is not None and run.session_id != session.id:
        raise TraceConflict("EASD run is already linked to another Coding session")
    existing = (
        await db.exec(
            select(TraceRun).where(
                TraceRun.session_id == session.id,
                col(TraceRun.status).in_(SESSION_OWNING_RUN_STATUSES),
                TraceRun.id != run.id,
            )
        )
    ).first()
    if existing is not None:
        raise TraceConflict("Another EASD run already owns this Coding session")
    run.session_id = session.id
    run.status = "planning"
    run.updated_at = _utcnow()
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TraceConflict("Another EASD run acquired this Coding session") from exc
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="planning_started",
        actor="human",
        delivery_flow=context.specification.delivery_flow.model_dump(mode="json"),
    )
    logger.info("trace_plan_started run_id={} session_id={}", run.id, session.id)
    TRACE_OPERATIONS.labels(
        operation="plan_start", status="ok", risk_tier=run.risk_tier
    ).inc()
    return run


async def retry_plan_authoring_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Retry Plan authoring without overwriting the persisted Plan draft."""

    context = await active_context(db, run_id)
    run = context.run
    if context.specification.delivery_flow.mode != "planned":
        raise TraceConflict("This accepted EASD specification uses direct flow")
    session = await _session_for_run(db, run, session_id)
    if run.status == "planning":
        return run
    if run.status != "plan_review":
        raise TraceConflict(f"Cannot retry planning while EASD run is {run.status}")
    from_status = run.status
    run.status = "planning"
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="planning_retried",
        actor="human",
        delivery_flow=context.specification.delivery_flow.model_dump(mode="json"),
    )
    logger.info("trace_plan_retried run_id={} session_id={}", run.id, session.id)
    TRACE_OPERATIONS.labels(
        operation="plan_retry", status="ok", risk_tier=run.risk_tier
    ).inc()
    return run


async def start_run_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Atomically bind and activate one approved-plan run in a Coding session."""
    spec_context = await active_context(db, run_id)
    run = spec_context.run
    from_status = run.status
    direct = spec_context.specification.delivery_flow.mode == "direct"
    if direct:
        start_status = "accepted"
    else:
        await active_plan_context(db, run_id)
        start_status = "planned"
    session = await _session_for_run(db, run, session_id)
    if run.status in {"active", "reviewing", "verifying"}:
        return run
    if run.status != start_status:
        raise TraceConflict(f"Cannot start a {run.status} EASD run in chat")
    if run.session_id is not None and run.session_id != session.id:
        raise TraceConflict("EASD run is already linked to another Coding session")
    existing = (
        await db.exec(
            select(TraceRun).where(
                TraceRun.session_id == session.id,
                col(TraceRun.status).in_(SESSION_OWNING_RUN_STATUSES),
                TraceRun.id != run.id,
            )
        )
    ).first()
    if existing is not None:
        raise TraceConflict(
            "Another EASD run is already active for this Coding session"
        )
    run.session_id = session.id
    run.status = "active"
    run.updated_at = _utcnow()
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TraceConflict(
            "Another EASD run became active for this Coding session"
        ) from exc
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="implementation_started",
        actor="human",
        delivery_flow=spec_context.specification.delivery_flow.model_dump(mode="json"),
    )
    logger.info("trace_run_started_in_chat run_id={} session_id={}", run.id, session.id)
    TRACE_OPERATIONS.labels(
        operation="chat_start", status="ok", risk_tier=run.risk_tier
    ).inc()
    return run


async def start_spec_authoring_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Atomically bind minimal Intent to a Coding chat for agent authoring."""

    run = await get_run(db, run_id)
    from_status = run.status
    session = await _session_for_run(db, run, session_id)
    if run.status == "authoring":
        return run
    if run.status != "intent":
        raise TraceConflict(
            f"Cannot draft a specification while EASD run is {run.status}"
        )
    if run.session_id is not None and run.session_id != session.id:
        raise TraceConflict("EASD run is already linked to another Coding session")
    existing = (
        await db.exec(
            select(TraceRun).where(
                TraceRun.session_id == session.id,
                col(TraceRun.status).in_(SESSION_OWNING_RUN_STATUSES),
                TraceRun.id != run.id,
            )
        )
    ).first()
    if existing is not None:
        raise TraceConflict("Another EASD run already owns this Coding session")
    run.session_id = session.id
    run.status = "authoring"
    run.updated_at = _utcnow()
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TraceConflict("Another EASD run acquired this Coding session") from exc
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="specification_authoring_started",
        actor="human",
    )
    logger.info(
        "trace_spec_authoring_started run_id={} session_id={}", run.id, session.id
    )
    TRACE_OPERATIONS.labels(
        operation="spec_authoring_start",
        status="ok",
        risk_tier=run.risk_tier,
    ).inc()
    return run


async def retry_spec_authoring_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Retry specification authoring without overwriting the persisted draft."""

    run = await get_run(db, run_id)
    session = await _session_for_run(db, run, session_id)
    if run.status == "authoring":
        return run
    if run.status != "draft":
        raise TraceConflict(
            f"Cannot retry specification authoring while EASD run is {run.status}"
        )
    from_status = run.status
    run.status = "authoring"
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="specification_authoring_retried",
        actor="human",
    )
    logger.info(
        "trace_spec_authoring_retried run_id={} session_id={}", run.id, session.id
    )
    TRACE_OPERATIONS.labels(
        operation="spec_authoring_retry",
        status="ok",
        risk_tier=run.risk_tier,
    ).inc()
    return run


async def _nonterminal_missions(
    db: AsyncSession,
    *,
    run_id: UUID,
) -> list[DelegationTask]:
    return list(
        (
            await db.exec(
                select(DelegationTask).where(
                    DelegationTask.trace_run_id == run_id,
                    col(DelegationTask.status).not_in(TERMINAL_MISSION_STATUSES),
                )
            )
        ).all()
    )


async def start_review_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Move completed implementation work into explicit review."""

    spec_context = await active_context(db, run_id)
    run = spec_context.run
    if spec_context.specification.delivery_flow.mode == "planned":
        await active_plan_context(db, run_id)
    from_status = run.status
    await _session_for_run(db, run, session_id)
    if run.status == "reviewing":
        return run
    if run.status != "active":
        raise TraceConflict(f"Cannot review while EASD run is {run.status}")
    nonterminal = await _nonterminal_missions(db, run_id=run.id)
    if nonterminal:
        raise TraceConflict(
            "Cannot start review while EASD missions are still running: "
            + ", ".join(str(item.id) for item in nonterminal)
        )
    run.status = "reviewing"
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="review_started",
        actor="human",
        delivery_flow=spec_context.specification.delivery_flow.model_dump(mode="json"),
    )
    TRACE_OPERATIONS.labels(
        operation="review_start", status="ok", risk_tier=run.risk_tier
    ).inc()
    return run


async def start_verification_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    session_id: str | UUID,
) -> TraceRun:
    """Move reviewed work into the final verification phase."""

    spec_context = await active_context(db, run_id)
    run = spec_context.run
    plan_context = (
        await active_plan_context(db, run_id)
        if spec_context.specification.delivery_flow.mode == "planned"
        else None
    )
    from_status = run.status
    await _session_for_run(db, run, session_id)
    if run.status == "verifying":
        return run
    if run.status != "reviewing":
        raise TraceConflict(f"Cannot verify while EASD run is {run.status}")
    nonterminal = await _nonterminal_missions(db, run_id=run.id)
    if nonterminal:
        raise TraceConflict(
            "Cannot start verification while review missions are still running: "
            + ", ".join(str(item.id) for item in nonterminal)
        )
    review_evidence = list(
        (
            await db.exec(
                select(TraceEvidence).where(
                    TraceEvidence.run_id == run.id,
                    TraceEvidence.spec_hash == spec_context.revision.content_hash,
                    TraceEvidence.kind == "review",
                    TraceEvidence.result == "passed",
                )
            )
        ).all()
    )
    if not review_evidence:
        raise TraceConflict("Passing EASD review evidence is required before Verify")
    if (
        plan_context is not None
        and plan_context.plan.review_required
        and not any(
            item.payload.get("runtime_reviewer_identity") is True
            and item.payload.get("independent") is True
            for item in review_evidence
        )
    ):
        raise TraceConflict(
            "Independent passing review evidence is required before Verify"
        )
    run.status = "verifying"
    run.updated_at = _utcnow()
    db.add(run)
    await db.flush()
    _queue_run_state(
        db,
        run,
        from_status=from_status,
        event="verification_started",
        actor="human",
        delivery_flow=spec_context.specification.delivery_flow.model_dump(mode="json"),
    )
    TRACE_OPERATIONS.labels(
        operation="verification_start", status="ok", risk_tier=run.risk_tier
    ).inc()
    return run


async def active_run_for_session(
    db: AsyncSession, session_id: str | UUID
) -> TraceRun | None:
    session_uuid = _uuid(session_id, label="Coding session ID")
    return (
        await db.exec(
            select(TraceRun)
            .where(
                TraceRun.session_id == session_uuid,
                col(TraceRun.status).in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(col(TraceRun.updated_at).desc())
        )
    ).first()


async def preimplementation_run_for_session(
    db: AsyncSession, session_id: str | UUID
) -> TraceRun | None:
    session_uuid = _uuid(session_id, label="Coding session ID")
    return (
        await db.exec(
            select(TraceRun)
            .where(
                TraceRun.session_id == session_uuid,
                col(TraceRun.status).in_(
                    {
                        "intent",
                        "authoring",
                        "draft",
                        "accepted",
                        "planning",
                        "plan_review",
                        "planned",
                    }
                ),
            )
            .order_by(col(TraceRun.updated_at).desc())
        )
    ).first()


async def _repository_roots_for_run(
    db: AsyncSession, run: TraceRun
) -> tuple[dict[str, str], ...]:
    if run.project_id is None:
        return (
            {
                "repository": Path(run.workspace).name,
                "path": _normalize_workspace(run.workspace),
            },
        )
    pairs = await get_project_workspaces(db, run.project_id)
    roots = [
        {
            "repository": link.display_name
            or repository.name
            or Path(repository.path).name,
            "path": _normalize_workspace(repository.path),
        }
        for link, repository in pairs
    ]
    owning = _normalize_workspace(run.workspace)
    roots.sort(key=lambda item: item["path"] != owning)
    return tuple(roots)


async def build_easd_runtime_contract(
    db: AsyncSession,
    *,
    session_id: str | UUID,
    agent_name: str,
    role: str,
) -> EasdRuntimeContract | None:
    """Load the bounded accepted EASD contract used by Coding runtime hooks."""

    run = await active_run_for_session(db, session_id)
    if run is None:
        return None
    context = await active_context(db, run.id)
    spec = context.specification
    plan_revision: TracePlanRevision | None = None
    plan: TracePlan | None = None
    if run.active_plan_revision_id is not None:
        candidate = await _plan_revision_for_run(
            db,
            run_id=run.id,
            revision_id=run.active_plan_revision_id,
        )
        if (
            candidate.status == "accepted"
            and candidate.spec_hash == context.revision.content_hash
        ):
            plan_revision = candidate
            plan = TracePlan.model_validate(candidate.plan)
    lines = [
        "## EASD Development Contract",
        "",
        f"Run: {run.id}",
        f"Phase: {run.status}",
        f"Accepted spec hash: {context.revision.content_hash}",
        f"Risk tier: {run.risk_tier}",
        f"Agent: {agent_name} ({role})",
        "",
        f"Problem: {spec.problem}",
        f"Intended outcome: {spec.outcome}",
    ]
    if spec.goals:
        lines.extend(["", "Goals:", *(f"- {item}" for item in spec.goals)])
    if spec.non_goals:
        lines.extend(["", "Non-goals:", *(f"- {item}" for item in spec.non_goals)])
    if spec.source_refs:
        lines.extend(
            ["", "Source references:", *(f"- {item}" for item in spec.source_refs)]
        )
    if spec.impact_targets:
        lines.extend(["", "Affected targets:"])
        lines.extend(
            f"- {item.repository}:{item.path}"
            f"{f' ({item.module})' if item.module else ''}: {item.reason}"
            for item in spec.impact_targets
        )
    if spec.constraints:
        lines.extend(["", "Constraints:"])
        lines.extend(
            f"- [{item.kind}] {item.statement}"
            f"{f' (sources: {", ".join(item.source_refs)})' if item.source_refs else ''}"
            for item in spec.constraints
        )
    if spec.verification_commands:
        lines.extend(
            [
                "",
                "Planned verification commands:",
                *(f"- {item}" for item in spec.verification_commands),
            ]
        )
    lines.extend(["", "Acceptance criteria:"])
    lines.extend(
        f"- {criterion.id}: {criterion.statement} "
        f"[allowed={','.join(criterion.evidence_policy.allowed_kinds)}; "
        f"machine_required={str(criterion.evidence_policy.machine_required).lower()}; "
        f"minimum_passes={criterion.evidence_policy.minimum_passes}]"
        for criterion in spec.criteria
    )
    if plan_revision is not None and plan is not None:
        lines.extend(
            [
                "",
                f"Accepted plan hash: {plan_revision.content_hash}",
                "Approved plan missions:",
            ]
        )
        lines.extend(
            f"- {mission.id} [{mission.kind}] ACs="
            f"{','.join(mission.acceptance_criteria)}; repos="
            f"{','.join(mission.target_repositories) or '-'}; paths="
            f"{','.join(mission.target_paths) or '-'}; depends="
            f"{','.join(mission.depends_on) or '-'}; {mission.title}"
            for mission in plan.missions
        )
    delegation_identity = (
        "- Every substantial delegation must include this run ID, exact spec and "
        "plan hashes, approved plan mission ID, and owned acceptance criteria."
        if plan_revision is not None
        else "- This is direct flow: delegations include run ID, exact spec hash, "
        "and owned acceptance criteria, and must not invent a Plan identity."
    )
    lines.extend(
        [
            "",
            "EASD runtime rules:",
            "- Repository files under the configured data_directory are the shared "
            "source of truth; re-read them instead of relying on chat memory.",
            "- Do not silently expand or rewrite the accepted specification.",
            "- Record scope/spec drift as an EASD deviation.",
            delegation_identity,
            "- Final EASD handoffs must report every assigned criterion in "
            "criteria_results and include real verification evidence.",
            "- Agent completion is not run convergence; the EASD convergence "
            "service owns Done.",
        ]
    )
    block = "\n".join(lines)
    prompt = block if len(block) <= 12_000 else block[:11_950] + "\n[truncated]"
    return EasdRuntimeContract(
        run_id=str(run.id),
        run_status=run.status,
        spec_hash=context.revision.content_hash,
        plan_hash=plan_revision.content_hash if plan_revision else None,
        prompt=prompt,
        verification_commands=tuple(spec.verification_commands),
        impact_targets=tuple(
            target.model_dump(mode="json") for target in spec.impact_targets
        ),
        repository_roots=await _repository_roots_for_run(db, run),
    )


async def active_context(db: AsyncSession, run_id: str | UUID) -> _TraceContext:
    run = await get_run(db, run_id)
    if run.active_spec_revision_id is None:
        raise TraceConflict("EASD run has no accepted specification")
    revision = await _revision_for_run(
        db,
        run_id=run.id,
        revision_id=run.active_spec_revision_id,
    )
    if revision.status != "accepted":
        raise TraceConflict("EASD active specification is not accepted")
    specification = TraceSpecification.model_validate(revision.spec)
    return _TraceContext(run=run, revision=revision, specification=specification)


async def active_plan_context(
    db: AsyncSession, run_id: str | UUID
) -> _TracePlanContext:
    context = await active_context(db, run_id)
    run = context.run
    if run.active_plan_revision_id is None:
        raise TraceConflict("EASD run has no accepted implementation plan")
    revision = await _plan_revision_for_run(
        db,
        run_id=run.id,
        revision_id=run.active_plan_revision_id,
    )
    if revision.status != "accepted":
        raise TraceConflict("EASD active plan is not accepted")
    if revision.spec_hash != context.revision.content_hash:
        raise TraceConflict("EASD active plan references a stale specification")
    return _TracePlanContext(
        run=run,
        spec_revision=context.revision,
        specification=context.specification,
        plan_revision=revision,
        plan=TracePlan.model_validate(revision.plan),
    )


async def validate_mission_binding(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    spec_hash: str,
    plan_hash: str | None,
    plan_mission_id: str | None,
    criterion_ids: list[str],
    target_paths: list[str] | None = None,
    target_repositories: list[str] | None = None,
) -> _TraceMissionContext:
    spec_context = await active_context(db, run_id)
    if spec_context.run.status not in MISSION_RUN_STATUSES:
        raise TraceConflict(f"EASD run is {spec_context.run.status}, not active")
    if spec_context.revision.content_hash != spec_hash:
        raise TraceConflict("EASD mission references a stale spec hash")
    if spec_context.specification.delivery_flow.mode == "direct":
        if plan_hash or plan_mission_id:
            raise TraceValidationError(
                "Direct-flow EASD missions must not claim a Plan identity"
            )
        requested = set(criterion_ids)
        if not requested:
            raise TraceValidationError("EASD mission requires acceptance criteria")
        unknown = sorted(requested - spec_context.specification.criterion_ids())
        if unknown:
            raise TraceValidationError(
                "Unknown EASD acceptance criteria: " + ", ".join(unknown)
            )
        context = _TraceMissionContext(
            run=spec_context.run,
            spec_revision=spec_context.revision,
            specification=spec_context.specification,
            plan_revision=None,
            plan=None,
        )
        await _validate_mission_scope(
            db,
            context=context,
            target_paths=target_paths,
            target_repositories=target_repositories,
            plan_mission=None,
        )
        return context

    plan_context = await active_plan_context(db, run_id)
    context = _TraceMissionContext(
        run=plan_context.run,
        spec_revision=plan_context.spec_revision,
        specification=plan_context.specification,
        plan_revision=plan_context.plan_revision,
        plan=plan_context.plan,
    )
    if not plan_hash or not plan_mission_id:
        raise TraceValidationError("Planned EASD missions require exact Plan identity")
    if plan_context.plan_revision.content_hash != plan_hash:
        raise TraceConflict("EASD mission references a stale plan hash")
    plan_mission = next(
        (item for item in plan_context.plan.missions if item.id == plan_mission_id),
        None,
    )
    if plan_mission is None:
        raise TraceValidationError("Unknown EASD plan mission: " + plan_mission_id)
    allowed_kinds = {
        "active": {"implementation", "integration"},
        "reviewing": {"review"},
        "verifying": {"verification"},
    }[context.run.status]
    if plan_mission.kind not in allowed_kinds:
        raise TraceConflict(
            f"Plan mission {plan_mission.id} ({plan_mission.kind}) cannot run "
            f"during {context.run.status}"
        )
    requested = set(criterion_ids)
    if not requested:
        raise TraceValidationError("EASD mission requires acceptance criteria")
    unknown = sorted(requested - context.specification.criterion_ids())
    if unknown:
        raise TraceValidationError(
            "Unknown EASD acceptance criteria: " + ", ".join(unknown)
        )
    if requested != set(plan_mission.acceptance_criteria):
        raise TraceValidationError(
            f"EASD delegation criteria must exactly match plan mission {plan_mission.id}"
        )
    await _validate_mission_scope(
        db,
        context=context,
        target_paths=target_paths,
        target_repositories=target_repositories,
        plan_mission=plan_mission,
    )
    return context


async def _validate_mission_scope(
    db: AsyncSession,
    *,
    context: _TraceMissionContext,
    target_paths: list[str] | None,
    target_repositories: list[str] | None,
    plan_mission: Any | None,
) -> None:
    selected_repositories: set[str] = set()
    if target_repositories:
        accepted_repositories = {
            item.repository for item in context.specification.impact_targets
        }
        repository_roots = await _repository_roots_for_run(db, context.run)
        repository_by_path = {
            item["path"]: item["repository"] for item in repository_roots
        }
        resolved_repositories = {
            raw: (
                raw
                if raw in accepted_repositories
                else repository_by_path.get(_normalize_workspace(raw))
                if Path(raw).is_absolute()
                else Path(raw).name
                if Path(raw).name in accepted_repositories
                else None
            )
            for raw in target_repositories
        }
        unknown_repositories = sorted(
            raw
            for raw, resolved in resolved_repositories.items()
            if resolved not in accepted_repositories
        )
        if unknown_repositories:
            raise TraceValidationError(
                "EASD mission targets repositories outside the accepted Scope: "
                + ", ".join(unknown_repositories)
            )
        selected_repositories = {
            resolved
            for resolved in resolved_repositories.values()
            if resolved is not None
        }
        if plan_mission is not None and not selected_repositories.issubset(
            set(plan_mission.target_repositories)
        ):
            raise TraceValidationError(
                f"EASD delegation repositories exceed plan mission {plan_mission.id}"
            )
    elif plan_mission is not None and plan_mission.target_repositories:
        raise TraceValidationError(
            f"EASD delegation must name repositories from plan mission {plan_mission.id}"
        )
    if target_paths:
        accepted_paths = [
            _normalized_spec_path(item.path)
            for item in context.specification.impact_targets
            if not selected_repositories or item.repository in selected_repositories
        ]
        outside = sorted(
            path
            for path in target_paths
            if not _path_is_within_any(_normalized_spec_path(path), accepted_paths)
        )
        if outside:
            raise TraceValidationError(
                "EASD mission target_paths exceed the accepted Scope: "
                + ", ".join(outside)
            )
        if plan_mission is not None:
            outside_plan = sorted(
                path
                for path in target_paths
                if not _path_is_within_any(
                    _normalized_spec_path(path),
                    [_normalized_spec_path(item) for item in plan_mission.target_paths],
                )
            )
            if outside_plan:
                raise TraceValidationError(
                    f"EASD delegation target_paths exceed plan mission {plan_mission.id}: "
                    + ", ".join(outside_plan)
                )
    elif plan_mission is not None and plan_mission.target_paths:
        raise TraceValidationError(
            f"EASD delegation must name target_paths from plan mission {plan_mission.id}"
        )


def _normalized_spec_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise TraceValidationError("EASD target paths must be repository-relative")
    return str(path)


def _path_is_within_any(path: str, accepted_paths: list[str]) -> bool:
    return any(
        target in {"", "."} or path == target or path.startswith(f"{target}/")
        for target in accepted_paths
    )


def _completion_contract(verification: object) -> dict[str, Any] | None:
    if not isinstance(verification, dict):
        return None
    value = cast(dict[str, object], verification).get("completion_contract")
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _artifact_scope_targets(
    artifact: dict[str, Any],
    completion_contract: dict[str, Any] | None,
    repository_roots: tuple[dict[str, str], ...],
) -> list[dict[str, str | None]]:
    targets: list[dict[str, str | None]] = []
    if completion_contract is not None:
        values = completion_contract.get("scope_targets")
        if isinstance(values, list):
            for raw in values:
                if not isinstance(raw, dict):
                    continue
                repository = raw.get("repository")
                path = raw.get("path")
                if isinstance(path, str):
                    targets.append(
                        {
                            "repository": (
                                repository if isinstance(repository, str) else None
                            ),
                            "path": path,
                        }
                    )
        elif isinstance(completion_contract.get("scope_paths"), list):
            targets.extend(
                {"repository": None, "path": str(item)}
                for item in completion_contract["scope_paths"]
                if isinstance(item, str)
            )
    workspace_result = artifact.get("workspace_result")
    if isinstance(workspace_result, dict):
        repositories = workspace_result.get("repositories")
        if isinstance(repositories, list):
            for repository in repositories:
                if not isinstance(repository, dict):
                    continue
                source = repository.get("source")
                repository_name = next(
                    (
                        item["repository"]
                        for item in repository_roots
                        if isinstance(source, str)
                        and _normalize_workspace(source) == item["path"]
                    ),
                    Path(source).name if isinstance(source, str) else None,
                )
                changed_files = repository.get("changed_files")
                if isinstance(changed_files, list):
                    targets.extend(
                        {"repository": repository_name, "path": str(item)}
                        for item in changed_files
                        if isinstance(item, str)
                    )
    unique = {(item["repository"], item["path"]): item for item in targets}
    return list(unique.values())


def _scope_target_is_accepted(
    target: dict[str, str | None],
    accepted: list[tuple[str | None, str]],
) -> bool:
    repository = target["repository"]
    path = _normalized_spec_path(target["path"] or "")
    return any(
        (
            repository is None
            or accepted_repository is None
            or repository == accepted_repository
        )
        and _path_is_within_any(path, [accepted_path])
        for accepted_repository, accepted_path in accepted
    )


def _passed_planned_commands(evidence: list[dict[str, Any]]) -> set[str]:
    commands: set[str] = set()
    for item in evidence:
        if item.get("kind") != "machine" or item.get("result") != "passed":
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        direct = payload.get("spec_command")
        if isinstance(direct, str) and direct.strip():
            commands.add(direct.strip())
        verification = payload.get("verification")
        contract = _completion_contract(verification)
        if contract is None or contract.get("passed") is not True:
            continue
        records = contract.get("evidence")
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            spec_command = record.get("spec_command")
            if (
                record.get("source") == "planned"
                and record.get("passed") is True
                and isinstance(spec_command, str)
                and spec_command.strip()
            ):
                commands.add(spec_command.strip())
    return commands


async def create_evidence(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    spec_hash: str,
    criterion_ids: list[str],
    producer: str,
    kind: TraceEvidenceKind,
    result: TraceEvidenceResult,
    summary: str,
    delegation_task_id: UUID | None = None,
    revision: str | None = None,
    artifact_hash: str | None = None,
    payload: dict | None = None,
    source_key: str | None = None,
) -> TraceEvidence:
    context = await active_context(db, run_id)
    if context.run.status not in EVIDENCE_RUN_STATUSES:
        raise TraceConflict(
            f"Cannot add evidence while EASD run is {context.run.status}"
        )
    if context.revision.content_hash != spec_hash:
        raise TraceConflict("EASD evidence references a stale spec hash")
    requested = set(criterion_ids)
    if not requested:
        raise TraceValidationError("EASD evidence requires acceptance criteria")
    unknown = sorted(requested - context.specification.criterion_ids())
    if unknown:
        raise TraceValidationError(
            "Unknown EASD acceptance criteria: " + ", ".join(unknown)
        )
    if kind == "waiver" and result != "waived":
        raise TraceValidationError("Waiver evidence must use result='waived'")
    if result == "waived" and kind != "waiver":
        raise TraceValidationError("Only waiver evidence may waive a criterion")
    if delegation_task_id is not None:
        task = await db.get(DelegationTask, delegation_task_id)
        if task is None or task.trace_run_id != context.run.id:
            raise TraceValidationError("EASD evidence mission belongs to another run")
    normalized_summary = summary.strip()
    normalized_producer = producer.strip()
    if not normalized_summary or not normalized_producer:
        raise TraceValidationError("EASD evidence producer and summary are required")
    normalized_source_key = source_key.strip() if source_key else None
    if normalized_source_key:
        existing = (
            await db.exec(
                select(TraceEvidence).where(
                    TraceEvidence.run_id == context.run.id,
                    TraceEvidence.source_key == normalized_source_key,
                )
            )
        ).first()
        if existing is not None:
            if (
                existing.spec_hash == spec_hash
                and existing.criterion_ids == list(dict.fromkeys(criterion_ids))
                and existing.producer == normalized_producer
                and existing.kind == kind
                and existing.result == result
                and existing.summary == normalized_summary
                and existing.delegation_task_id == delegation_task_id
                and existing.revision == revision
                and existing.artifact_hash == artifact_hash
                and existing.payload == dict(payload or {})
            ):
                return existing
            raise TraceConflict("EASD evidence source key already has another result")
    row = TraceEvidence(
        run_id=context.run.id,
        delegation_task_id=delegation_task_id,
        spec_hash=spec_hash,
        criterion_ids=list(dict.fromkeys(criterion_ids)),
        producer=normalized_producer,
        kind=kind,
        result=result,
        summary=normalized_summary,
        revision=revision,
        artifact_hash=artifact_hash,
        payload=dict(payload or {}),
        source_key=normalized_source_key,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TraceConflict("EASD evidence source key already exists") from exc
    evidence_payload = serialize_evidence(row)
    enqueue_artifact(
        db,
        workspace=context.run.workspace,
        run_id=str(context.run.id),
        kind="evidence",
        artifact_id=str(row.id),
        payload=evidence_payload,
    )
    if kind == "review":
        enqueue_artifact(
            db,
            workspace=context.run.workspace,
            run_id=str(context.run.id),
            kind="reviews",
            artifact_id=str(row.id),
            payload=evidence_payload,
        )
    elif kind == "machine" and context.run.status == "verifying":
        enqueue_artifact(
            db,
            workspace=context.run.workspace,
            run_id=str(context.run.id),
            kind="verifications",
            artifact_id=str(row.id),
            payload=evidence_payload,
        )
    logger.info(
        "trace_evidence_added run_id={} kind={} result={} criteria={}",
        context.run.id,
        kind,
        result,
        len(row.criterion_ids),
    )
    TRACE_OPERATIONS.labels(
        operation="evidence_add", status=result, risk_tier=context.run.risk_tier
    ).inc()
    return row


async def submit_review_evidence(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    spec_hash: str,
    reviewer: str,
    reviewer_role: Literal["lead", "member"],
    criteria_results: list[TraceReviewCriterion],
    findings: list[str],
    sources: list[str],
    summary: str,
    revision: str,
    artifact_hash: str | None = None,
    confidence: float | None = None,
    delegation_task_id: UUID | None = None,
) -> list[TraceEvidence]:
    """Persist typed review evidence using runtime-owned reviewer identity."""

    context = await active_context(db, run_id)
    if context.run.status != "reviewing":
        raise TraceConflict(
            f"Cannot submit review while EASD run is {context.run.status}"
        )
    if context.revision.content_hash != spec_hash:
        raise TraceConflict("EASD review references a stale specification hash")
    if not criteria_results:
        raise TraceValidationError("EASD review requires criterion results")
    result_ids = [item.criterion_id for item in criteria_results]
    if len(set(result_ids)) != len(result_ids):
        raise TraceValidationError("EASD review criterion results must be unique")
    unknown = sorted(set(result_ids) - context.specification.criterion_ids())
    if unknown:
        raise TraceValidationError(
            "Unknown EASD review criteria: " + ", ".join(unknown)
        )
    normalized_reviewer = reviewer.strip()
    normalized_summary = summary.strip()
    normalized_revision = revision.strip()
    if not normalized_reviewer or not normalized_summary or not normalized_revision:
        raise TraceValidationError(
            "EASD review requires reviewer, summary, and revision"
        )

    review_task: DelegationTask | None = None
    independent = False
    if delegation_task_id is not None:
        review_task = await db.get(DelegationTask, delegation_task_id)
        if review_task is None or review_task.trace_run_id != context.run.id:
            raise TraceValidationError("EASD review mission belongs to another run")
        if review_task.recipient != normalized_reviewer:
            raise TraceValidationError(
                "EASD review mission recipient does not match runtime reviewer"
            )
        task_spec = review_task.spec if isinstance(review_task.spec, dict) else {}
        task_plan_hash = task_spec.get("trace_plan_hash")
        task_plan_mission_id = task_spec.get("plan_mission_id")
        mission_context = await validate_mission_binding(
            db,
            run_id=context.run.id,
            spec_hash=spec_hash,
            plan_hash=(task_plan_hash if isinstance(task_plan_hash, str) else None),
            plan_mission_id=(
                task_plan_mission_id if isinstance(task_plan_mission_id, str) else None
            ),
            criterion_ids=result_ids,
            target_paths=[
                str(item)
                for item in task_spec.get("target_paths", [])
                if isinstance(item, str)
            ],
            target_repositories=[
                str(item)
                for item in task_spec.get("target_repos", [])
                if isinstance(item, str)
            ],
        )
        implementation_mission_ids = {
            mission.id
            for mission in (
                mission_context.plan.missions if mission_context.plan else []
            )
            if mission.kind in {"implementation", "integration"}
            and set(mission.acceptance_criteria) & set(result_ids)
        }
        overlapping_work = list(
            (
                await db.exec(
                    select(DelegationTask).where(
                        DelegationTask.trace_run_id == context.run.id,
                        DelegationTask.id != review_task.id,
                        DelegationTask.recipient == normalized_reviewer,
                        DelegationTask.status == "completed",
                    )
                )
            ).all()
        )
        reviewed = set(result_ids)
        independent = reviewer_role == "member" and not any(
            isinstance(item.spec, dict)
            and item.spec.get("plan_mission_id") in implementation_mission_ids
            and reviewed & set(item.spec.get("acceptance_criteria", []))
            for item in overlapping_work
        )

    cleaned_findings = list(
        dict.fromkeys(item.strip() for item in findings if item.strip())
    )
    cleaned_sources = list(
        dict.fromkeys(item.strip() for item in sources if item.strip())
    )
    payload_base = {
        "runtime_reviewer_identity": True,
        "reviewer_role": reviewer_role,
        "independent": independent,
        "review_summary": normalized_summary,
        "findings": cleaned_findings,
        "sources": cleaned_sources,
        "confidence": confidence,
    }
    rows: list[TraceEvidence] = []
    for item in criteria_results:
        source_payload = {
            "run_id": str(context.run.id),
            "spec_hash": spec_hash,
            "reviewer": normalized_reviewer,
            "revision": normalized_revision,
            "artifact_hash": artifact_hash,
            "criterion_id": item.criterion_id,
        }
        digest = hashlib.sha256(
            _stable_payload(source_payload).encode("utf-8")
        ).hexdigest()
        rows.append(
            await create_evidence(
                db,
                run_id=context.run.id,
                spec_hash=spec_hash,
                criterion_ids=[item.criterion_id],
                producer=normalized_reviewer,
                kind="review",
                result=item.result,
                summary=item.summary,
                delegation_task_id=delegation_task_id,
                revision=normalized_revision,
                artifact_hash=artifact_hash,
                payload=payload_base,
                source_key=f"agent-review:{digest}",
            )
        )
    return rows


async def record_mission_handoff_evidence(
    db: AsyncSession,
    *,
    task: DelegationTask,
    artifact: dict,
) -> list[TraceEvidence]:
    """Persist EASD evidence from one final typed mission handoff.

    Machine trust is granted only when the runtime-generated
    ``completion_contract`` verification is present. Criterion result prose is
    retained in the evidence payload but never upgrades self-reported checks to
    machine evidence.
    """

    if task.trace_run_id is None:
        return []
    spec_hash = task.spec.get("trace_spec_hash")
    raw_plan_hash = task.spec.get("trace_plan_hash")
    raw_plan_mission_id = task.spec.get("plan_mission_id")
    plan_hash = (
        raw_plan_hash if isinstance(raw_plan_hash, str) and raw_plan_hash else None
    )
    plan_mission_id = (
        raw_plan_mission_id
        if isinstance(raw_plan_mission_id, str) and raw_plan_mission_id
        else None
    )
    assigned = [
        str(item)
        for item in task.spec.get("acceptance_criteria", [])
        if isinstance(item, str) and item
    ]
    if not isinstance(spec_hash, str) or len(spec_hash) != 64 or not assigned:
        raise TraceValidationError(
            "EASD mission is missing specification identity or acceptance criteria"
        )
    raw_results = artifact.get("criteria_results")
    if not isinstance(raw_results, list):
        raise TraceValidationError("EASD handoff requires criteria_results")
    by_id = {
        str(item.get("criterion_id")): item
        for item in raw_results
        if isinstance(item, dict) and item.get("criterion_id")
    }
    missing = sorted(set(assigned) - set(by_id))
    if missing:
        raise TraceValidationError(
            "EASD handoff is missing criterion results: " + ", ".join(missing)
        )

    verification = artifact.get("verification")
    completion_contract = _completion_contract(verification)
    machine_verified = (
        isinstance(verification, dict)
        and verification.get("method") == "completion_contract"
        and verification.get("verified") is True
        and bool(verification.get("command_ids"))
        and completion_contract is not None
        and completion_contract.get("passed") is True
        and completion_contract.get("artifact_hash")
        == verification.get("artifact_hash")
    )
    context = await validate_mission_binding(
        db,
        run_id=task.trace_run_id,
        spec_hash=spec_hash,
        plan_hash=plan_hash,
        plan_mission_id=plan_mission_id,
        criterion_ids=assigned,
        target_paths=[
            str(item)
            for item in task.spec.get("target_paths", [])
            if isinstance(item, str)
        ],
        target_repositories=[
            str(item)
            for item in task.spec.get("target_repos", [])
            if isinstance(item, str)
        ],
    )
    repository_roots = await _repository_roots_for_run(db, context.run)
    scope_targets = _artifact_scope_targets(
        artifact, completion_contract, repository_roots
    )
    mission_paths = [
        _normalized_spec_path(str(item))
        for item in task.spec.get("target_paths", [])
        if isinstance(item, str)
    ]
    mission_repositories = [
        str(item) for item in task.spec.get("target_repos", []) if isinstance(item, str)
    ]
    accepted_repository_names = {
        item.repository for item in context.specification.impact_targets
    }
    repository_by_path = {item["path"]: item["repository"] for item in repository_roots}
    selected_repositories = {
        raw
        if raw in accepted_repository_names
        else repository_by_path.get(_normalize_workspace(raw), Path(raw).name)
        for raw in mission_repositories
    }
    accepted_targets: list[tuple[str | None, str]]
    if mission_paths:
        accepted_targets = [
            (repository if selected_repositories else None, path)
            for repository in (selected_repositories or {None})
            for path in mission_paths
        ]
    else:
        accepted_targets = [
            (cast(str | None, item.repository), _normalized_spec_path(item.path))
            for item in context.specification.impact_targets
        ]
    outside_scope = sorted(
        (
            f"{target['repository']}:{target['path']}"
            if target["repository"]
            else str(target["path"])
        )
        for target in scope_targets
        if not _scope_target_is_accepted(target, accepted_targets)
    )
    if outside_scope:
        machine_verified = False
        await create_deviation(
            db,
            run_id=task.trace_run_id,
            description=(
                "Mission changed paths outside the accepted Scope: "
                + ", ".join(outside_scope)
            ),
            blocking=True,
            delegation_task_id=task.id,
            proposed_change={
                "source": "completion_contract",
                "paths": outside_scope,
                "task_attempt": task.attempt,
            },
        )
    kind: TraceEvidenceKind = "machine" if machine_verified else "manual"
    created: list[TraceEvidence] = []
    for criterion_id in assigned:
        criterion_result = by_id[criterion_id]
        raw_result = str(criterion_result.get("result") or "inconclusive")
        result = cast(
            TraceEvidenceResult,
            raw_result
            if raw_result in {"passed", "failed", "inconclusive"}
            else "inconclusive",
        )
        summary = str(criterion_result.get("summary") or artifact.get("summary") or "")
        artifact_hash = (
            str(verification.get("artifact_hash"))
            if isinstance(verification, dict) and verification.get("artifact_hash")
            else None
        )
        revision = (
            str(verification.get("revision"))
            if isinstance(verification, dict) and verification.get("revision")
            else None
        )
        source_key = (
            f"mission:{task.id}:attempt:{task.attempt}:criterion:{criterion_id}:"
            f"{artifact_hash or 'manual'}"
        )
        created.append(
            await create_evidence(
                db,
                run_id=task.trace_run_id,
                spec_hash=spec_hash,
                criterion_ids=[criterion_id],
                producer=task.recipient,
                kind=kind,
                result=result,
                summary=summary,
                delegation_task_id=task.id,
                revision=revision,
                artifact_hash=artifact_hash,
                payload={
                    "task_attempt": task.attempt,
                    "criterion_result": criterion_result,
                    "verification": verification,
                },
                source_key=source_key,
            )
        )
    raw_deviations = artifact.get("deviations")
    if isinstance(raw_deviations, list):
        for raw_deviation in raw_deviations:
            description = str(raw_deviation).strip()
            if not description:
                continue
            await create_deviation(
                db,
                run_id=task.trace_run_id,
                description=description,
                blocking=True,
                delegation_task_id=task.id,
                proposed_change={
                    "source": "mission_handoff",
                    "task_attempt": task.attempt,
                },
            )
    return created


def record_mission_binding(
    context: _TraceMissionContext,
    *,
    missions: list[DelegationTask],
) -> None:
    """Emit the durable mission-binding operation after its transaction commits."""

    plan_hash = (
        context.plan_revision.content_hash[:12]
        if context.plan_revision is not None
        else "direct"
    )
    logger.info(
        "trace_mission_bound run_id={} spec_hash={} plan_hash={} missions={}",
        context.run.id,
        context.spec_revision.content_hash[:12],
        plan_hash,
        len(missions),
    )
    TRACE_OPERATIONS.labels(
        operation="mission_bind",
        status="ok",
        risk_tier=context.run.risk_tier,
    ).inc(len(missions))


async def create_deviation(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    description: str,
    blocking: bool = True,
    criterion_id: str | None = None,
    delegation_task_id: UUID | None = None,
    proposed_change: dict | None = None,
) -> TraceDeviation:
    context = await active_context(db, run_id)
    if context.run.status not in ACTIVE_RUN_STATUSES:
        raise TraceConflict(
            f"Cannot record a deviation while EASD run is {context.run.status}"
        )
    if criterion_id and criterion_id not in context.specification.criterion_ids():
        raise TraceValidationError("EASD deviation references an unknown criterion")
    if delegation_task_id is not None:
        task = await db.get(DelegationTask, delegation_task_id)
        if task is None or task.trace_run_id != context.run.id:
            raise TraceValidationError("EASD deviation mission belongs to another run")
    normalized = description.strip()
    if not normalized:
        raise TraceValidationError("EASD deviation description is required")
    row = TraceDeviation(
        run_id=context.run.id,
        spec_hash=context.revision.content_hash,
        criterion_id=criterion_id,
        delegation_task_id=delegation_task_id,
        blocking=blocking,
        description=normalized,
        proposed_change=dict(proposed_change or {}),
    )
    db.add(row)
    await db.flush()
    enqueue_artifact(
        db,
        workspace=context.run.workspace,
        run_id=str(context.run.id),
        kind="deviations",
        artifact_id=str(row.id),
        payload=serialize_deviation(row),
    )
    logger.info(
        "trace_deviation_created run_id={} blocking={} criterion={}",
        context.run.id,
        blocking,
        criterion_id,
    )
    TRACE_OPERATIONS.labels(
        operation="deviation_create",
        status="blocking" if blocking else "non_blocking",
        risk_tier=context.run.risk_tier,
    ).inc()
    return row


async def resolve_deviation(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    deviation_id: str | UUID,
    status: Literal["approved", "rejected", "resolved"],
    resolution: str,
    resolved_spec_hash: str | None = None,
) -> TraceDeviation:
    context = await active_context(db, run_id)
    row = await db.get(TraceDeviation, _uuid(deviation_id, label="EASD deviation ID"))
    if row is None or row.run_id != context.run.id:
        raise TraceNotFound("EASD deviation was not found in this run")
    normalized = resolution.strip()
    if not normalized:
        raise TraceValidationError("EASD deviation resolution is required")
    if status == "resolved":
        if resolved_spec_hash != context.revision.content_hash:
            raise TraceConflict(
                "Resolved deviation must reference the current accepted spec hash"
            )
        non_normative = row.proposed_change.get("non_normative") is True
        if not non_normative and resolved_spec_hash == row.spec_hash:
            raise TraceConflict(
                "Normative deviation requires a newly accepted spec revision"
            )
    row.status = status
    row.resolution = normalized
    row.resolved_spec_hash = resolved_spec_hash
    row.updated_at = _utcnow()
    if status in {"rejected", "resolved"}:
        row.resolved_at = row.updated_at
    db.add(row)
    await db.flush()
    enqueue_artifact_update(
        db,
        workspace=context.run.workspace,
        run_id=str(context.run.id),
        kind="deviations",
        artifact_id=str(row.id),
        payload=serialize_deviation(row),
    )
    logger.info(
        "trace_deviation_resolved run_id={} deviation_id={} status={}",
        context.run.id,
        row.id,
        status,
    )
    TRACE_OPERATIONS.labels(
        operation="deviation_resolve",
        status=status,
        risk_tier=context.run.risk_tier,
    ).inc()
    return row


def _criterion_matrix(
    specification: TraceSpecification,
    *,
    spec_hash: str,
    evidence: list[TraceEvidence],
    missions: list[DelegationTask],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for criterion in specification.criteria:
        related = [
            item
            for item in evidence
            if item.spec_hash == spec_hash and criterion.id in item.criterion_ids
        ]
        related_missions = [
            task
            for task in missions
            if criterion.id in task.spec.get("acceptance_criteria", [])
        ]
        waivers = [
            item
            for item in related
            if item.kind == "waiver" and item.result == "waived"
        ]
        allowed_passes = [
            item
            for item in related
            if item.result == "passed"
            and item.kind in criterion.evidence_policy.allowed_kinds
        ]
        has_machine = any(item.kind == "machine" for item in allowed_passes)
        passed = len(allowed_passes) >= criterion.evidence_policy.minimum_passes and (
            not criterion.evidence_policy.machine_required or has_machine
        )
        if waivers:
            status = "waived"
        elif passed:
            status = "passed"
        elif any(item.result == "failed" for item in related):
            status = "failed"
        elif related or any(
            task.status not in TERMINAL_MISSION_STATUSES for task in related_missions
        ):
            status = "in_progress"
        else:
            status = "uncovered"
        output.append(
            {
                "id": criterion.id,
                "statement": criterion.statement,
                "required": criterion.required,
                "status": status,
                "evidence_policy": criterion.evidence_policy.model_dump(mode="json"),
                "evidence_ids": [str(item.id) for item in related],
                "mission_ids": [str(item.id) for item in related_missions],
            }
        )
    return output


def _blocker(code: str, message: str, **fields: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **fields}


def _nonterminal_mission_blockers(
    missions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _blocker(
            "mission_not_terminal",
            f"Mission {item['id']} is still {item['status']}.",
            mission_id=item["id"],
            status=item["status"],
        )
        for item in missions
        if item["status"] not in TERMINAL_MISSION_STATUSES
    ]


def _verification_blockers(
    *,
    missions: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    independent_required: bool,
) -> list[dict[str, Any]]:
    blockers = _nonterminal_mission_blockers(missions)
    review_evidence = [
        item
        for item in evidence
        if item["kind"] == "review" and item["result"] == "passed"
    ]
    if not review_evidence:
        blockers.append(
            _blocker(
                "review_evidence_required",
                "Passing review evidence is required before Verify.",
            )
        )
    elif independent_required and not any(
        item["payload"].get("runtime_reviewer_identity") is True
        and item["payload"].get("independent") is True
        for item in review_evidence
    ):
        blockers.append(
            _blocker(
                "independent_review_required",
                "Independent runtime review evidence is required before Verify.",
            )
        )
    return blockers


def _convergence_reasons(
    *,
    detail: dict[str, Any],
    specification: TraceSpecification,
    independent_required: bool,
) -> list[dict[str, Any]]:
    criteria = detail["criteria"]
    missions = detail["missions"]
    deviations = detail["deviations"]
    reasons: list[dict[str, Any]] = []
    for item in criteria:
        if item["required"] and item["status"] not in {"passed", "waived"}:
            reasons.append(
                _blocker(
                    "criterion_not_satisfied",
                    f"{item['id']} is {item['status']} and still requires evidence.",
                    criterion_id=item["id"],
                    status=item["status"],
                )
            )
    reasons.extend(_nonterminal_mission_blockers(missions))
    unsatisfied = {
        criterion["id"]
        for criterion in criteria
        if criterion["status"] not in {"passed", "waived"}
    }
    for item in missions:
        if item["status"] != "cancelled":
            continue
        covered = set(item["spec"].get("acceptance_criteria", []))
        if covered & unsatisfied:
            reasons.append(
                _blocker(
                    "cancelled_mission_left_criteria_open",
                    f"Cancelled mission {item['id']} left required criteria open.",
                    mission_id=item["id"],
                )
            )
    for item in deviations:
        if item["blocking"] and item["status"] in {"open", "approved"}:
            reasons.append(
                _blocker(
                    "blocking_deviation",
                    "A blocking deviation must be rejected or resolved.",
                    deviation_id=item["id"],
                    status=item["status"],
                )
            )
    if independent_required and not any(
        item["kind"] == "review"
        and item["result"] == "passed"
        and item["payload"].get("runtime_reviewer_identity") is True
        and item["payload"].get("independent") is True
        for item in detail["evidence"]
    ):
        reasons.append(
            _blocker(
                "independent_review_required",
                "Independent passing review evidence is required before Converge.",
            )
        )
    planned_commands = set(specification.verification_commands)
    passed_planned_commands = _passed_planned_commands(detail["evidence"])
    missing_planned_commands = sorted(planned_commands - passed_planned_commands)
    if missing_planned_commands:
        reasons.append(
            _blocker(
                "planned_verification_missing",
                "Accepted verification commands still need passing machine evidence.",
                commands=missing_planned_commands,
            )
        )
    return reasons


def _action(
    action_id: str,
    label: str,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blockers = blockers or []
    return {
        "id": action_id,
        "label": label,
        "state": "blocked" if blockers else "available",
        "blockers": blockers,
    }


def _run_action_rail(
    *,
    run: TraceRun,
    specification: TraceSpecification | None,
    plan: TracePlan | None,
    detail: dict[str, Any],
) -> dict[str, Any]:
    status = run.status
    actions: list[dict[str, Any]] = []
    primary_action: str | None = None

    def add(
        action_id: str,
        label: str,
        blockers: list[dict[str, Any]] | None = None,
        *,
        primary: bool = False,
    ) -> None:
        nonlocal primary_action
        actions.append(_action(action_id, label, blockers))
        if primary:
            primary_action = action_id

    if status == "intent":
        add("draft_specification", "Draft specification", primary=True)
    elif status == "authoring":
        add("retry_specification", "Retry drafting", primary=True)
    elif status == "draft":
        add("approve_specification", "Approve specification", primary=True)
        add("retry_specification", "Redraft in chat")
    elif status == "accepted" and specification is not None:
        if specification.delivery_flow.mode == "direct":
            add("start_implementation", "Run implementation", primary=True)
        else:
            add("start_planning", "Run plan", primary=True)
    elif status == "planning":
        add("retry_planning", "Retry planning", primary=True)
    elif status == "plan_review":
        add("approve_plan", "Approve plan", primary=True)
        add("retry_planning", "Replan in chat")
    elif status == "planned":
        add("start_implementation", "Run implementation", primary=True)
    elif status == "active":
        add(
            "start_review",
            "Run review",
            _nonterminal_mission_blockers(detail["missions"]),
            primary=True,
        )
    elif status == "reviewing":
        add(
            "start_verification",
            "Run verification",
            _verification_blockers(
                missions=detail["missions"],
                evidence=detail["evidence"],
                independent_required=bool(plan and plan.review_required),
            ),
            primary=True,
        )
    elif status == "verifying" and specification is not None:
        add(
            "converge",
            "Converge",
            _convergence_reasons(
                detail=detail,
                specification=specification,
                independent_required=bool(plan and plan.review_required),
            ),
            primary=True,
        )

    return {
        "phase": status,
        "primary_action": primary_action,
        "actions": actions,
    }


def _trace_node(
    node_id: str,
    kind: str,
    label: str,
    *,
    status: str | None = None,
    timestamp: str | None = None,
    entity_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "label": label,
        "status": status,
        "timestamp": timestamp,
        "entity_id": entity_id,
        "data": data or {},
    }


def _trace_edge(
    kind: str,
    source: str,
    target: str,
    *,
    criterion_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{kind}:{source}:{target}",
        "kind": kind,
        "source": source,
        "target": target,
        "criterion_ids": criterion_ids or [],
    }


def _trace_projection(
    detail: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run = detail["run"]
    run_id = str(run["id"])
    run_node_id = f"run:{run_id}"
    nodes: list[dict[str, Any]] = [
        _trace_node(
            run_node_id,
            "run",
            run["title"],
            status=run["status"],
            timestamp=run["updated_at"],
            entity_id=run_id,
            data={
                "risk_tier": run["risk_tier"],
                "workspace": run["workspace"],
                "session_id": run["session_id"],
            },
        )
    ]
    edges: list[dict[str, Any]] = []
    criterion_nodes: dict[tuple[str, str], str] = {}
    mission_contract_nodes: dict[tuple[str, str], str] = {}

    matrix_by_id = {item["id"]: item for item in detail["criteria"]}
    for revision in detail["revisions"]:
        revision_id = str(revision["id"])
        spec_hash = revision["content_hash"]
        spec_node_id = f"spec:{revision_id}"
        nodes.append(
            _trace_node(
                spec_node_id,
                "specification",
                f"Specification v{revision['version']}",
                status=revision["status"],
                timestamp=revision["created_at"],
                entity_id=revision_id,
                data={
                    "content_hash": spec_hash,
                    "risk_tier": revision["spec"].get("risk_tier"),
                    "delivery_flow": revision["spec"].get("delivery_flow"),
                    "outcome": revision["spec"].get("outcome"),
                },
            )
        )
        edges.append(_trace_edge("contains", run_node_id, spec_node_id))
        for criterion in revision["spec"].get("criteria", []):
            criterion_id = str(criterion["id"])
            criterion_node_id = f"criterion:{spec_hash}:{criterion_id}"
            criterion_nodes[(spec_hash, criterion_id)] = criterion_node_id
            matrix = matrix_by_id.get(criterion_id)
            nodes.append(
                _trace_node(
                    criterion_node_id,
                    "criterion",
                    criterion_id,
                    status=(matrix or {}).get("status", "uncovered"),
                    entity_id=criterion_id,
                    data={
                        "statement": criterion.get("statement"),
                        "required": criterion.get("required", True),
                        "spec_hash": spec_hash,
                        "evidence_policy": criterion.get("evidence_policy", {}),
                    },
                )
            )
            edges.append(
                _trace_edge(
                    "defines",
                    spec_node_id,
                    criterion_node_id,
                    criterion_ids=[criterion_id],
                )
            )

    spec_nodes_by_hash = {
        node["data"].get("content_hash"): node["id"]
        for node in nodes
        if node["kind"] == "specification"
    }
    for revision in detail["plan_revisions"]:
        revision_id = str(revision["id"])
        plan_hash = revision["content_hash"]
        plan_node_id = f"plan:{revision_id}"
        nodes.append(
            _trace_node(
                plan_node_id,
                "plan",
                f"Plan v{revision['version']}",
                status=revision["status"],
                timestamp=revision["created_at"],
                entity_id=revision_id,
                data={
                    "content_hash": plan_hash,
                    "spec_hash": revision["spec_hash"],
                    "review_required": revision["plan"].get("review_required", False),
                    "integration_owner": revision["plan"].get("integration_owner"),
                },
            )
        )
        edges.append(_trace_edge("contains", run_node_id, plan_node_id))
        spec_node_id = spec_nodes_by_hash.get(revision["spec_hash"])
        if spec_node_id:
            edges.append(_trace_edge("compiled_to", spec_node_id, plan_node_id))
        for mission in revision["plan"].get("missions", []):
            mission_id = str(mission["id"])
            mission_node_id = f"mission_contract:{plan_hash}:{mission_id}"
            mission_contract_nodes[(plan_hash, mission_id)] = mission_node_id
            criterion_ids = [
                str(item) for item in mission.get("acceptance_criteria", [])
            ]
            nodes.append(
                _trace_node(
                    mission_node_id,
                    "mission_contract",
                    mission.get("title") or mission_id,
                    status=mission.get("kind"),
                    entity_id=mission_id,
                    data={
                        "plan_hash": plan_hash,
                        "kind": mission.get("kind"),
                        "goal": mission.get("goal"),
                        "target_repositories": mission.get("target_repositories", []),
                        "target_paths": mission.get("target_paths", []),
                        "isolation": mission.get("isolation"),
                    },
                )
            )
            edges.append(
                _trace_edge(
                    "contains",
                    plan_node_id,
                    mission_node_id,
                    criterion_ids=criterion_ids,
                )
            )
            for criterion_id in criterion_ids:
                criterion_node_id = criterion_nodes.get(
                    (revision["spec_hash"], criterion_id)
                )
                if criterion_node_id:
                    edges.append(
                        _trace_edge(
                            "owns",
                            mission_node_id,
                            criterion_node_id,
                            criterion_ids=[criterion_id],
                        )
                    )
            for dependency_id in mission.get("depends_on", []):
                dependency_node_id = f"mission_contract:{plan_hash}:{dependency_id}"
                edges.append(
                    _trace_edge("depends_on", mission_node_id, dependency_node_id)
                )

    mission_nodes: dict[str, str] = {}
    for mission in detail["missions"]:
        mission_id = str(mission["id"])
        mission_node_id = f"mission:{mission_id}"
        mission_nodes[mission_id] = mission_node_id
        spec = mission["spec"]
        criterion_ids = [str(item) for item in spec.get("acceptance_criteria", [])]
        nodes.append(
            _trace_node(
                mission_node_id,
                "mission_attempt",
                spec.get("title") or spec.get("goal") or mission["recipient"],
                status=mission["status"],
                timestamp=mission["created_at"],
                entity_id=mission_id,
                data={
                    "attempt": mission["attempt"],
                    "recipient": mission["recipient"],
                    "delegator": mission["delegator"],
                    "plan_mission_id": spec.get("plan_mission_id"),
                    "trace_spec_hash": spec.get("trace_spec_hash"),
                    "trace_plan_hash": spec.get("trace_plan_hash"),
                    "last_rejection": mission["last_rejection"],
                },
            )
        )
        edges.append(_trace_edge("contains", run_node_id, mission_node_id))
        contract_node_id = mission_contract_nodes.get(
            (
                str(spec.get("trace_plan_hash") or ""),
                str(spec.get("plan_mission_id") or ""),
            )
        )
        if contract_node_id:
            edges.append(_trace_edge("executes", mission_node_id, contract_node_id))
        for criterion_id in criterion_ids:
            criterion_node_id = criterion_nodes.get(
                (str(spec.get("trace_spec_hash") or ""), criterion_id)
            )
            if criterion_node_id:
                edges.append(
                    _trace_edge(
                        "owns",
                        mission_node_id,
                        criterion_node_id,
                        criterion_ids=[criterion_id],
                    )
                )

    for evidence in detail["evidence"]:
        evidence_id = str(evidence["id"])
        evidence_node_id = f"evidence:{evidence_id}"
        criterion_ids = [str(item) for item in evidence["criterion_ids"]]
        nodes.append(
            _trace_node(
                evidence_node_id,
                "evidence",
                f"{evidence['kind']} · {evidence['result']}",
                status=evidence["result"],
                timestamp=evidence["created_at"],
                entity_id=evidence_id,
                data={
                    "kind": evidence["kind"],
                    "producer": evidence["producer"],
                    "summary": evidence["summary"],
                    "spec_hash": evidence["spec_hash"],
                    "revision": evidence["revision"],
                    "artifact_hash": evidence["artifact_hash"],
                },
            )
        )
        edges.append(_trace_edge("contains", run_node_id, evidence_node_id))
        delegation_task_id = evidence["delegation_task_id"]
        mission_node_id = mission_nodes.get(str(delegation_task_id))
        if mission_node_id:
            edges.append(_trace_edge("produced", mission_node_id, evidence_node_id))
        for criterion_id in criterion_ids:
            criterion_node_id = criterion_nodes.get(
                (evidence["spec_hash"], criterion_id)
            )
            if criterion_node_id:
                edges.append(
                    _trace_edge(
                        "supports",
                        evidence_node_id,
                        criterion_node_id,
                        criterion_ids=[criterion_id],
                    )
                )

    for deviation in detail["deviations"]:
        deviation_id = str(deviation["id"])
        deviation_node_id = f"deviation:{deviation_id}"
        criterion_id = deviation["criterion_id"]
        nodes.append(
            _trace_node(
                deviation_node_id,
                "deviation",
                deviation["description"],
                status=deviation["status"],
                timestamp=deviation["created_at"],
                entity_id=deviation_id,
                data={
                    "blocking": deviation["blocking"],
                    "spec_hash": deviation["spec_hash"],
                    "resolution": deviation["resolution"],
                },
            )
        )
        edges.append(_trace_edge("contains", run_node_id, deviation_node_id))
        criterion_node_id = criterion_nodes.get(
            (deviation["spec_hash"], str(criterion_id or ""))
        )
        if criterion_node_id:
            edges.append(
                _trace_edge(
                    "affects",
                    deviation_node_id,
                    criterion_node_id,
                    criterion_ids=[str(criterion_id)],
                )
            )

    if detail["convergence"]:
        convergence_node_id = f"convergence:{run_id}"
        nodes.append(
            _trace_node(
                convergence_node_id,
                "convergence",
                "Convergence report",
                status="passed",
                timestamp=detail["convergence"].get("converged_at"),
                entity_id=run_id,
                data=detail["convergence"],
            )
        )
        edges.append(_trace_edge("converged_as", run_node_id, convergence_node_id))

    return nodes, list({edge["id"]: edge for edge in edges}.values())


async def run_detail(db: AsyncSession, run_id: str | UUID) -> dict[str, Any]:
    run = await get_run(db, run_id)
    revisions = list(
        (
            await db.exec(
                select(TraceSpecRevision)
                .where(TraceSpecRevision.run_id == run.id)
                .order_by(col(TraceSpecRevision.version).asc())
            )
        ).all()
    )
    plan_revisions = list(
        (
            await db.exec(
                select(TracePlanRevision)
                .where(TracePlanRevision.run_id == run.id)
                .order_by(col(TracePlanRevision.version).asc())
            )
        ).all()
    )
    missions = list(
        (
            await db.exec(
                select(DelegationTask)
                .where(DelegationTask.trace_run_id == run.id)
                .order_by(col(DelegationTask.created_at).asc())
            )
        ).all()
    )
    repository_missions = _REPOSITORY_MISSIONS.get(run.id, [])
    if repository_missions:
        by_id = {item.id: item for item in missions}
        for raw in repository_missions:
            try:
                mission = DelegationTask.model_validate(raw)
            except (TypeError, ValueError):
                continue
            by_id[mission.id] = mission
        missions = sorted(by_id.values(), key=lambda item: item.created_at)
    evidence = list(
        (
            await db.exec(
                select(TraceEvidence)
                .where(TraceEvidence.run_id == run.id)
                .order_by(col(TraceEvidence.created_at).asc())
            )
        ).all()
    )
    deviations = list(
        (
            await db.exec(
                select(TraceDeviation)
                .where(TraceDeviation.run_id == run.id)
                .order_by(col(TraceDeviation.created_at).asc())
            )
        ).all()
    )
    active_revision = next(
        (item for item in revisions if item.id == run.active_spec_revision_id), None
    )
    active_plan_revision = next(
        (item for item in plan_revisions if item.id == run.active_plan_revision_id),
        None,
    )
    matrix: list[dict[str, Any]] = []
    specification: TraceSpecification | None = None
    if active_revision is not None:
        specification = TraceSpecification.model_validate(active_revision.spec)
        matrix = _criterion_matrix(
            specification,
            spec_hash=active_revision.content_hash,
            evidence=evidence,
            missions=missions,
        )
    action_revision = active_revision or next(
        (item for item in reversed(revisions) if item.status == "draft"), None
    )
    if specification is None and action_revision is not None:
        specification = TraceSpecification.model_validate(action_revision.spec)
    action_plan_revision = active_plan_revision or next(
        (item for item in reversed(plan_revisions) if item.status == "draft"), None
    )
    plan = (
        TracePlan.model_validate(action_plan_revision.plan)
        if action_plan_revision is not None
        else None
    )
    detail = {
        "run": serialize_run(run),
        "revisions": [serialize_revision(item) for item in revisions],
        "active_spec": serialize_revision(active_revision) if active_revision else None,
        "plan_revisions": [serialize_plan_revision(item) for item in plan_revisions],
        "active_plan": (
            serialize_plan_revision(active_plan_revision)
            if active_plan_revision
            else None
        ),
        "criteria": matrix,
        "missions": [serialize_mission(item) for item in missions],
        "evidence": [serialize_evidence(item) for item in evidence],
        "deviations": [serialize_deviation(item) for item in deviations],
        "convergence": run.convergence_report,
    }
    detail["action_rail"] = _run_action_rail(
        run=run,
        specification=specification,
        plan=plan,
        detail=detail,
    )
    return detail


def read_run_trace_events(
    workspace: str,
    run_id: str | UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Read repository-owned trace events outside a database transaction."""

    try:
        return EasdRepositoryStore(workspace).read_events(run_id)
    except EasdStoreError as exc:
        return [], [{"code": "events_unavailable", "message": str(exc)}]


def read_run_repository_state(
    workspace: str,
    run_id: str | UUID,
) -> dict[str, Any]:
    try:
        stored = EasdRepositoryStore(workspace).load_run(run_id).run
    except EasdStoreError as exc:
        raise TraceConflict(f"EASD repository state is unavailable: {exc}") from exc
    return {
        "store_generation": int(stored.get("store_generation") or 0),
        "document_hash": str(stored.get("document_hash") or ""),
    }


def register_run_repository_state(
    run_id: str | UUID,
    state: dict[str, Any],
) -> None:
    normalized = _uuid(str(run_id), label="EASD run ID")
    _REPOSITORY_RUN_GENERATIONS[normalized] = int(state.get("store_generation") or 0)
    _REPOSITORY_RUN_HASHES[normalized] = str(state.get("document_hash") or "")


def _trace_events(
    detail: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    run_node_id = f"run:{detail['run']['id']}"
    spec_drafts = [
        item
        for item in detail["revisions"]
        if item["status"] in {"draft", "accepted", "superseded"}
    ]
    accepted_specs = [item for item in detail["revisions"] if item["accepted_at"]]
    plan_drafts = [
        item
        for item in detail["plan_revisions"]
        if item["status"] in {"draft", "accepted", "superseded"}
    ]
    accepted_plans = [item for item in detail["plan_revisions"] if item["accepted_at"]]
    draft_spec_index = 0
    accepted_spec_index = 0
    draft_plan_index = 0
    accepted_plan_index = 0
    output: list[dict[str, Any]] = []
    known = {
        "id",
        "run_id",
        "sequence",
        "event",
        "actor",
        "created_at",
        "from_status",
        "to_status",
        "entity_refs",
        "document_hash",
        "run_document_hash",
    }
    for raw in events:
        event_name = str(raw["event"])
        refs = [str(item) for item in raw.get("entity_refs", []) if str(item)]
        if run_node_id not in refs:
            refs.insert(0, run_node_id)
        if event_name == "specification_draft_created" and draft_spec_index < len(
            spec_drafts
        ):
            refs.append(f"spec:{spec_drafts[draft_spec_index]['id']}")
            draft_spec_index += 1
        elif event_name == "specification_accepted" and accepted_spec_index < len(
            accepted_specs
        ):
            refs.append(f"spec:{accepted_specs[accepted_spec_index]['id']}")
            accepted_spec_index += 1
        elif event_name == "plan_draft_created" and draft_plan_index < len(plan_drafts):
            refs.append(f"plan:{plan_drafts[draft_plan_index]['id']}")
            draft_plan_index += 1
        elif event_name == "plan_accepted" and accepted_plan_index < len(
            accepted_plans
        ):
            refs.append(f"plan:{accepted_plans[accepted_plan_index]['id']}")
            accepted_plan_index += 1
        output.append(
            {
                "id": str(raw["id"]),
                "sequence": int(raw["sequence"]),
                "event": event_name,
                "actor": raw.get("actor"),
                "created_at": raw.get("created_at"),
                "from_status": raw.get("from_status"),
                "to_status": raw.get("to_status"),
                "entity_refs": list(dict.fromkeys(refs)),
                "data": {key: value for key, value in raw.items() if key not in known},
            }
        )
    return output


def build_run_trace(
    detail: dict[str, Any],
    *,
    events: list[dict[str, Any]],
    diagnostics: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the provider-neutral graph used by Trace, Recovery, and Realtime."""

    nodes, edges = _trace_projection(detail)
    gaps = [
        {"action_id": action["id"], **blocker}
        for action in detail["action_rail"]["actions"]
        if action["state"] == "blocked"
        for blocker in action["blockers"]
    ]
    trace = {
        "version": 1,
        "run_id": str(detail["run"]["id"]),
        "store_generation": detail["run"].get("store_generation"),
        "nodes": nodes,
        "edges": edges,
        "events": _trace_events(detail, events),
        "gaps": gaps,
        "diagnostics": diagnostics,
    }
    logger.info(
        "trace_projection_built nodes={} edges={} events={} diagnostics={}",
        len(nodes),
        len(edges),
        len(events),
        len(diagnostics),
    )
    return trace


def _recovery_action(
    action_id: str,
    label: str,
    summary: str,
    *,
    from_status: str,
    to_status: str,
    prompt_phase: str,
    reuses: list[str],
    preserves: list[str],
) -> dict[str, Any]:
    return {
        "id": action_id,
        "label": label,
        "summary": summary,
        "from_status": from_status,
        "to_status": to_status,
        "prompt_phase": prompt_phase,
        "reuses": reuses,
        "preserves": preserves,
    }


async def recovery_preview(db: AsyncSession, run_id: str | UUID) -> dict[str, Any]:
    detail = await run_detail(db, run_id)
    run = detail["run"]
    status = run["status"]
    spec = detail["active_spec"] or next(
        (item for item in reversed(detail["revisions"]) if item["status"] == "draft"),
        None,
    )
    plan = detail["active_plan"] or next(
        (
            item
            for item in reversed(detail["plan_revisions"])
            if item["status"] == "draft"
        ),
        None,
    )
    reuses = [
        value
        for value in (
            f"Specification revision v{spec['version']}" if spec else None,
            f"Plan revision v{plan['version']}" if plan else None,
            f"Coding session {run['session_id']}" if run["session_id"] else None,
        )
        if value
    ]
    common_preserves = [
        "Prior revisions and attempts",
        "Existing evidence and deviations",
        "Append-only Trace events",
    ]
    actions: list[dict[str, Any]] = []
    if status == "authoring":
        actions.append(
            _recovery_action(
                "retry_specification",
                "Retry specification drafting",
                "Repeat the interrupted Specify attempt in the same Coding session.",
                from_status=status,
                to_status="authoring",
                prompt_phase="authoring",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "draft":
        actions.append(
            _recovery_action(
                "redraft_specification",
                "Redraft specification",
                "Return to Specify; the current draft stays durable until its replacement is persisted.",
                from_status=status,
                to_status="authoring",
                prompt_phase="authoring",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "planning":
        actions.append(
            _recovery_action(
                "retry_planning",
                "Retry planning",
                "Repeat the interrupted Plan attempt against the accepted Spec.",
                from_status=status,
                to_status="planning",
                prompt_phase="planning",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "plan_review":
        actions.append(
            _recovery_action(
                "replan",
                "Replan",
                "Return to Plan; the current Plan draft stays durable until replacement persistence.",
                from_status=status,
                to_status="planning",
                prompt_phase="planning",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "active":
        actions.append(
            _recovery_action(
                "retry_implementation",
                "Retry implementation",
                "Resume the accepted implementation contract and inspect existing mission attempts before redispatch.",
                from_status=status,
                to_status="active",
                prompt_phase="implementation",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "reviewing":
        actions.append(
            _recovery_action(
                "retry_review",
                "Rerun review",
                "Repeat read-only Review and append fresh review evidence without deleting prior findings.",
                from_status=status,
                to_status="reviewing",
                prompt_phase="review",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    elif status == "verifying":
        actions.append(
            _recovery_action(
                "retry_verification",
                "Rerun verification",
                "Repeat accepted Proof commands and append fresh machine evidence.",
                from_status=status,
                to_status="verifying",
                prompt_phase="verification",
                reuses=reuses,
                preserves=common_preserves,
            )
        )
    unavailable_reason = None
    if not actions:
        unavailable_reason = (
            "Converged Runs are immutable; create a new Run for additional work."
            if status == "converged"
            else f"No safe recovery action is available while the Run is {status}."
        )
    return {
        "run_id": str(run["id"]),
        "store_generation": run.get("store_generation"),
        "actions": actions,
        "unavailable_reason": unavailable_reason,
    }


async def recover_run_in_session(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    action_id: str,
    session_id: str | UUID,
    expected_generation: int | None,
) -> tuple[TraceRun, dict[str, Any]]:
    preview = await recovery_preview(db, run_id)
    action = next(
        (item for item in preview["actions"] if item["id"] == action_id),
        None,
    )
    if action is None:
        raise TraceConflict(f"Recovery action {action_id} is not available")
    actual_generation = preview["store_generation"]
    if actual_generation != expected_generation:
        raise TraceConflict(
            "EASD repository generation changed; refresh Recovery before retrying"
        )
    run = await get_run(db, run_id)
    session = await _session_for_run(db, run, session_id)
    from_status = run.status
    if action_id == "redraft_specification":
        run = await retry_spec_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
    elif action_id == "replan":
        run = await retry_plan_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
    else:
        event_by_action = {
            "retry_specification": "specification_authoring_retried",
            "retry_planning": "planning_retried",
            "retry_implementation": "implementation_retried",
            "retry_review": "review_retried",
            "retry_verification": "verification_retried",
        }
        event = event_by_action.get(action_id)
        if event is None:
            raise TraceValidationError(f"Unknown EASD recovery action: {action_id}")
        run.updated_at = _utcnow()
        db.add(run)
        await db.flush()
        detail = await run_detail(db, run.id)
        _queue_run_state(
            db,
            run,
            from_status=from_status,
            event=event,
            actor="human",
            delivery_flow=(
                detail["active_spec"]["spec"].get("delivery_flow")
                if detail["active_spec"]
                else None
            ),
            event_data={
                "recovery_action": action_id,
                "session_id": str(session.id),
                "spec_hash": (
                    detail["active_spec"]["content_hash"]
                    if detail["active_spec"]
                    else None
                ),
                "plan_hash": (
                    detail["active_plan"]["content_hash"]
                    if detail["active_plan"]
                    else None
                ),
            },
        )
    recovery = {
        **action,
        "recorded_at": _utcnow().isoformat(),
        "session_id": str(session.id),
    }
    TRACE_OPERATIONS.labels(
        operation="recovery",
        status="ok",
        risk_tier=run.risk_tier,
    ).inc()
    return run, recovery


async def converge_run(
    db: AsyncSession,
    *,
    run_id: str | UUID,
    git_revision: str | None,
) -> dict[str, Any]:
    context = await active_context(db, run_id)
    plan_context = (
        await active_plan_context(db, run_id)
        if context.specification.delivery_flow.mode == "planned"
        else None
    )
    if context.run.status == "converged":
        if isinstance(context.run.convergence_report, dict):
            return dict(context.run.convergence_report)
        raise TraceConflict("Converged EASD run has no persisted report")
    if context.run.status != "verifying":
        raise TraceConflict(f"Cannot converge a {context.run.status} EASD run")
    detail = await run_detail(db, context.run.id)
    criteria = detail["criteria"]
    missions = detail["missions"]
    deviations = detail["deviations"]
    reasons = _convergence_reasons(
        detail=detail,
        specification=context.specification,
        independent_required=bool(plan_context and plan_context.plan.review_required),
    )
    if reasons:
        convergence_reasons = [
            {key: value for key, value in reason.items() if key != "message"}
            for reason in reasons
        ]
        logger.info(
            "trace_convergence_rejected run_id={} reasons={}",
            context.run.id,
            len(convergence_reasons),
        )
        TRACE_OPERATIONS.labels(
            operation="converge",
            status="rejected",
            risk_tier=context.run.risk_tier,
        ).inc()
        raise TraceConvergenceError(convergence_reasons)

    now = _utcnow()
    report = {
        "run_id": str(context.run.id),
        "spec_revision_id": str(context.revision.id),
        "spec_hash": context.revision.content_hash,
        "plan_revision_id": (
            str(plan_context.plan_revision.id) if plan_context is not None else None
        ),
        "plan_hash": (
            plan_context.plan_revision.content_hash
            if plan_context is not None
            else None
        ),
        "delivery_flow": context.specification.delivery_flow.model_dump(mode="json"),
        "git_revision": git_revision,
        "criteria": {
            "total": len(criteria),
            "passed": sum(item["status"] == "passed" for item in criteria),
            "waived": sum(item["status"] == "waived" for item in criteria),
        },
        "missions": {
            "total": len(missions),
            "completed": sum(item["status"] == "completed" for item in missions),
            "cancelled": sum(item["status"] == "cancelled" for item in missions),
        },
        "evidence_ids": [item["id"] for item in detail["evidence"]],
        "deviation_ids": [item["id"] for item in deviations],
        "converged_at": now.isoformat(),
    }
    context.run.status = "converged"
    context.run.convergence_report = report
    context.run.converged_at = now
    context.run.updated_at = now
    db.add(context.run)
    await db.flush()
    enqueue_convergence(
        db,
        workspace=context.run.workspace,
        run_id=str(context.run.id),
        report=report,
    )
    _queue_run_state(
        db,
        context.run,
        from_status="verifying",
        event="run_converged",
        actor="human",
        delivery_flow=context.specification.delivery_flow.model_dump(mode="json"),
    )
    logger.info(
        "trace_run_converged run_id={} criteria={} evidence={}",
        context.run.id,
        len(criteria),
        len(detail["evidence"]),
    )
    TRACE_OPERATIONS.labels(
        operation="converge", status="ok", risk_tier=context.run.risk_tier
    ).inc()
    return report


def serialize_run(row: TraceRun) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "project_id": str(row.project_id) if row.project_id else None,
        "workspace": row.workspace,
        "session_id": str(row.session_id) if row.session_id else None,
        "title": row.title,
        "intent": row.intent,
        "status": row.status,
        "risk_tier": row.risk_tier,
        "active_spec_revision_id": (
            str(row.active_spec_revision_id) if row.active_spec_revision_id else None
        ),
        "active_plan_revision_id": (
            str(row.active_plan_revision_id) if row.active_plan_revision_id else None
        ),
        "convergence_report": row.convergence_report,
        "converged_at": row.converged_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "compact_before_run": row.compact_before_run,
        "auto_pilot": row.auto_pilot,
        "repository_document_hash": _REPOSITORY_RUN_HASHES.get(row.id),
        "store_generation": _REPOSITORY_RUN_GENERATIONS.get(row.id),
    }


def serialize_revision(row: TraceSpecRevision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "version": row.version,
        "status": row.status,
        "spec": row.spec,
        "authoring": row.authoring,
        "content_hash": row.content_hash,
        "created_at": row.created_at,
        "accepted_at": row.accepted_at,
    }


def serialize_plan_revision(row: TracePlanRevision) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "version": row.version,
        "status": row.status,
        "spec_hash": row.spec_hash,
        "plan": row.plan,
        "authoring": row.authoring,
        "content_hash": row.content_hash,
        "created_at": row.created_at,
        "accepted_at": row.accepted_at,
    }


def serialize_mission(row: DelegationTask) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "trace_run_id": str(row.trace_run_id) if row.trace_run_id else None,
        "lead_session_id": str(row.lead_session_id),
        "delegator": row.delegator,
        "recipient": row.recipient,
        "status": row.status,
        "spec": row.spec,
        "dependencies": row.dependencies,
        "attempt": row.attempt,
        "deadline_at": row.deadline_at,
        "dispatched_at": row.dispatched_at,
        "completed_at": row.completed_at,
        "result": row.result,
        "last_rejection": row.last_rejection,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_evidence(row: TraceEvidence) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "delegation_task_id": (
            str(row.delegation_task_id) if row.delegation_task_id else None
        ),
        "spec_hash": row.spec_hash,
        "criterion_ids": row.criterion_ids,
        "producer": row.producer,
        "kind": row.kind,
        "result": row.result,
        "summary": row.summary,
        "revision": row.revision,
        "artifact_hash": row.artifact_hash,
        "payload": row.payload,
        "source_key": row.source_key,
        "created_at": row.created_at,
    }


def serialize_deviation(row: TraceDeviation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "spec_hash": row.spec_hash,
        "criterion_id": row.criterion_id,
        "delegation_task_id": (
            str(row.delegation_task_id) if row.delegation_task_id else None
        ),
        "status": row.status,
        "blocking": row.blocking,
        "description": row.description,
        "proposed_change": row.proposed_change,
        "resolution": row.resolution,
        "resolved_spec_hash": row.resolved_spec_hash,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "resolved_at": row.resolved_at,
    }


def _stable_payload(value: dict[str, Any]) -> str:
    """Serialize a payload deterministically for idempotency checks."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


__all__ = [
    "TraceConflict",
    "TraceConvergenceError",
    "TraceError",
    "TraceNotFound",
    "TraceValidationError",
    "accept_revision",
    "accept_plan_revision",
    "active_context",
    "active_plan_context",
    "active_run_for_session",
    "preimplementation_run_for_session",
    "converge_run",
    "create_deviation",
    "create_evidence",
    "create_revision",
    "create_run",
    "create_intent_run",
    "create_plan_revision",
    "get_run",
    "list_runs",
    "resolve_deviation",
    "retry_plan_authoring_in_session",
    "retry_spec_authoring_in_session",
    "record_mission_handoff_evidence",
    "record_mission_binding",
    "run_detail",
    "serialize_deviation",
    "serialize_evidence",
    "serialize_plan_revision",
    "serialize_revision",
    "serialize_run",
    "start_run_in_session",
    "start_plan_authoring_in_session",
    "start_review_in_session",
    "start_spec_authoring_in_session",
    "start_verification_in_session",
    "submit_authored_specification",
    "submit_authored_plan",
    "submit_review_evidence",
    "validate_mission_binding",
]
