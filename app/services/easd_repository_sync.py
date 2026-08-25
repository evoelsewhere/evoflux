"""Post-transaction projection from local runtime state to the EASD repo store.

The repository projection is the collaborative contract. SQLite rows are a
rebuildable local runtime index while the current migration path is active.
Filesystem work runs only after commit, never inside a database transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.team import DelegationTask
from app.services.easd_repository_store import EasdRepositoryStore, document_hash
from app.services.easd_setup_service import EASD_MANIFEST

_CALLBACKS = "easd_repository_after_commit"
_INSTALLED = False


def _install_events() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @event.listens_for(Session, "before_commit")
    def _capture_mission_snapshots(session: Session) -> None:
        candidates = {
            id(item): item
            for item in (*session.new, *session.dirty)
            if isinstance(item, DelegationTask)
            and item.trace_run_id is not None
            and isinstance(item.spec, dict)
            and isinstance(item.spec.get("_easd_owner_workspace"), str)
        }
        for task in candidates.values():
            workspace = str(task.spec["_easd_owner_workspace"])
            payload = {
                "id": str(task.id),
                "trace_run_id": str(task.trace_run_id),
                "lead_session_id": str(task.lead_session_id),
                "delegator": task.delegator,
                "recipient": task.recipient,
                "status": task.status,
                "spec": task.spec,
                "dependencies": task.dependencies,
                "attempt": task.attempt,
                "deadline_at": task.deadline_at.isoformat()
                if task.deadline_at
                else None,
                "dispatched_at": (
                    task.dispatched_at.isoformat() if task.dispatched_at else None
                ),
                "completed_at": (
                    task.completed_at.isoformat() if task.completed_at else None
                ),
                "result": task.result,
                "last_rejection": task.last_rejection,
                "created_at": task.created_at.isoformat(),
                "updated_at": task.updated_at.isoformat(),
            }

            def write_mission(
                *,
                owner: str = workspace,
                run_id: str = str(task.trace_run_id),
                task_id: str = str(task.id),
                snapshot: dict[str, Any] = payload,
            ) -> None:
                store = _store_if_initialized(owner)
                if store is not None:
                    store.upsert_artifact(
                        run_id,
                        "missions",
                        task_id,
                        snapshot,
                    )

            session.info.setdefault(_CALLBACKS, []).append(write_mission)

    @event.listens_for(Session, "after_commit")
    def _after_commit(session: Session) -> None:
        callbacks = list(session.info.pop(_CALLBACKS, []))
        for callback in callbacks:
            callback()

    @event.listens_for(Session, "after_rollback")
    def _after_rollback(session: Session) -> None:
        session.info.pop(_CALLBACKS, None)

    _INSTALLED = True


def enqueue(db: AsyncSession, callback: Callable[[], None]) -> None:
    """Run one repository write only after the surrounding DB commit succeeds."""

    _install_events()
    db.sync_session.info.setdefault(_CALLBACKS, []).append(callback)


def _store_if_initialized(workspace: str) -> EasdRepositoryStore | None:
    if not (Path(workspace) / EASD_MANIFEST).is_file():
        return None
    return EasdRepositoryStore(workspace)


def enqueue_run_create(
    db: AsyncSession,
    *,
    workspace: str,
    run: dict[str, Any],
    intent: dict[str, Any] | None,
) -> None:
    run_payload = dict(run)
    intent_payload = dict(intent) if intent is not None else None

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is not None:
            store.create_run(run=run_payload, intent=intent_payload)

    enqueue(db, write)


def enqueue_run_update(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    run: dict[str, Any],
    event_payload: dict[str, Any],
    expected_hash: str | None = None,
) -> None:
    run_payload = dict(run)
    event_copy = dict(event_payload)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is None:
            return
        current = store.load_run(run_id).run
        store.update_run(
            run_id,
            run_payload,
            expected_hash=expected_hash or document_hash(current),
            event=event_copy,
        )

    enqueue(db, write)


def enqueue_revision_create(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    kind: Literal["specifications", "plans"],
    version: int,
    revision: dict[str, Any],
) -> None:
    payload = dict(revision)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is not None:
            store.write_revision(
                run_id,
                kind=kind,
                version=version,
                payload=payload,
            )

    enqueue(db, write)


def enqueue_revision_update(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    kind: Literal["specifications", "plans"],
    version: int,
    revision: dict[str, Any],
) -> None:
    payload = dict(revision)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is None:
            return
        current = next(
            item
            for item in store.read_revisions(run_id, kind)
            if int(item.get("version") or 0) == version
        )
        store.replace_revision(
            run_id,
            kind=kind,
            version=version,
            payload=payload,
            expected_hash=document_hash(current),
        )

    enqueue(db, write)


def enqueue_artifact(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    kind: Literal[
        "missions",
        "reviews",
        "verifications",
        "evidence",
        "deviations",
    ],
    artifact_id: str,
    payload: dict[str, Any],
) -> None:
    artifact = dict(payload)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is not None:
            store.append_artifact(run_id, kind, artifact_id, artifact)

    enqueue(db, write)


def enqueue_artifact_update(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    kind: Literal["missions", "deviations"],
    artifact_id: str,
    payload: dict[str, Any],
) -> None:
    artifact = dict(payload)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is None:
            return
        store.upsert_artifact(run_id, kind, artifact_id, artifact)

    enqueue(db, write)


def enqueue_convergence(
    db: AsyncSession,
    *,
    workspace: str,
    run_id: str,
    report: dict[str, Any],
) -> None:
    payload = dict(report)

    def write() -> None:
        store = _store_if_initialized(workspace)
        if store is not None:
            store.write_convergence(run_id, payload)

    enqueue(db, write)


__all__ = [
    "enqueue_artifact",
    "enqueue_artifact_update",
    "enqueue_convergence",
    "enqueue_revision_create",
    "enqueue_revision_update",
    "enqueue_run_create",
    "enqueue_run_update",
]


_install_events()
