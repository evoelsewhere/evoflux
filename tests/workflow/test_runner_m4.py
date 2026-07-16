"""M4: agent/gate/input/foreach + turn-boundary hooks.

The agent-node path is exercised against a FakeTeam that implements the
exact surface the runner touches (spawn/allowlist/inject/interrupt/busy) —
the real team integration points themselves are covered by the team-side
unit tests (allowlist in resolve_recipient/_spawn_locked, hook ordering in
_try_emit_done).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlmodel import col, select

import app.models.workflow  # noqa: F401
from app.workflow.models import parse_definition
from app.workflow.runner import WorkflowRunner


async def _wait(predicate, timeout: float = 10.0):
    for _ in range(int(timeout * 40)):
        if predicate():
            return
        await asyncio.sleep(0.025)
    raise AssertionError("condition not met in time")


class FakeTeam:
    """The exact runner-facing surface of AgentTeam."""

    def __init__(self) -> None:
        self.turn_allowed_blueprints: set[str] | None = None
        self.spawned: list[str] = []
        self.injected: list[str] = []
        self.busy_calls: list[bool] = []
        self.interrupted = False
        self._live: dict[str, list[str]] = {}

    def live_instances_for_blueprint(self, blueprint: str) -> list[str]:
        return self._live.get(blueprint, [])

    async def spawn(self, blueprint: str):
        self.spawned.append(blueprint)
        self._live.setdefault(blueprint, []).append(f"{blueprint}#1")

    async def inject_synthetic_turn(self, session_id: str, prompt: str):
        self.injected.append(prompt)
        return "message-id"

    def interrupt_turn(self):
        self.interrupted = True
        return []

    def set_inline_busy(self, busy: bool) -> None:
        self.busy_calls.append(busy)


@pytest.fixture
def fake_team(monkeypatch):
    team = FakeTeam()
    from app.services import team_manager

    monkeypatch.setattr(team_manager, "find_team_for_session", lambda _sid: team)
    return team


@pytest.mark.asyncio
async def test_agent_node_lifecycle_with_boundary_hooks(setup_db, fake_team):
    """Inject → allowlist set → capture at the boundary (fallback text from
    DB) → advance resumes → output feeds the next node."""
    from app.core import db as db_module
    from app.models.chat import ChatSession, SessionMessage

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: agentic
scope: forge
nodes:
  - { id: work, kind: agent, subagents: [debate], prompt: "Analyze {{inputs.thing}}" }
  - { id: shape, kind: transform, set: { got: "{{nodes.work.output.text}}" } }
edges:
  - { from: work, to: shape }
outputs:
  final: "{{nodes.shape.output.got}}"
""")

    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = str(session.id)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={"thing": "the bug"},
        scope_workspace=None,
    )

    # The drive task pre-spawns, sets the allowlist, injects, then waits.
    await _wait(lambda: len(fake_team.injected) == 1)
    assert fake_team.spawned == ["debate"]
    assert fake_team.turn_allowed_blueprints == {"debate"}
    assert fake_team.injected[0] == "Analyze the bug"
    assert state.pending_node == "work"

    # Simulate the lead's answer landing in the DB, then the barrier firing.
    async with db_module.async_session_factory() as db:
        from app.models.chat import ChatSession as _CS  # noqa: F401

        db.add(
            SessionMessage(
                session_id=session.id, role="assistant", content="It's a race."
            )
        )
        await db.commit()

    await runner.on_turn_boundary_capture(session_id)
    assert state.pending_node is None
    assert fake_team.turn_allowed_blueprints is None  # cleared at capture
    assert state.captured_output == {"text": "It's a race."}

    consumed = await runner.on_turn_boundary_advance(session_id)
    assert consumed is True

    await _wait(lambda: not runner.is_driving(session_id))
    from app.models.workflow import WorkflowExecution

    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "completed"
        assert execution.outputs == {"final": "It's a race."}


@pytest.mark.asyncio
async def test_advance_is_ignored_when_not_awaiting_boundary(setup_db, fake_team):
    runner = WorkflowRunner()
    assert await runner.on_turn_boundary_advance("no-such-session") is False


@pytest.mark.asyncio
async def test_agent_node_timeout_interrupts_team(setup_db, fake_team):
    from app.core import db as db_module
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: sluggish
scope: forge
nodes:
  - { id: work, kind: agent, subagents: [], prompt: p, timeout_s: 1 }
""")
    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=str(session.id),
        inputs={},
        scope_workspace=None,
    )
    await _wait(lambda: not runner.is_driving(str(session.id)), timeout=10)
    assert fake_team.interrupted is True
    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "failed"
        assert "timed out" in (execution.error or "")


@pytest.mark.asyncio
async def test_gate_round_trip_via_ask_user_service(setup_db, fake_team):
    """The gate is a literal ask_user: QuestionAskedEvent out, reply in via
    the session-keyed service registry, answer routes the edges."""
    from app.agent.ask_user import get_service_for_session
    from app.core import db as db_module
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: gated-flow
scope: forge
nodes:
  - { id: ask, kind: gate, title: "Deploy?", body: "to prod", choices: [go, halt] }
  - { id: deploy, kind: transform, set: { did: "deployed" } }
edges:
  - { from: ask, to: deploy, when: go }
""")
    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
    session_id = str(session.id)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )

    await _wait(lambda: state.status == "waiting_gate")
    svc = get_service_for_session(session_id)
    assert svc is not None
    request_id = next(iter(svc._pending))
    assert svc._pending[request_id].questions[0].question.startswith("Deploy?")
    assert svc.reply(request_id, ["go"]) is True

    await _wait(lambda: not runner.is_driving(session_id))
    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "completed"
    assert state.node_outputs["ask"] == {"choice": "go"}
    assert state.node_outputs["deploy"] == {"did": "deployed"}


