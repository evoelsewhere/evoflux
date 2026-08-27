from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.chat import ChatSession
from app.models.team import DelegationTask
from app.services import trace_service
from app.services.trace_contracts import (
    TracePlan,
    TraceReviewCriterion,
    TraceSpecification,
)


def _spec(
    repository: str,
    *,
    risk_tier: str = "standard",
    delivery_mode: str = "planned",
) -> TraceSpecification:
    return TraceSpecification.model_validate(
        {
            "title": "Durable EASD plan",
            "problem": "Implementation can start before a plan is approved.",
            "outcome": "Only an accepted plan can authorize implementation.",
            "impact_targets": [
                {
                    "repository": repository,
                    "path": "app/service.py",
                    "reason": "Owns the planned behavior",
                }
            ],
            "verification_commands": [
                "pytest -q tests/services/test_trace_plan_service.py"
            ],
            "risk_tier": risk_tier,
            "delivery_flow": {
                "mode": delivery_mode,
                "rationale": (
                    "Single-repository low-risk change can run directly."
                    if delivery_mode == "direct"
                    else "Explicit Plan approval is required."
                ),
                "confidence": 0.9,
                "required_by": [],
            },
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "Implementation requires an accepted plan.",
                    "evidence_policy": {
                        "allowed_kinds": ["machine", "review"],
                        "machine_required": True,
                    },
                }
            ],
        }
    )


def _plan(spec: TraceSpecification, repository: str) -> TracePlan:
    return TracePlan.model_validate(
        {
            "spec_hash": spec.content_hash(),
            "review_required": False,
            "integration_owner": "M1",
            "missions": [
                {
                    "id": "M1",
                    "kind": "implementation",
                    "title": "Implement accepted behavior",
                    "goal": "Implement AC-1 inside the accepted service boundary.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [repository],
                    "target_paths": ["app/service.py"],
                    "depends_on": [],
                    "expected_output": "Implementation and regression evidence.",
                    "constraints": ["Preserve accepted scope"],
                    "verification_commands": [
                        "pytest -q tests/services/test_trace_plan_service.py"
                    ],
                    "isolation": "worktree",
                },
                {
                    "id": "M2",
                    "kind": "review",
                    "title": "Review accepted behavior",
                    "goal": "Review AC-1 against the integrated result.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [repository],
                    "target_paths": ["app/service.py"],
                    "depends_on": ["M1"],
                    "expected_output": "Cited per-AC review evidence.",
                    "isolation": "shared",
                },
                {
                    "id": "M3",
                    "kind": "verification",
                    "title": "Verify accepted behavior",
                    "goal": "Run the accepted Proof command against AC-1.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [repository],
                    "target_paths": ["app/service.py"],
                    "depends_on": ["M2"],
                    "expected_output": "Revision-bound machine evidence.",
                    "verification_commands": [
                        "pytest -q tests/services/test_trace_plan_service.py"
                    ],
                    "isolation": "shared",
                },
            ],
        }
    )


def test_plan_contract_rejects_cycles():
    raw = {
        "spec_hash": "a" * 64,
        "missions": [
            {
                "id": "M1",
                "kind": "implementation",
                "title": "One",
                "goal": "One",
                "acceptance_criteria": ["AC-1"],
                "expected_output": "One",
                "depends_on": ["M2"],
            },
            {
                "id": "M2",
                "kind": "integration",
                "title": "Two",
                "goal": "Two",
                "acceptance_criteria": ["AC-1"],
                "expected_output": "Two",
                "depends_on": ["M1"],
            },
        ],
    }

    with pytest.raises(ValidationError, match="acyclic"):
        TracePlan.model_validate(raw)


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
        db, run_id=run.id, session_id=session.id
    )


