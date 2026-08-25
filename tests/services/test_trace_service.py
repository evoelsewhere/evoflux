from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.chat import ChatSession
from app.models.team import DelegationTask
from app.services import trace_service
from app.services.trace_contracts import TracePlan, TraceSpecification


def _spec(
    *,
    title: str = "EASD feature",
    risk_tier: str = "standard",
    machine_required: bool = True,
) -> TraceSpecification:
    return TraceSpecification.model_validate(
        {
            "title": title,
            "problem": "The feature has no accountable delivery contract.",
            "outcome": "Every required criterion has snapshot-bound evidence.",
            "goals": ["Make completion verifiable"],
            "non_goals": ["Replace the workflow engine"],
            "source_refs": ["docs/plans/trace.md"],
            "impact_targets": [
                {
                    "repository": "backend",
                    "path": "app/services/trace_service.py",
                    "module": "EASD",
                    "reason": "Owns convergence behavior",
                }
            ],
            "constraints": [
                {
                    "kind": "compatibility",
                    "statement": "Preserve the accepted revision hash contract",
                    "source_refs": ["docs/plans/trace.md"],
                }
            ],
            "verification_commands": ["pytest -q tests/services/test_trace_service.py"],
            "risk_tier": risk_tier,
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The implementation has passing machine evidence.",
                    "required": True,
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": machine_required,
                        "minimum_passes": 1,
                    },
                }
            ],
        }
    )


def _plan(specification: TraceSpecification) -> TracePlan:
    target = specification.impact_targets[0]
    missions = [
        {
            "id": "M1",
            "kind": "implementation",
            "title": "Implement accepted criteria",
            "goal": "Implement AC-1 inside accepted scope.",
            "acceptance_criteria": ["AC-1"],
            "target_repositories": [target.repository],
            "target_paths": [target.path],
            "expected_output": "Implementation and evidence.",
        }
    ]
    review_required = specification.risk_tier in {"cross_layer", "critical"}
    missions.append(
        {
            "id": "M2",
            "kind": "review",
            "title": "Review accepted criteria",
            "goal": (
                "Independently review AC-1."
                if review_required
                else "Review AC-1 against the integrated result."
            ),
            "acceptance_criteria": ["AC-1"],
            "target_repositories": [target.repository],
            "target_paths": [target.path],
            "depends_on": ["M1"],
            "expected_output": "Cited review evidence.",
            "isolation": "shared",
        }
    )
    missions.append(
        {
            "id": "MV",
            "kind": "verification",
            "title": "Verify accepted criteria",
            "goal": "Run accepted Proof commands against AC-1.",
            "acceptance_criteria": ["AC-1"],
            "target_repositories": [target.repository],
            "target_paths": [target.path],
            "depends_on": ["M2"],
            "expected_output": "Revision-bound machine evidence.",
            "verification_commands": list(specification.verification_commands),
            "isolation": "shared",
        }
    )
    return TracePlan.model_validate(
        {
            "spec_hash": specification.content_hash(),
            "review_required": review_required,
            "integration_owner": "M1",
            "missions": missions,
        }
    )


async def _approve_plan(db, run, specification: TraceSpecification):
    plan_revision = await trace_service.create_plan_revision(
        db,
        run_id=run.id,
        plan=_plan(specification),
    )
    return await trace_service.accept_plan_revision(
        db,
        run_id=run.id,
        revision_id=plan_revision.id,
        expected_hash=plan_revision.content_hash,
    )


async def _start(db, run):
    session = await db.get(ChatSession, run.session_id) if run.session_id else None
    if session is None:
        session = ChatSession(
            agent_name="lead",
            mode="coding",
            workspace=run.workspace,
            project_id=run.project_id,
        )
        db.add(session)
        await db.flush()
    return await trace_service.start_run_in_session(
        db,
        run_id=run.id,
        session_id=session.id,
    )


