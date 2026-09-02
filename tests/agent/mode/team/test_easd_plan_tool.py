from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.easd.context import EasdContext
from app.agent.easd.plan import make_easd_plan_tool
from app.models.chat import ChatSession
from app.services import trace_service
from app.services.trace_contracts import TracePlan, TraceSpecification


def _spec(repository: str) -> TraceSpecification:
    return TraceSpecification.model_validate(
        {
            "title": "Tool-authored plan",
            "problem": "The accepted spec has no approved execution plan.",
            "outcome": "The user can review a typed plan before implementation.",
            "impact_targets": [
                {
                    "repository": repository,
                    "path": "app/service.py",
                    "reason": "Owns the implementation",
                }
            ],
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "A typed plan is persisted for user review.",
                }
            ],
        }
    )


def _plan(specification: TraceSpecification, repository: str) -> TracePlan:
    return TracePlan.model_validate(
        {
            "spec_hash": specification.content_hash(),
            "missions": [
                {
                    "id": "M1",
                    "kind": "implementation",
                    "title": "Implement AC-1",
                    "goal": "Implement the accepted behavior.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [repository],
                    "target_paths": ["app/service.py"],
                    "expected_output": "Implementation and evidence.",
                },
                {
                    "id": "M2",
                    "kind": "review",
                    "title": "Review AC-1",
                    "goal": "Review the integrated behavior.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": [repository],
                    "target_paths": ["app/service.py"],
                    "depends_on": ["M1"],
                    "expected_output": "Cited review evidence.",
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_lead_plan_tool_persists_review_draft_without_approving(
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
            risk_tier="standard",
            specification=specification,
            session_id=session.id,
        )
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        await trace_service.start_plan_authoring_in_session(
            db, run_id=run.id, session_id=session.id
        )
        await db.commit()

    easd_ctx = EasdContext(db_factory=async_session_factory, session_id=str(session.id))
    tool = make_easd_plan_tool(easd_ctx, agent_name="lead")
    state = SimpleNamespace(metadata={})

    result = await tool.arun(
        _injected={"_state": state},
        run_id=str(run.id),
        plan=_plan(specification, tmp_path.name).model_dump(mode="json"),
        summary="Every required criterion has bounded implementation ownership.",
        confidence=0.93,
    )

    assert "Plan draft persisted" in result
    assert state.metadata["stop_after_tool_call"] == "easd_submit_plan"
    async with async_session_factory() as db:
        detail = await trace_service.run_detail(db, run.id)
    assert detail["run"]["status"] == "plan_review"
    assert detail["active_plan"] is None
    assert detail["plan_revisions"][0]["authoring"]["mode"] == "agent_chat"
