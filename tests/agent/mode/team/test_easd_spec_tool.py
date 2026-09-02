from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.easd.context import EasdContext
from app.agent.easd.spec import make_easd_spec_tool
from app.models.chat import ChatSession
from app.services import trace_service
from app.services.trace_contracts import TraceSpecification


@pytest.mark.asyncio
async def test_lead_tool_persists_draft_without_approving_or_implementing(
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
            title="Tool-authored spec",
            problem="The run has only Intent.",
            session_id=session.id,
        )
        await trace_service.start_spec_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        await db.commit()

    specification = TraceSpecification.model_validate(
        {
            "title": run.title,
            "problem": "The run has only Intent.",
            "outcome": "The user receives a complete reviewable specification.",
            "goals": ["Persist the draft"],
            "non_goals": ["Approve or implement it"],
            "impact_targets": [
                {
                    "repository": tmp_path.name,
                    "path": "documents/spec.md",
                    "reason": "Documents the intended behavior",
                }
            ],
            "risk_tier": "standard",
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The draft is persisted for user review.",
                    "evidence_policy": {
                        "allowed_kinds": ["review"],
                        "machine_required": False,
                        "minimum_passes": 1,
                    },
                }
            ],
        }
    )
    easd_ctx = EasdContext(db_factory=async_session_factory, session_id=str(session.id))
    tool = make_easd_spec_tool(easd_ctx, agent_name="lead")
    state = SimpleNamespace(metadata={})

    result = await tool.arun(
        _injected={"_state": state},
        run_id=str(run.id),
        specification=specification.model_dump(mode="json"),
        summary="Repository evidence supports a bounded reviewable specification.",
        confidence=0.9,
    )

    assert "Specification draft persisted" in result
    assert state.metadata["stop_after_tool_call"] == "easd_submit_specification"
    async with async_session_factory() as db:
        detail = await trace_service.run_detail(db, run.id)
    assert detail["run"]["status"] == "draft"
    assert detail["run"]["active_spec_revision_id"] is None
    assert detail["revisions"][0]["status"] == "draft"
    assert detail["revisions"][0]["authoring"]["mode"] == "agent_chat"