@pytest.mark.asyncio
async def test_input_node_free_text_routes_through_switch(setup_db, fake_team):
    from app.agent.ask_user import get_service_for_session
    from app.core import db as db_module
    from app.models.chat import ChatSession

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: enviro
scope: forge
nodes:
  - { id: ask_env, kind: input, question: "Which env?" }
  - { id: route, kind: switch, value: "{{nodes.ask_env.output.text}}" }
  - { id: prod, kind: transform, set: { env: prod } }
  - { id: other, kind: transform, set: { env: other } }
edges:
  - { from: ask_env, to: route }
  - { from: route, to: prod, when: prod }
  - { from: route, to: other, when: "*" }
""")
    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
    session_id = str(session.id)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait(lambda: state.status == "waiting_gate")
    svc = get_service_for_session(session_id)
    request_id = next(iter(svc._pending))
    # Free-text answer (options list is empty for input nodes).
    assert svc._pending[request_id].questions[0].options == []
    svc.reply(request_id, ["prod"])

    await _wait(lambda: not runner.is_driving(session_id))
    assert state.node_outputs["prod"] == {"env": "prod"}
    assert "other" not in state.node_outputs


@pytest.mark.asyncio
async def test_stop_during_gate_cancels_cleanly(setup_db, fake_team):
    from app.core import db as db_module
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: stuck-gate
scope: forge
nodes:
  - { id: ask, kind: gate, title: t, choices: [a] }
""")
    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
    session_id = str(session.id)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait(lambda: state.status == "waiting_gate")
    assert await runner.stop(state.execution_id) is True
    await _wait(lambda: not runner.is_driving(session_id))
    async with db_module.async_session_factory() as db:
        execution = await db.get(WorkflowExecution, state.execution_id)
        assert execution.status == "stopped"


@pytest.mark.asyncio
async def test_foreach_tool_body_yields_iteration_rows(setup_db, fake_team):
    from app.core import db as db_module
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowNodeRun

    runner = WorkflowRunner()
    definition = parse_definition("""
schema_version: 1
name: loopy-tools
scope: forge
nodes:
  - id: seed
    kind: transform
    set: { names: '["a", "b", "c"]' }
  - id: each
    kind: foreach
    items: "{{nodes.seed.output.names}}"
    body:
      kind: tool
      tool: shell
      args: { command: "echo item-{{item}}-{{index}}" }
edges:
  - { from: seed, to: each }
outputs:
  n: "{{nodes.each.output.count}}"
""")
    async with db_module.async_session_factory() as db:
        session = ChatSession(mode="forge")
        db.add(session)
        await db.commit()
        await db.refresh(session)
    session_id = str(session.id)

    state = await runner.start(
        definition,
        definition_hash="0" * 64,
        session_id=session_id,
        inputs={},
        scope_workspace=None,
    )
    await _wait(lambda: not runner.is_driving(session_id), timeout=20)

    # items rendered from a JSON-string transform → parsed to a real list.
    assert state.node_outputs["each"]["count"] == 3
    assert "item-b-1" in state.node_outputs["each"]["items"][1]["text"]

    async with db_module.async_session_factory() as db:
        rows = (
            await db.exec(
                select(WorkflowNodeRun)
                .where(col(WorkflowNodeRun.execution_id) == state.execution_id)
                .where(col(WorkflowNodeRun.node_id) == "each")
            )
        ).all()
        iterations = sorted(row.iteration for row in rows)
        assert iterations == [0, 1, 2]


# ── team-side integration points ─────────────────────────────────────────────


def test_resolve_recipient_enforces_allowlist():
    from types import SimpleNamespace

    from app.agent.mode.team.team import AgentTeam

    team = object.__new__(AgentTeam)
    team.lead = SimpleNamespace(name="evoflux")
    team.members = {"debate#1": object(), "executor#1": object()}
    team.turn_allowed_blueprints = {"debate"}

    assert team.resolve_recipient("evoflux") == "evoflux"
    assert team.resolve_recipient("debate#1") == "debate#1"
    assert team.resolve_recipient("debate") == "debate#1"
    # Not on the node roster → unresolvable, even though it's live.
    assert team.resolve_recipient("executor#1") is None
    assert team.resolve_recipient("executor") is None

    team.turn_allowed_blueprints = None
    assert team.resolve_recipient("executor#1") == "executor#1"


def test_recipient_error_names_the_workflow_roster():
    from types import SimpleNamespace

    from app.agent.mode.team.tools import _recipient_error

    team = SimpleNamespace(
        turn_allowed_blueprints={"debate"},
        blueprints={"executor": object(), "debate": object()},
        lead=SimpleNamespace(name="evoflux"),
    )
    team.blueprint_allowed_this_turn = lambda bp: bp in team.turn_allowed_blueprints
    mailbox = SimpleNamespace(registered_agents=["evoflux", "executor#1"])

    message = _recipient_error(team, mailbox, "executor", sender="evoflux")
    assert "workflow node's roster" in message
    assert "debate" in message