def test_specification_hash_is_stable_and_duplicate_criteria_fail():
    first = _spec()
    second = TraceSpecification.model_validate(first.model_dump(mode="json"))
    assert first.content_hash() == second.content_hash()
    assert len(first.content_hash()) == 64

    duplicate = first.model_dump(mode="json")
    duplicate["criteria"].append(dict(duplicate["criteria"][0]))
    with pytest.raises(ValidationError, match="duplicate criterion IDs"):
        TraceSpecification.model_validate(duplicate)


def test_specification_rejects_source_path_escape():
    raw = _spec().model_dump(mode="json")
    raw["source_refs"] = ["../secrets.md"]
    with pytest.raises(ValidationError, match="repository-relative"):
        TraceSpecification.model_validate(raw)


def test_specification_rejects_unsafe_verification_command():
    raw = _spec().model_dump(mode="json")
    raw["verification_commands"] = ["pytest -q && curl https://example.invalid"]

    with pytest.raises(ValidationError, match="shell composition"):
        TraceSpecification.model_validate(raw)

    raw = _spec().model_dump(mode="json")
    raw["impact_targets"][0]["path"] = "../outside.py"
    with pytest.raises(ValidationError, match="repository-relative"):
        TraceSpecification.model_validate(raw)


@pytest.mark.asyncio
async def test_run_revision_acceptance_and_mission_binding(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
        )
        detail = await trace_service.run_detail(db, run.id)
        revision_id = detail["revisions"][0]["id"]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=revision_id,
            expected_hash=spec.content_hash(),
        )
        plan_revision = await _approve_plan(db, run, spec)
        await _start(db, run)
        context = await trace_service.validate_mission_binding(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            plan_hash=plan_revision.content_hash,
            plan_mission_id="M1",
            criterion_ids=["AC-1"],
            target_repositories=["backend"],
            target_paths=["app/services/trace_service.py"],
        )
        assert context.run.status == "active"

        with pytest.raises(trace_service.TraceConflict, match="stale spec hash"):
            await trace_service.validate_mission_binding(
                db,
                run_id=run.id,
                spec_hash="0" * 64,
                plan_hash=plan_revision.content_hash,
                plan_mission_id="M1",
                criterion_ids=["AC-1"],
            )
        with pytest.raises(trace_service.TraceValidationError, match="Unknown"):
            await trace_service.validate_mission_binding(
                db,
                run_id=run.id,
                spec_hash=revision.content_hash,
                plan_hash=plan_revision.content_hash,
                plan_mission_id="M1",
                criterion_ids=["AC-404"],
            )
        with pytest.raises(trace_service.TraceValidationError, match="exceed"):
            await trace_service.validate_mission_binding(
                db,
                run_id=run.id,
                spec_hash=revision.content_hash,
                plan_hash=plan_revision.content_hash,
                plan_mission_id="M1",
                criterion_ids=["AC-1"],
                target_repositories=["backend"],
                target_paths=["app/api/outside.py"],
            )


@pytest.mark.asyncio
async def test_minimal_intent_authors_reviewable_spec_before_acceptance(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        run = await trace_service.create_intent_run(
            db,
            workspace=str(tmp_path),
            title="Agent-authored specification",
            problem="The feature contract is not drafted yet.",
            outcome="",
            session_id=session.id,
        )
        assert run.status == "intent"
        assert (await trace_service.run_detail(db, run.id))["revisions"] == []

        started = await trace_service.start_spec_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        assert started.status == "authoring"
        competing = await trace_service.create_intent_run(
            db,
            workspace=str(tmp_path),
            title="Competing authoring run",
            problem="It must not share one authoring session.",
            session_id=session.id,
        )
        with pytest.raises(trace_service.TraceConflict, match="already owns"):
            await trace_service.start_spec_authoring_in_session(
                db,
                run_id=competing.id,
                session_id=session.id,
            )
        assert competing.status == "intent"

        raw = _spec(title=run.title).model_dump(mode="json")
        raw["impact_targets"][0]["repository"] = tmp_path.name
        specification = TraceSpecification.model_validate(raw)
        revision = await trace_service.submit_authored_specification(
            db,
            run_id=run.id,
            session_id=session.id,
            specification=specification,
            authoring={"mode": "agent_chat"},
        )
        assert run.status == "draft"
        assert run.active_spec_revision_id is None
        assert revision.status == "draft"

        repeated = await trace_service.submit_authored_specification(
            db,
            run_id=run.id,
            session_id=session.id,
            specification=specification,
            authoring={"mode": "agent_chat"},
        )
        assert repeated.id == revision.id

        changed = specification.model_copy(update={"outcome": "A different outcome"})
        with pytest.raises(trace_service.TraceConflict, match="overwrite refused"):
            await trace_service.submit_authored_specification(
                db,
                run_id=run.id,
                session_id=session.id,
                specification=changed,
                authoring={"mode": "agent_chat"},
            )

        accepted = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=revision.id,
            expected_hash=revision.content_hash,
        )
        assert accepted.status == "accepted"
        assert run.status == "accepted"


