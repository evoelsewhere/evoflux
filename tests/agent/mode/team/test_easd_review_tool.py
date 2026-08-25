from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.mode.team.easd_review import make_easd_review_tool
from app.models.chat import ChatSession
from app.models.team import DelegationTask
from app.services import trace_service
from app.services.trace_contracts import TracePlan, TraceSpecification


@pytest.mark.asyncio
async def test_member_review_tool_records_runtime_independent_evidence(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    specification = TraceSpecification.model_validate(
        {
            "title": "Independent review tool",
            "problem": "Review identity can be fabricated in prose.",
            "outcome": "Runtime identity determines reviewer independence.",
            "impact_targets": [
                {
                    "repository": tmp_path.name,
                    "path": "app/service.py",
                    "reason": "Reviewed implementation",
                }
            ],
            "criteria": [{"id": "AC-1", "statement": "Review is persisted."}],
        }
    )
    plan = TracePlan.model_validate(
        {
            "spec_hash": specification.content_hash(),
            "review_required": True,
            "missions": [
                {
                    "id": "M1",
                    "kind": "implementation",
                    "title": "Implement",
                    "goal": "Implement AC-1.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [tmp_path.name],
                    "target_paths": ["app/service.py"],
                    "expected_output": "Implementation.",
                },
                {
                    "id": "M2",
                    "kind": "review",
                    "title": "Review",
                    "goal": "Review AC-1 independently.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [tmp_path.name],
                    "target_paths": ["app/service.py"],
                    "depends_on": ["M1"],
                    "expected_output": "Cited review.",
                    "isolation": "shared",
                },
            ],
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
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        spec_revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan_draft = await trace_service.create_plan_revision(
            db, run_id=run.id, plan=plan
        )
        await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan_draft.id,
            expected_hash=plan_draft.content_hash,
        )
        await trace_service.start_run_in_session(
            db, run_id=run.id, session_id=session.id
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=session.id
        )
        review_task = DelegationTask(
            lead_session_id=session.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="reviewer#1",
            status="in_progress",
            spec={
                "trace_spec_hash": spec_revision.content_hash,
                "trace_plan_hash": plan_draft.content_hash,
                "plan_mission_id": "M2",
                "acceptance_criteria": ["AC-1"],
                "target_repos": [tmp_path.name],
                "target_paths": ["app/service.py"],
            },
        )
        db.add(review_task)
        await db.commit()

    team = SimpleNamespace(
        _db_factory=async_session_factory,
        lead=SimpleNamespace(db_factory=async_session_factory),
    )
    tool = make_easd_review_tool(
        team,
        agent_name="reviewer#1",
        role="member",
    )
    result = await tool.arun(
        run_id=str(run.id),
        spec_hash=spec_revision.content_hash,
        criteria_results=[
            {
                "criterion_id": "AC-1",
                "result": "passed",
                "summary": "Integrated implementation satisfies AC-1.",
            }
        ],
        findings=[],
        sources=["app/service.py:1"],
        summary="Independent review found no blocking specification gap.",
        revision="abc123",
        delegation_task_id=str(review_task.id),
    )

    assert "independent=true" in result
    async with async_session_factory() as db:
        detail = await trace_service.run_detail(db, run.id)
    review = next(item for item in detail["evidence"] if item["kind"] == "review")
    assert review["producer"] == "reviewer#1"
    assert review["payload"]["independent"] is True
    assert detail["run"]["status"] == "reviewing"


@pytest.mark.asyncio
async def test_review_tool_rejects_an_implementation_mission_identity(
    tmp_path, setup_db
):
    from app.core.db import async_session_factory

    specification = TraceSpecification.model_validate(
        {
            "title": "Reject forged review mission",
            "problem": "An implementation task could claim to be a reviewer.",
            "outcome": "Only an approved review mission can submit review evidence.",
            "impact_targets": [
                {
                    "repository": tmp_path.name,
                    "path": "app/service.py",
                    "reason": "Reviewed implementation",
                }
            ],
            "criteria": [{"id": "AC-1", "statement": "Review is trusted."}],
        }
    )
    plan = TracePlan.model_validate(
        {
            "spec_hash": specification.content_hash(),
            "review_required": True,
            "missions": [
                {
                    "id": "M1",
                    "kind": "implementation",
                    "title": "Implement",
                    "goal": "Implement AC-1.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [tmp_path.name],
                    "target_paths": ["app/service.py"],
                    "expected_output": "Implementation.",
                },
                {
                    "id": "M2",
                    "kind": "review",
                    "title": "Review",
                    "goal": "Review AC-1.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [tmp_path.name],
                    "target_paths": ["app/service.py"],
                    "depends_on": ["M1"],
                    "expected_output": "Review evidence.",
                },
            ],
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
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        spec_revision = await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan_draft = await trace_service.create_plan_revision(
            db, run_id=run.id, plan=plan
        )
        await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan_draft.id,
            expected_hash=plan_draft.content_hash,
        )
        await trace_service.start_run_in_session(
            db, run_id=run.id, session_id=session.id
        )
        await trace_service.start_review_in_session(
            db, run_id=run.id, session_id=session.id
        )
        forged = DelegationTask(
            lead_session_id=session.id,
            trace_run_id=run.id,
            delegator="lead",
            recipient="reviewer#1",
            status="in_progress",
            spec={
                "trace_spec_hash": spec_revision.content_hash,
                "trace_plan_hash": plan_draft.content_hash,
                "plan_mission_id": "M1",
                "acceptance_criteria": ["AC-1"],
                "target_repos": [tmp_path.name],
                "target_paths": ["app/service.py"],
            },
        )
        db.add(forged)
        await db.commit()

    team = SimpleNamespace(
        _db_factory=async_session_factory,
        lead=SimpleNamespace(db_factory=async_session_factory),
    )
    result = await make_easd_review_tool(
        team, agent_name="reviewer#1", role="member"
    ).arun(
        run_id=str(run.id),
        spec_hash=spec_revision.content_hash,
        criteria_results=[
            {
                "criterion_id": "AC-1",
                "result": "passed",
                "summary": "Attempted forged review result.",
            }
        ],
        findings=[],
        sources=["app/service.py:1"],
        summary="This result must not cross the review trust boundary.",
        revision="abc123",
        delegation_task_id=str(forged.id),
    )

    assert "cannot run during reviewing" in result