@pytest.mark.asyncio
async def test_direct_flow_skips_plan_but_keeps_review_verify_and_converge(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        specification = _spec(tmp_path.name, delivery_mode="direct")
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier=specification.risk_tier,
            specification=specification,
            session_id=session.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        assert run.status == "accepted"
        assert run.active_plan_revision_id is None
        accepted_detail = await trace_service.run_detail(db, run.id)
        assert accepted_detail["action_rail"]["primary_action"] == (
            "start_implementation"
        )
        assert [
            action["id"] for action in accepted_detail["action_rail"]["actions"]
        ] == ["start_implementation"]
        with pytest.raises(trace_service.TraceConflict, match="skips Plan"):
            await trace_service.start_plan_authoring_in_session(
                db, run_id=run.id, session_id=session.id
            )

        await trace_service.start_run_in_session(
            db, run_id=run.id, session_id=session.id
        )
        assert run.status == "active"
        direct_context = await trace_service.validate_mission_binding(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            plan_hash=None,
            plan_mission_id=None,
            criterion_ids=["AC-1"],
            target_repositories=[tmp_path.name],
            target_paths=["app/service.py"],
        )
        assert direct_context.plan is None
        assert direct_context.plan_revision is None
        await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            criterion_ids=["AC-1"],
            producer="runtime",
            kind="machine",
            result="passed",
            summary="Accepted direct-flow check passed.",
            payload={
                "spec_command": "pytest -q tests/services/test_trace_plan_service.py"
            },
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=session.id
        )
        await trace_service.submit_review_evidence(
            db,
            run_id=run.id,
            spec_hash=revision.content_hash,
            reviewer="lead",
            reviewer_role="lead",
            criteria_results=[
                TraceReviewCriterion(
                    criterion_id="AC-1",
                    result="passed",
                    summary="Direct implementation matches the accepted Spec.",
                )
            ],
            findings=[],
            sources=["app/service.py:1"],
            summary="Mandatory Review found no blocking issue.",
            revision="direct123",
        )
        await trace_service.start_verification_in_session(
            db, run_id=run.id, session_id=session.id
        )
        report = await trace_service.converge_run(
            db, run_id=run.id, git_revision="direct123"
        )

        assert report["delivery_flow"]["mode"] == "direct"
        assert report["plan_revision_id"] is None
        assert report["plan_hash"] is None
        assert run.status == "converged"


@pytest.mark.asyncio
async def test_direct_flow_fails_closed_for_cross_layer_or_security_scope(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    raw = _spec(tmp_path.name, delivery_mode="direct").model_dump(mode="json")
    raw["constraints"] = [
        {
            "kind": "security",
            "statement": "Preserve the authorization boundary.",
            "source_refs": [],
        }
    ]
    unsafe = TraceSpecification.model_validate(raw)
    async with async_session_factory() as db:
        with pytest.raises(
            trace_service.TraceValidationError, match="constraint:security"
        ):
            await trace_service.create_run(
                db,
                workspace=str(tmp_path),
                title=unsafe.title,
                risk_tier=unsafe.risk_tier,
                specification=unsafe,
            )


@pytest.mark.asyncio
async def test_plan_approval_is_required_before_implementation(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        specification = _spec(tmp_path.name)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier=specification.risk_tier,
            specification=specification,
            session_id=session.id,
        )
        spec_draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=spec_draft["id"],
            expected_hash=spec_draft["content_hash"],
        )
        with pytest.raises(trace_service.TraceConflict, match="no accepted"):
            await _start(db, run)

        await trace_service.start_plan_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        assert run.status == "planning"
        plan = _plan(specification, tmp_path.name)
        plan_draft = await trace_service.submit_authored_plan(
            db,
            run_id=run.id,
            session_id=session.id,
            plan=plan,
            authoring={"mode": "agent_chat"},
        )
        assert run.status == "plan_review"
        assert run.active_plan_revision_id is None
        repeated = await trace_service.submit_authored_plan(
            db,
            run_id=run.id,
            session_id=session.id,
            plan=plan,
            authoring={"mode": "agent_chat"},
        )
        assert repeated.id == plan_draft.id
        changed = plan.model_copy(update={"integration_owner": None})
        with pytest.raises(trace_service.TraceConflict, match="overwrite refused"):
            await trace_service.submit_authored_plan(
                db,
                run_id=run.id,
                session_id=session.id,
                plan=changed,
                authoring={"mode": "agent_chat"},
            )

        retried = await trace_service.retry_plan_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        assert retried.status == "planning"
        assert plan_draft.status == "draft"
        repeated_retry = await trace_service.retry_plan_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        assert repeated_retry.status == "planning"
        replacement = await trace_service.submit_authored_plan(
            db,
            run_id=run.id,
            session_id=session.id,
            plan=changed,
            authoring={"mode": "agent_chat", "attempt": 2},
        )
        assert replacement.version == 2
        assert plan_draft.status == "superseded"
        assert replacement.status == "draft"

        accepted = await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=replacement.id,
            expected_hash=replacement.content_hash,
        )
        assert accepted.status == "accepted"
        assert run.status == "planned"
        await _start(db, run)
        assert run.status == "active"
        detail = await trace_service.run_detail(db, run.id)
        assert detail["active_plan"]["content_hash"] == changed.content_hash()