@pytest.mark.asyncio
async def test_mission_target_path_is_validated_inside_selected_repository(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    raw = _spec().model_dump(mode="json")
    raw["impact_targets"] = [
        {
            "repository": "Backend",
            "path": "app/service.py",
            "reason": "Backend implementation",
        },
        {
            "repository": "Frontend",
            "path": "src/App.tsx",
            "reason": "Frontend implementation",
        },
    ]
    spec = TraceSpecification.model_validate(raw)
    async with async_session_factory() as db:
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan = TracePlan.model_validate(
            {
                "spec_hash": revision.content_hash,
                "missions": [
                    {
                        "id": "M1",
                        "kind": "implementation",
                        "title": "Implement frontend AC",
                        "goal": "Implement AC-1 in the frontend target.",
                        "acceptance_criteria": ["AC-1"],
                        "target_repositories": ["Frontend"],
                        "target_paths": ["src/App.tsx"],
                        "expected_output": "Frontend implementation.",
                    },
                    {
                        "id": "M2",
                        "kind": "review",
                        "title": "Review frontend AC",
                        "goal": "Review AC-1 against the integrated result.",
                        "acceptance_criteria": ["AC-1"],
                        "target_repositories": ["Frontend"],
                        "target_paths": ["src/App.tsx"],
                        "depends_on": ["M1"],
                        "expected_output": "Cited review evidence.",
                    },
                    {
                        "id": "MV",
                        "kind": "verification",
                        "title": "Verify frontend AC",
                        "goal": "Run accepted Proof commands.",
                        "acceptance_criteria": ["AC-1"],
                        "target_repositories": ["Frontend"],
                        "target_paths": ["src/App.tsx"],
                        "depends_on": ["M2"],
                        "expected_output": "Revision-bound machine evidence.",
                        "verification_commands": list(spec.verification_commands),
                    },
                ],
            }
        )
        plan_draft = await trace_service.create_plan_revision(
            db, run_id=run.id, plan=plan
        )
        plan_revision = await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan_draft.id,
            expected_hash=plan_draft.content_hash,
        )
        await _start(db, run)

        with pytest.raises(trace_service.TraceValidationError, match="exceed"):
            await trace_service.validate_mission_binding(
                db,
                run_id=run.id,
                spec_hash=revision.content_hash,
                plan_hash=plan_revision.content_hash,
                plan_mission_id="M1",
                criterion_ids=["AC-1"],
                target_repositories=["Frontend"],
                target_paths=["app/service.py"],
            )
        context = await trace_service.validate_mission_binding(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            plan_hash=plan_revision.content_hash,
            plan_mission_id="M1",
            criterion_ids=["AC-1"],
            target_repositories=["Frontend"],
            target_paths=["src/App.tsx"],
        )
        assert context.run.id == run.id


