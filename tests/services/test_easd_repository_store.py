from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.easd_repository_store import (
    EasdRepositoryStore,
    EasdStoreConflict,
    document_hash,
)
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    initialize_repositories,
)
from app.models.chat import ChatSession
from app.models.team import DelegationTask
from app.services import trace_service
from app.services.trace_contracts import TraceSpecification


def _store(tmp_path, data_directory: str = "documents/easd") -> EasdRepositoryStore:
    initialize_repositories(
        [EasdRepositoryTarget(path=str(tmp_path), name=tmp_path.name)],
        data_directory=data_directory,
    )
    return EasdRepositoryStore(tmp_path)


def test_repository_store_persists_complete_diffable_run_structure(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    stored = store.create_run(
        run={
            "id": str(run_id),
            "title": "Repository source of truth",
            "status": "intent",
            "risk_tier": "standard",
            "created_at": "2026-08-24T00:00:00Z",
            "updated_at": "2026-08-24T00:00:00Z",
        },
        intent={
            "title": "Repository source of truth",
            "problem": "Local SQLite state cannot be shared through Git.",
            "outcome": "Every normative EASD artifact is repository-owned.",
        },
    )

    assert stored.directory.parent == tmp_path / "documents" / "easd" / "runs"
    assert stored.directory.name.endswith(f"--{run_id}")
    assert (stored.directory / "run.yaml").is_file()
    assert (stored.directory / "intent.yaml").is_file()
    assert len(list((stored.directory / "events").glob("000001-*.yaml"))) == 1
    assert set(path.name for path in stored.directory.iterdir()) >= {
        "specifications",
        "plans",
        "missions",
        "reviews",
        "verifications",
        "evidence",
        "deviations",
        "events",
    }


def test_repository_store_rejects_stale_run_write(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    original = store.create_run(
        run={"id": str(run_id), "title": "CAS", "status": "intent"},
        intent={"title": "CAS", "problem": "stale writes"},
    ).run
    original_hash = document_hash(original)
    updated = store.update_run(
        run_id,
        {**original, "status": "authoring"},
        expected_hash=original_hash,
        event={
            "event": "authoring_started",
            "from_status": "intent",
            "to_status": "authoring",
            "actor": "human",
        },
    )

    with pytest.raises(EasdStoreConflict, match="reload and review"):
        store.update_run(
            run_id,
            {**updated, "status": "draft"},
            expected_hash=original_hash,
        )

    assert store.load_run(run_id).run["status"] == "authoring"
    assert store.load_run(run_id).run["store_generation"] == 2


def test_repository_store_keeps_immutable_revisions_and_append_only_evidence(
    tmp_path,
):
    store = _store(tmp_path)
    run_id = uuid4()
    store.create_run(
        run={"id": str(run_id), "title": "Immutable", "status": "draft"},
        intent={"title": "Immutable", "problem": "contracts can drift"},
    )
    revision_id = uuid4()
    revision = store.write_revision(
        run_id,
        kind="specifications",
        version=1,
        payload={
            "id": str(revision_id),
            "run_id": str(run_id),
            "version": 1,
            "status": "draft",
            "content_hash": "a" * 64,
            "spec": {"title": "Immutable"},
        },
    )
    with pytest.raises(EasdStoreConflict, match="already exists"):
        store.write_revision(
            run_id,
            kind="specifications",
            version=1,
            payload=revision,
        )
    accepted = store.replace_revision(
        run_id,
        kind="specifications",
        version=1,
        payload={**revision, "status": "accepted"},
        expected_hash=document_hash(revision),
    )
    with pytest.raises(EasdStoreConflict, match="immutable"):
        store.replace_revision(
            run_id,
            kind="specifications",
            version=1,
            payload={**accepted, "status": "superseded"},
            expected_hash=document_hash(accepted),
        )

    evidence_id = uuid4()
    store.append_artifact(
        run_id,
        "evidence",
        evidence_id,
        {
            "id": str(evidence_id),
            "run_id": str(run_id),
            "kind": "machine",
            "result": "passed",
        },
    )

    assert len(store.read_revisions(run_id, "specifications")) == 1
    assert len(store.read_artifacts(run_id, "evidence")) == 1


@pytest.mark.asyncio
async def test_easd_mission_status_is_projected_after_each_commit(tmp_path, setup_db):
    from app.core.db import async_session_factory

    initialize_repositories(
        [EasdRepositoryTarget(path=str(tmp_path), name=tmp_path.name)]
    )
    specification = TraceSpecification.model_validate(
        {
            "title": "Shared mission status",
            "problem": "Mission state exists only on one machine.",
            "outcome": "Git collaborators can inspect the latest mission status.",
            "impact_targets": [
                {
                    "repository": tmp_path.name,
                    "path": "app/service.py",
                    "reason": "Owned direct-flow change",
                }
            ],
            "delivery_flow": {
                "mode": "direct",
                "rationale": "One low-risk repository boundary.",
                "confidence": 0.95,
                "required_by": [],
            },
            "criteria": [{"id": "AC-1", "statement": "Status is shared."}],
        }
    )
    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier="standard",
            specification=specification,
            session_id=session.id,
        )
        await db.commit()
        async with async_session_factory() as next_db:
            draft = (await trace_service.run_detail(next_db, run.id))["revisions"][0]
            await trace_service.accept_revision(
                next_db,
                run_id=run.id,
                revision_id=draft["id"],
                expected_hash=draft["content_hash"],
            )
            await next_db.commit()
        task = DelegationTask(
            lead_session_id=session.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="coder#1",
            status="pending",
            spec={
                "trace_run_id": str(run.id),
                "trace_spec_hash": draft["content_hash"],
                "acceptance_criteria": ["AC-1"],
                "_easd_owner_workspace": str(tmp_path),
            },
        )
        db.add(task)
        await db.commit()

    store = EasdRepositoryStore(tmp_path)
    assert store.read_artifacts(run.id, "missions")[0]["status"] == "pending"

    async with async_session_factory() as db:
        persisted = await db.get(DelegationTask, task.id)
        assert persisted is not None
        persisted.status = "completed"
        db.add(persisted)
        await db.commit()

    assert store.read_artifacts(run.id, "missions")[0]["status"] == "completed"