@pytest.mark.asyncio
async def test_review_and_verify_are_distinct_user_controlled_phases(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        specification = _spec(tmp_path.name)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier=specification.risk_tier,
            specification=specification,
            session_id=session.id,
        )
        spec_draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        spec_revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=spec_draft["id"],
            expected_hash=spec_draft["content_hash"],
        )
        await trace_service.start_plan_authoring_in_session(
            db, run_id=run.id, session_id=session.id
        )
        plan_revision = await trace_service.submit_authored_plan(
            db,
            run_id=run.id,
            session_id=session.id,
            plan=_plan(specification, tmp_path.name),
            authoring={"mode": "agent_chat"},
        )
        await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan_revision.id,
            expected_hash=plan_revision.content_hash,
        )
        await _start(db, run)
        active_detail = await trace_service.run_detail(db, run.id)
        assert active_detail["action_rail"]["primary_action"] == "start_review"
        assert active_detail["action_rail"]["actions"][0]["state"] == "available"
        await trace_service.create_evidence(
            db,
            run_id=run.id,
            spec_hash=spec_revision.content_hash,
            criterion_ids=["AC-1"],
            producer="runtime",
            kind="machine",
            result="passed",
            summary="Planned test passed.",
            revision="abc123",
            payload={
                "spec_command": "pytest -q tests/services/test_trace_plan_service.py"
            },
            source_key="machine-plan-test",
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=session.id
        )
        assert run.status == "reviewing"
        reviewing_detail = await trace_service.run_detail(db, run.id)
        verify_action = reviewing_detail["action_rail"]["actions"][0]
        assert verify_action["id"] == "start_verification"
        assert verify_action["state"] == "blocked"
        assert verify_action["blockers"][0]["code"] == "review_evidence_required"
        with pytest.raises(trace_service.TraceConflict, match="review evidence"):
            await trace_service.start_verification_in_session(
                db, run_id=run.id, session_id=session.id
            )
        rows = await trace_service.submit_review_evidence(
            db,
            run_id=run.id,
            spec_hash=spec_revision.content_hash,
            reviewer="lead",
            reviewer_role="lead",
            criteria_results=[
                TraceReviewCriterion(
                    criterion_id="AC-1",
                    result="passed",
                    summary="Integrated behavior matches AC-1.",
                )
            ],
            findings=[],
            sources=["app/service.py:1"],
            summary="Review found no blocking issues.",
            revision="abc123",
        )
        assert rows[0].kind == "review"
        assert rows[0].payload["independent"] is False
        reviewed_detail = await trace_service.run_detail(db, run.id)
        assert reviewed_detail["action_rail"]["actions"][0]["state"] == "available"
        await trace_service.start_verification_in_session(
            db, run_id=run.id, session_id=session.id
        )
        assert run.status == "verifying"
        report = await trace_service.converge_run(
            db, run_id=run.id, git_revision="abc123"
        )
        assert report["plan_hash"] == plan_revision.content_hash
        assert run.status == "converged"


@pytest.mark.asyncio
async def test_action_rail_lists_nonterminal_missions_before_review(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        specification = _spec(tmp_path.name)
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=specification.title,
            risk_tier=specification.risk_tier,
            specification=specification,
            session_id=session.id,
        )
        spec_draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=spec_draft["id"],
            expected_hash=spec_draft["content_hash"],
        )
        await trace_service.start_plan_authoring_in_session(
            db, run_id=run.id, session_id=session.id
        )
        plan_revision = await trace_service.submit_authored_plan(
            db,
            run_id=run.id,
            session_id=session.id,
            plan=_plan(specification, tmp_path.name),
            authoring={"mode": "agent_chat"},
        )
        await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan_revision.id,
            expected_hash=plan_revision.content_hash,
        )
        await _start(db, run)
        mission = DelegationTask(
            lead_session_id=session.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="builder#1",
            status="running",
            spec={"goal": "Implement AC-1", "acceptance_criteria": ["AC-1"]},
        )
        db.add(mission)
        await db.flush()

        detail = await trace_service.run_detail(db, run.id)
        action = detail["action_rail"]["actions"][0]
        assert action["id"] == "start_review"
        assert action["state"] == "blocked"
        assert action["blockers"] == [
            {
                "code": "mission_not_terminal",
                "message": f"Mission {mission.id} is still running.",
                "mission_id": str(mission.id),
                "status": "running",
            }
        ]

        mission.status = "completed"
        db.add(mission)
        await db.flush()
        detail = await trace_service.run_detail(db, run.id)
        assert detail["action_rail"]["actions"][0]["state"] == "available"