@pytest.mark.asyncio
async def test_only_one_trace_run_can_be_active_per_coding_session(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        spec = _spec()
        runs = []
        for title in ("First", "Second"):
            run = await trace_service.create_run(
                db,
                workspace=str(tmp_path),
                title=title,
                risk_tier="standard",
                specification=spec,
                session_id=session.id if title == "First" else None,
            )
            draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
            await trace_service.accept_revision(
                db,
                run_id=run.id,
                revision_id=draft["id"],
                expected_hash=draft["content_hash"],
            )
            await _approve_plan(db, run, spec)
            runs.append(run)
        await _start(db, runs[0])
        with pytest.raises(trace_service.TraceConflict, match="already active"):
            await trace_service.start_run_in_session(
                db, run_id=runs[1].id, session_id=session.id
            )
        runs[1].session_id = session.id
        runs[1].status = "active"
        db.add(runs[1])
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_unbound_run_starts_atomically_in_authorized_coding_session(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    other = tmp_path / "other"
    other.mkdir()
    async with async_session_factory() as db:
        linked = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        same_scope = ChatSession(
            agent_name="lead", mode="coding", workspace=str(tmp_path)
        )
        wrong = ChatSession(agent_name="lead", mode="coding", workspace=str(other))
        db.add(linked)
        db.add(same_scope)
        db.add(wrong)
        await db.flush()
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        await _approve_plan(db, run, spec)

        with pytest.raises(trace_service.TraceValidationError, match="another"):
            await trace_service.start_run_in_session(
                db, run_id=run.id, session_id=wrong.id
            )
        assert run.session_id is None
        started = await trace_service.start_run_in_session(
            db, run_id=run.id, session_id=linked.id
        )
        assert started.session_id == linked.id
        assert started.status == "active"
        with pytest.raises(trace_service.TraceConflict, match="another"):
            await trace_service.start_run_in_session(
                db, run_id=run.id, session_id=same_scope.id
            )


@pytest.mark.asyncio
async def test_evidence_matrix_and_convergence_are_snapshot_bound(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
            session_id=lead.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        await _approve_plan(db, run, spec)
        await _start(db, run)
        mission = DelegationTask(
            lead_session_id=lead.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="builder#1",
            status="completed",
            spec={
                "goal": "Implement AC-1",
                "acceptance_criteria": ["AC-1"],
                "trace_spec_hash": revision.content_hash,
            },
            result={"summary": "implemented"},
        )
        db.add(mission)
        await db.flush()

        evidence = await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="builder#1",
            kind="machine",
            result="passed",
            summary="pytest passed",
            delegation_task_id=mission.id,
            revision="abc123",
            artifact_hash="f" * 64,
            payload={
                "exit_code": 0,
                "command": ["pytest", "-q"],
                "spec_command": "pytest -q tests/services/test_trace_service.py",
            },
            source_key="completion-contract-1",
        )
        duplicate = await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="builder#1",
            kind="machine",
            result="passed",
            summary="pytest passed",
            delegation_task_id=mission.id,
            revision="abc123",
            artifact_hash="f" * 64,
            payload={
                "exit_code": 0,
                "command": ["pytest", "-q"],
                "spec_command": "pytest -q tests/services/test_trace_service.py",
            },
            source_key="completion-contract-1",
        )
        assert duplicate.id == evidence.id
        await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="lead",
            kind="review",
            result="passed",
            summary="Integrated review passed.",
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=lead.id
        )
        await trace_service.start_verification_in_session(
            db, run_id=run.id, session_id=lead.id
        )

        detail = await trace_service.run_detail(db, run.id)
        assert detail["criteria"][0]["status"] == "passed"
        report = await trace_service.converge_run(
            db, run_id=run.id, git_revision="abc123"
        )
        assert report["spec_hash"] == revision.content_hash
        assert report["criteria"] == {"total": 1, "passed": 1, "waived": 0}
        assert (await trace_service.get_run(db, run.id)).status == "converged"
        repeated = await trace_service.converge_run(
            db, run_id=run.id, git_revision="newer-working-tree"
        )
        assert repeated == report

        with pytest.raises(trace_service.TraceConflict, match="while EASD run"):
            await trace_service.create_deviation(
                db,
                run_id=run.id,
                description="Too late to alter a converged run.",
            )


