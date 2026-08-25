from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.easd_context import EasdContextHook
from app.agent.state import AgentState, ModelRequest, RunContext
from app.models.chat import ChatSession
from app.services import trace_service
from app.services.trace_contracts import TracePlan, TraceSpecification


def _spec() -> TraceSpecification:
    return TraceSpecification.model_validate(
        {
            "title": "EASD context",
            "problem": "The lead can lose the accepted contract.",
            "outcome": "Every Coding turn sees the accepted EASD contract.",
            "goals": ["Preserve normative scope"],
            "non_goals": ["Replace team prompts"],
            "source_refs": ["docs/features/evo-agent-specs.md"],
            "impact_targets": [
                {
                    "repository": "backend",
                    "path": "app/services/trace_service.py",
                    "module": "EASD",
                    "reason": "Owns prompt context",
                }
            ],
            "constraints": [
                {
                    "kind": "compatibility",
                    "statement": "Preserve ordinary Coding turns",
                    "source_refs": ["docs/features/evo-agent-specs.md"],
                }
            ],
            "verification_commands": [
                "pytest -q tests/agent/hooks/test_easd_context_hook.py"
            ],
            "risk_tier": "standard",
            "criteria": [
                {
                    "id": "AC-1",
                    "statement": "The active contract is injected.",
                    "evidence_policy": {"machine_required": True},
                }
            ],
        }
    )


