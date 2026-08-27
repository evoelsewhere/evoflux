from __future__ import annotations

import os
import shutil
from uuid import uuid4

import pytest
import yaml

from app.services.easd_repository_store import (
    EasdRepositoryStore,
    EasdStoreConflict,
    document_hash,
)
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    initialize_repositories,
    localize_legacy_runs,
    preview_runtime_migration,
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

    assert stored.directory.parent == tmp_path / ".evoflux" / "easd" / ".local" / "runs"
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


def test_repository_store_reads_and_explicitly_localizes_legacy_runs(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    store = _store(tmp_path)
    run_id = uuid4()
    stored = store.create_run(
        run={"id": str(run_id), "title": "Legacy Run", "status": "intent"},
        intent={"title": "Legacy Run", "problem": "Git-visible runtime noise"},
    )
    legacy_root = tmp_path / "documents" / "easd" / "runs"
    legacy_root.mkdir(parents=True)
    legacy_directory = legacy_root / stored.directory.name
    os.replace(stored.directory, legacy_directory)

    compatible = EasdRepositoryStore(tmp_path)
    assert compatible.load_run(run_id).directory == legacy_directory
    preview = preview_runtime_migration([target])[0]
    assert preview["legacy_run_count"] == 1
    assert preview["runs"][0]["run_id"] == str(run_id)

    result = localize_legacy_runs([target])[0]

    assert result["moved_run_count"] == 1
    localized = EasdRepositoryStore(tmp_path).load_run(run_id)
    assert (
        localized.directory.parent == tmp_path / ".evoflux" / "easd" / ".local" / "runs"
    )
    assert not legacy_directory.exists()


def test_repository_store_rejects_duplicate_local_and_legacy_run_identity(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    stored = store.create_run(
        run={"id": str(run_id), "title": "Duplicate", "status": "intent"},
        intent={"title": "Duplicate", "problem": "Ambiguous source of truth"},
    )
    legacy = tmp_path / "documents" / "easd" / "runs" / stored.directory.name
    shutil.copytree(stored.directory, legacy)

    duplicate = EasdRepositoryStore(tmp_path)
    with pytest.raises(EasdStoreConflict, match="local and legacy"):
        duplicate.load_run(run_id)
    with pytest.raises(EasdStoreConflict, match="local and legacy"):
        duplicate.list_runs()


def test_repository_store_reads_valid_events_around_a_malformed_sibling(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    stored = store.create_run(
        run={"id": str(run_id), "title": "Trace events", "status": "intent"},
        intent={"title": "Trace events", "problem": "Need ordered history"},
    )
    (stored.directory / "events" / "000002-invalid.yaml").write_text(
        "sequence: not-an-integer\nevent: [",
        encoding="utf-8",
    )
    store.append_event(
        run_id,
        {"event": "authoring_started", "actor": "human"},
    )

    events, diagnostics = store.read_events(run_id)

    assert [item["event"] for item in events] == [
        "intent_created",
        "authoring_started",
    ]
    assert diagnostics[0]["code"] == "event_document_invalid"
    assert "000002-invalid.yaml" in diagnostics[0]["message"]


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
    events, diagnostics = store.read_events(run_id)
    assert diagnostics == []
    assert events[-1]["repository_generation"] == 2


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
    published_index = store.publish_spec_revision(run_id, accepted)
    published = store.load_published_spec(run_id)
    repeated_index = store.publish_spec_revision(run_id, accepted)

    assert published_index["current_revision"] == 1
    assert repeated_index["current_hash"] == "a" * 64
    assert published["index"]["current_hash"] == "a" * 64
    assert published["revision"]["content_hash"] == "a" * 64
    assert "run_snapshot" not in published["revision"]
    assert published["directory"].parent == (tmp_path / "documents" / "easd" / "specs")
    with pytest.raises(EasdStoreConflict, match="immutable"):
        store.replace_revision(
            run_id,
            kind="specifications",
            version=1,
            payload={**accepted, "status": "superseded"},
            expected_hash=document_hash(accepted),
        )
    with pytest.raises(EasdStoreConflict, match="conflicts"):
        store.publish_spec_revision(
            run_id,
            {**accepted, "content_hash": "b" * 64},
        )

    second = store.write_revision(
        run_id,
        kind="specifications",
        version=2,
        payload={
            **revision,
            "id": str(uuid4()),
            "version": 2,
            "content_hash": "b" * 64,
        },
    )
    accepted_second = store.replace_revision(
        run_id,
        kind="specifications",
        version=2,
        payload={**second, "status": "accepted"},
        expected_hash=document_hash(second),
    )
    store.publish_spec_revision(run_id, accepted_second)
    current_publication = store.load_published_spec(run_id)
    assert current_publication["index"]["current_revision"] == 2
    assert current_publication["revision"]["content_hash"] == "b" * 64
    first_publication = current_publication["directory"] / "revisions" / "0001.yaml"
    assert first_publication.is_file()
    assert document_hash(yaml.safe_load(first_publication.read_text())) == (
        document_hash(published["revision"])
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

    assert len(store.read_revisions(run_id, "specifications")) == 2
    assert len(store.read_artifacts(run_id, "evidence")) == 1


def test_converged_run_publication_is_compact_redacted_and_idempotent(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    report = {
        "run_id": str(run_id),
        "spec_revision_id": str(uuid4()),
        "spec_hash": "a" * 64,
        "plan_revision_id": str(uuid4()),
        "plan_hash": "b" * 64,
        "git_revision": "abc1234",
        "criteria": {"total": 2, "passed": 2, "waived": 0},
        "missions": {"total": 3, "completed": 3, "cancelled": 0},
        "evidence_ids": [str(uuid4())],
        "deviation_ids": [],
        "converged_at": "2026-08-27T00:00:00Z",
    }
    store.create_run(
        run={
            "id": str(run_id),
            "title": "Compact publication",
            "status": "converged",
            "risk_tier": "standard",
            "owner_repository": "backend",
            "workspace": "/private/source/path",
            "spec_catalog_index": f"specs/compact--{run_id}/index.yaml",
            "convergence_report": {**report, "raw_evidence": "must-not-publish"},
            "converged_at": report["converged_at"],
        },
        intent={
            "title": "Compact publication",
            "problem": "Local evidence should not leak",
        },
    )
    store.write_convergence(run_id, {**report, "raw_evidence": "must-not-publish"})

    preview = store.preview_convergence_publication(run_id)
    first = store.publish_convergence_record(run_id)
    repeated = store.publish_convergence_record(run_id)

    assert preview["eligible"] is True
    assert preview["published"] is False
    assert first["created"] is True
    assert repeated["created"] is False
    assert first["path"].startswith("documents/easd/records/runs/")
    published_text = (tmp_path / first["path"]).read_text(encoding="utf-8")
    assert "/private/source/path" not in published_text
    assert "must-not-publish" not in published_text
    assert "evidence_ids" in published_text


def test_non_converged_run_cannot_publish(tmp_path):
    store = _store(tmp_path)
    run_id = uuid4()
    store.create_run(
        run={"id": str(run_id), "title": "Still active", "status": "active"},
        intent={"title": "Still active", "problem": "Not done"},
    )

    assert store.preview_convergence_publication(run_id)["eligible"] is False
    with pytest.raises(EasdStoreConflict, match="Only a converged"):
        store.publish_convergence_record(run_id)


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
    published = store.load_published_spec(run.id)
    assert published["index"]["current_hash"] == draft["content_hash"]
    assert (
        store.load_run(run.id)
        .run["spec_catalog_index"]
        .endswith(f"--{run.id}/index.yaml")
    )
    assert store.read_artifacts(run.id, "missions")[0]["status"] == "pending"

    async with async_session_factory() as db:
        persisted = await db.get(DelegationTask, task.id)
        assert persisted is not None
        persisted.status = "completed"
        db.add(persisted)
        await db.commit()

    assert store.read_artifacts(run.id, "missions")[0]["status"] == "completed"