@pytest.mark.asyncio
async def test_mission_handoff_imports_machine_evidence_per_criterion(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan_revision = await _approve_plan(db, run, spec)
        await _start(db, run)
        mission = DelegationTask(
            lead_session_id=lead.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="builder#1",
            status="completed",
            spec={
                "goal": "Implement AC-1",
                "trace_run_id": str(run.id),
                "trace_spec_hash": revision.content_hash,
                "trace_plan_hash": plan_revision.content_hash,
                "plan_mission_id": "M1",
                "acceptance_criteria": ["AC-1"],
                "target_repos": ["backend"],
                "target_paths": ["app/services/trace_service.py"],
            },
        )
        db.add(mission)
        await db.flush()
        artifact = {
            "summary": "The implementation and focused checks are complete.",
            "deviations": ["The accepted response shape needs clarification."],
            "criteria_results": [
                {
                    "criterion_id": "AC-1",
                    "result": "passed",
                    "summary": "The focused API check passed.",
                    "evidence_ids": [],
                }
            ],
            "verification": {
                "verified": True,
                "method": "completion_contract",
                "command_ids": ["cmd-1"],
                "exit_codes": [0],
                "revision": "abc123",
                "artifact_hash": "e" * 64,
                "completion_contract": {
                    "artifact_hash": "e" * 64,
                    "changed_files": ["app/services/trace_service.py"],
                    "scope_paths": ["app/services/trace_service.py"],
                    "passed": True,
                    "rigor": "standard",
                    "evidence": [
                        {
                            "command_id": "cmd-1",
                            "command": ["pytest", "-q"],
                            "passed": True,
                            "source": "planned",
                            "spec_command": (
                                "pytest -q tests/services/test_trace_service.py"
                            ),
                        }
                    ],
                },
            },
        }
        evidence = await trace_service.record_mission_handoff_evidence(
            db, task=mission, artifact=artifact
        )

        assert len(evidence) == 1
        assert evidence[0].kind == "machine"
        assert evidence[0].result == "passed"
        assert evidence[0].criterion_ids == ["AC-1"]
        assert evidence[0].artifact_hash == "e" * 64
        detail = await trace_service.run_detail(db, run.id)
        assert len(detail["deviations"]) == 1
        assert detail["deviations"][0]["blocking"] is True
        assert detail["deviations"][0]["delegation_task_id"] == str(mission.id)
        assert (
            detail["deviations"][0]["description"]
            == "The accepted response shape needs clarification."
        )


@pytest.mark.asyncio
async def test_handoff_outside_scope_is_not_admitted_as_machine_evidence(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan_revision = await _approve_plan(db, run, spec)
        await _start(db, run)
        mission = DelegationTask(
            lead_session_id=lead.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="builder#1",
            status="completed",
            spec={
                "goal": "Implement AC-1",
                "trace_run_id": str(run.id),
                "trace_spec_hash": revision.content_hash,
                "trace_plan_hash": plan_revision.content_hash,
                "plan_mission_id": "M1",
                "acceptance_criteria": ["AC-1"],
                "target_repos": ["backend"],
                "target_paths": ["app/services/trace_service.py"],
            },
        )
        db.add(mission)
        await db.flush()
        artifact_hash = "d" * 64
        artifact = {
            "summary": "The implementation and focused checks are complete.",
            "criteria_results": [
                {
                    "criterion_id": "AC-1",
                    "result": "passed",
                    "summary": "The focused check passed.",
                    "evidence_ids": [],
                }
            ],
            "verification": {
                "verified": True,
                "method": "completion_contract",
                "command_ids": ["cmd-1"],
                "artifact_hash": artifact_hash,
                "completion_contract": {
                    "artifact_hash": artifact_hash,
                    "scope_paths": ["app/api/outside.py"],
                    "passed": True,
                    "evidence": [],
                },
            },
        }

        evidence = await trace_service.record_mission_handoff_evidence(
            db, task=mission, artifact=artifact
        )
        detail = await trace_service.run_detail(db, run.id)

        assert evidence[0].kind == "manual"
        assert detail["criteria"][0]["status"] != "passed"
        assert any(
            item["blocking"] and "outside the accepted Scope" in item["description"]
            for item in detail["deviations"]
        )


@pytest.mark.asyncio
async def test_convergence_requires_every_planned_verification_command(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec(machine_required=False)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
            session_id=lead.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        await _approve_plan(db, run, spec)
        await _start(db, run)
        await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="reviewer#1",
            kind="review",
            result="passed",
            summary="The criterion passed review, but no planned command ran.",
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=lead.id
        )
        await trace_service.start_verification_in_session(
            db, run_id=run.id, session_id=lead.id
        )

        with pytest.raises(trace_service.TraceConvergenceError) as exc_info:
            await trace_service.converge_run(db, run_id=run.id, git_revision=None)

        assert {
            "code": "planned_verification_missing",
            "commands": ["pytest -q tests/services/test_trace_service.py"],
        } in exc_info.value.reasons


@pytest.mark.asyncio
async def test_blocking_deviation_rejects_convergence(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec(machine_required=False)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
            session_id=lead.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        await _approve_plan(db, run, spec)
        await _start(db, run)
        await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="lead",
            kind="review",
            result="passed",
            summary="criterion reviewed",
        )
        deviation = await trace_service.create_deviation(
            db,
            run_id=run.id,
            criterion_id="AC-1",
            description="Implementation needs a larger public API.",
            proposed_change={"new_endpoint": "/v2"},
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=lead.id
        )
        await trace_service.start_verification_in_session(
            db, run_id=run.id, session_id=lead.id
        )
        with pytest.raises(trace_service.TraceConvergenceError) as exc_info:
            await trace_service.converge_run(db, run_id=run.id, git_revision=None)
        assert any(
            reason["code"] == "blocking_deviation"
            and reason["deviation_id"] == str(deviation.id)
            for reason in exc_info.value.reasons
        )

        with pytest.raises(trace_service.TraceConflict, match="newly accepted"):
            await trace_service.resolve_deviation(
                db,
                run_id=run.id,
                deviation_id=deviation.id,
                status="resolved",
                resolution="Accept the larger API.",
                resolved_spec_hash=revision.content_hash,
            )


@pytest.mark.asyncio
async def test_evidence_rejects_foreign_mission(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        lead = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(lead)
        await db.flush()
        spec = _spec()
        first = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title="First",
            risk_tier="standard",
            specification=spec,
        )
        second = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title="Second",
            risk_tier="standard",
            specification=spec,
        )
        for run in (first, second):
            draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
            await trace_service.accept_revision(
                db,
                run_id=run.id,
                revision_id=draft["id"],
                expected_hash=draft["content_hash"],
            )
            await _approve_plan(db, run, spec)
            await _start(db, run)
        foreign = DelegationTask(
            lead_session_id=lead.id,
            trace_run_id=second.id,
            delegator="lead",
            recipient="builder#1",
            spec={"acceptance_criteria": ["AC-1"]},
        )
        db.add(foreign)
        await db.flush()
        first_context = await trace_service.active_context(db, first.id)
        with pytest.raises(trace_service.TraceValidationError, match="another run"):
            await trace_service.create_evidence(
                db,
                run_id=first.id,
                spec_hash=first_context.revision.content_hash,
                criterion_ids=["AC-1"],
                producer="builder#1",
                kind="machine",
                result="passed",
                summary="not actually this run",
                delegation_task_id=foreign.id,
            )


def test_invalid_uuid_is_domain_validation_error():
    with pytest.raises(trace_service.TraceValidationError, match="Invalid EASD run"):
        trace_service._uuid(str(uuid4()) + "x", label="EASD run ID")