def _plan(specification: TraceSpecification) -> TracePlan:
    return TracePlan.model_validate(
        {
            "spec_hash": specification.content_hash(),
            "missions": [
                {
                    "id": "M1",
                    "kind": "implementation",
                    "title": "Implement AC-1",
                    "goal": "Implement the accepted contract.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": ["backend"],
                    "target_paths": ["app/services/trace_service.py"],
                    "expected_output": "Implementation and evidence.",
                },
                {
                    "id": "M2",
                    "kind": "review",
                    "title": "Review AC-1",
                    "goal": "Review the accepted behavior.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": ["backend"],
                    "target_paths": ["app/services/trace_service.py"],
                    "depends_on": ["M1"],
                    "expected_output": "Cited review evidence.",
                },
                {
                    "id": "MV",
                    "kind": "verification",
                    "title": "Verify AC-1",
                    "goal": "Run the accepted Proof command.",
                    "acceptance_criteria": ["AC-1"],
                    "target_repositories": ["backend"],
                    "target_paths": ["app/services/trace_service.py"],
                    "depends_on": ["M2"],
                    "expected_output": "Revision-bound machine evidence.",
                    "verification_commands": list(specification.verification_commands),
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_active_trace_contract_is_injected_and_draft_is_not(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        spec = _spec()
        run = await trace_service.create_run(
            db,
            workspace=str(tmp_path),
            title=spec.title,
            risk_tier="standard",
            specification=spec,
            session_id=session.id,
        )
        await db.commit()

    hook = EasdContextHook(
        db_factory=async_session_factory,
        lead_session_id=str(session.id),
        agent_name="lead",
        role="lead",
    )
    ctx = RunContext(session_id=str(session.id), run_id="run", agent_name="lead")
    state = AgentState(messages=[])
    request = ModelRequest(messages=(), system_prompt="Base prompt.")
    await hook.before_agent(ctx, state)
    assert await hook.before_model(ctx, state, request) is None

    async with async_session_factory() as db:
        draft = (await trace_service.run_detail(db, run.id))["revisions"][0]
        await trace_service.accept_revision(
            db,
            run_id=run.id,
            revision_id=draft["id"],
            expected_hash=draft["content_hash"],
        )
        plan = await trace_service.create_plan_revision(
            db,
            run_id=run.id,
            plan=_plan(spec),
        )
        await trace_service.accept_plan_revision(
            db,
            run_id=run.id,
            revision_id=plan.id,
            expected_hash=plan.content_hash,
        )
        await trace_service.start_run_in_session(
            db, run_id=run.id, session_id=session.id
        )
        await db.commit()

    await hook.before_agent(ctx, state)
    injected = await hook.before_model(ctx, state, request)
    assert injected is not None
    assert "## EASD Development Contract" in injected.system_prompt
    assert str(run.id) in injected.system_prompt
    assert draft["content_hash"] in injected.system_prompt
    assert "AC-1: The active contract is injected." in injected.system_prompt
    assert "backend:app/services/trace_service.py" in injected.system_prompt
    assert "Preserve ordinary Coding turns" in injected.system_prompt
    assert "machine_required=true" in injected.system_prompt
    assert (
        "pytest -q tests/agent/hooks/test_easd_context_hook.py"
        in injected.system_prompt
    )
    assert "do not silently expand" in injected.system_prompt.lower()
    assert state.metadata["_easd_run_id"] == str(run.id)
    assert state.metadata["_easd_spec_hash"] == draft["content_hash"]
    assert state.metadata["_easd_plan_hash"] == plan.content_hash
    assert state.metadata["_easd_phase"] == "active"
    assert state.metadata["_easd_verification_commands"] == [
        "pytest -q tests/agent/hooks/test_easd_context_hook.py"
    ]
    assert state.metadata["_easd_impact_targets"][0]["path"] == (
        "app/services/trace_service.py"
    )
    assert state.metadata["_easd_repository_roots"] == [
        {"repository": tmp_path.name, "path": str(tmp_path.resolve())}
    ]

    async def no_write(*_args):
        return "changed"

    for phase in ("planning", "plan_review", "planned"):
        async with async_session_factory() as db:
            persisted = await trace_service.get_run(db, run.id)
            persisted.status = phase
            db.add(persisted)
            await db.commit()
        phase_state = AgentState(messages=[])
        await hook.before_agent(ctx, phase_state)
        blocked = await hook.wrap_tool_call(
            ctx,
            phase_state,
            SimpleNamespace(function=SimpleNamespace(name="write")),
            no_write,
        )
        assert blocked.startswith("BLOCKED — EASD pre-implementation work is read-only")

    async with async_session_factory() as db:
        persisted = await trace_service.get_run(db, run.id)
        persisted.status = "reviewing"
        db.add(persisted)
        await db.commit()
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)
    called = False

    async def handler(*_args):
        nonlocal called
        called = True
        return "changed"

    blocked = await hook.wrap_tool_call(
        ctx,
        state,
        SimpleNamespace(function=SimpleNamespace(name="edit")),
        handler,
    )
    assert blocked.startswith("BLOCKED — EASD Review is read-only")
    assert called is False

    async with async_session_factory() as db:
        persisted = await trace_service.get_run(db, run.id)
        persisted.status = "verifying"
        db.add(persisted)
        await db.commit()
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)
    called = False
    blocked = await hook.wrap_tool_call(
        ctx,
        state,
        SimpleNamespace(function=SimpleNamespace(name="patch")),
        handler,
    )
    assert blocked.startswith("BLOCKED — EASD Verify is read-only")
    assert called is False


@pytest.mark.asyncio
async def test_authoring_context_blocks_implementation_tools(tmp_path, setup_db):
    from app.core.db import async_session_factory

    async with async_session_factory() as db:
        session = ChatSession(agent_name="lead", mode="coding", workspace=str(tmp_path))
        db.add(session)
        await db.flush()
        run = await trace_service.create_intent_run(
            db,
            workspace=str(tmp_path),
            title="Read-only authoring",
            problem="Implementation must wait for approval.",
            session_id=session.id,
        )
        await trace_service.start_spec_authoring_in_session(
            db,
            run_id=run.id,
            session_id=session.id,
        )
        await db.commit()

    hook = EasdContextHook(
        db_factory=async_session_factory,
        lead_session_id=str(session.id),
        agent_name="lead",
        role="lead",
    )
    ctx = RunContext(session_id=str(session.id), run_id="turn", agent_name="lead")
    state = AgentState(messages=[])
    await hook.before_agent(ctx, state)
    called = False

    async def handler(*_args):
        nonlocal called
        called = True
        return "edited"

    result = await hook.wrap_tool_call(
        ctx,
        state,
        SimpleNamespace(function=SimpleNamespace(name="edit")),
        handler,
    )

    assert result.startswith("BLOCKED — EASD pre-implementation work is read-only")
    assert called is False

    for status in ("draft", "accepted"):
        async with async_session_factory() as db:
            persisted = await trace_service.get_run(db, run.id)
            persisted.status = status
            db.add(persisted)
            await db.commit()
        state = AgentState(messages=[])
        await hook.before_agent(ctx, state)
        called = False
        result = await hook.wrap_tool_call(
            ctx,
            state,
            SimpleNamespace(function=SimpleNamespace(name="write")),
            handler,
        )
        assert result.startswith("BLOCKED — EASD pre-implementation work is read-only")
        assert called is False
