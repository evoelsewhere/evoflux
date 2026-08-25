"""Tests for team_delegate tool — structured task delegation.

Covers:
- Single and multiple recipient delivery
- TaskSpec field population (goal, expected_output, constraints, context, priority)
- Content formatting (human-readable delegation message)
- Error handling (self-delegate, empty goal/expected_output, missing recipient)
- Validation of required fields
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid7

import pytest

import app.agent.mode.team.delegate as delegate_module
from app.agent.mode.team.delegate import TaskSpec, make_team_delegate_tool
from app.agent.mode.team.mailbox import TeamMailbox


def _make_mailbox(*agents: str) -> TeamMailbox:
    """Create a mailbox with the given agents registered."""
    mb = TeamMailbox()
    for name in agents:
        mb.register(name)
    return mb


class TestTaskSpecSchema:
    """Test TaskSpec Pydantic model."""

    def test_minimal_spec(self):
        """Only goal and expected_output are semantically required."""
        spec = TaskSpec(goal="Write tests", expected_output="All tests pass")
        assert spec.goal == "Write tests"
        assert spec.expected_output == "All tests pass"
        assert spec.constraints == []
        assert spec.context is None
        assert spec.priority == "normal"
        assert spec.depends_on == []
        assert spec.target_paths == []
        assert spec.exclusive_paths is True
        assert spec.isolation == "auto"
        assert spec.resolved_isolation == "shared"
        assert spec.target_repos == []
        assert spec.complexity == "auto"
        assert spec.trace_run_id is None
        assert spec.trace_plan_hash is None
        assert spec.plan_mission_id is None
        assert spec.acceptance_criteria == []

    def test_full_spec(self):
        """All fields populated."""
        spec = TaskSpec(
            goal="Implement retry logic",
            expected_output="team_handoff with code diff and test results",
            constraints=["Python 3.14 only", "No new dependencies"],
            context="See app/services/agent_service.py line 200",
            priority="high",
            depends_on=["task_1"],
        )
        assert spec.priority == "high"
        assert len(spec.constraints) == 2
        assert spec.depends_on == ["task_1"]

    def test_trace_contract_supports_direct_and_planned_identity(self):
        with pytest.raises(ValueError, match="EASD delegation requires"):
            TaskSpec(
                goal="Implement AC-1",
                expected_output="Verified implementation",
                trace_run_id=str(uuid7()),
            )

        direct = TaskSpec(
            goal="Implement AC-1 directly",
            expected_output="Verified implementation",
            trace_run_id=str(uuid7()),
            trace_spec_hash="f" * 64,
            acceptance_criteria=["AC-1"],
        )
        assert direct.trace_plan_hash is None
        assert direct.plan_mission_id is None

        spec = TaskSpec(
            goal="Implement AC-1",
            expected_output="Verified implementation",
            trace_run_id=str(uuid7()),
            trace_spec_hash="f" * 64,
            trace_plan_hash="e" * 64,
            plan_mission_id="M1",
            acceptance_criteria=["AC-1"],
        )
        assert spec.acceptance_criteria == ["AC-1"]
        assert spec.plan_mission_id == "M1"

    def test_serialization_excludes_none(self):
        """model_dump with exclude_none drops empty optional fields."""
        spec = TaskSpec(goal="Do X", expected_output="Y done")
        dumped = spec.model_dump(mode="json", exclude_none=True)
        assert "context" not in dumped
        assert "goal" in dumped
        assert "expected_output" in dumped


class TestTeamDelegateTool:
    """Test team_delegate tool delivery and formatting."""

    async def test_delegate_to_single_recipient(self):
        """Delegate to one agent, verify mailbox delivery."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            goal="Implement retry logic in agent_service.py",
            expected_output="Modified file with exponential backoff, all tests pass",
        )
        assert "Task delegated to executor#1" in result
        # Message delivered to executor's inbox
        msg = mb.receive_nowait("executor#1")
        assert msg is not None
        assert "TASK DELEGATION" in msg.content
        assert "Implement retry logic" in msg.content
        assert "Expected output:" in msg.content

    async def test_bare_blueprint_auto_spawns_and_inherits_user_context(
        self, monkeypatch
    ):
        """A normal delegation is one atomic spawn+assign operation."""
        mb = _make_mailbox("lead")

        class FakeTeam:
            mode = "work"
            blueprints = {"executor": object()}
            turn_allowed_blueprints = None
            lead = SimpleNamespace(session_id=str(uuid7()))

            def __init__(self):
                self.members = {}
                self.created_spec = None

            def resolve_recipient(self, name):
                if name in self.members:
                    return name
                live = self.live_instances_for_blueprint(name)
                return live[0] if len(live) == 1 else None

            def live_instances_for_blueprint(self, blueprint):
                return [
                    name for name in self.members if name.startswith(f"{blueprint}#")
                ]

            def blueprint_allowed_this_turn(self, blueprint):
                return blueprint in self.blueprints

            async def spawn(self, blueprint, *, confirm=False):
                assert confirm is True
                member = SimpleNamespace(name=f"{blueprint}#1", state="idle")
                self.members[member.name] = member
                mb.register(member.name)
                return member

            def current_user_request_for_delegation(self):
                return "Audit and improve agent collaboration"

            async def create_delegation_tasks(self, **kwargs):
                self.created_spec = kwargs["spec"]
                return [
                    SimpleNamespace(
                        id=uuid7(),
                        status="pending",
                        recipient="executor#1",
                    )
                ]

            async def dispatch_delegation_tasks(self, tasks):
                return None

        team = FakeTeam()
        monkeypatch.setattr(delegate_module, "_emit_delegation_event", lambda *a: None)
        tool = make_team_delegate_tool(mb, agent_name="lead", team=team)

        result = await tool(
            to=["executor"],
            goal="Implement the runtime changes",
            expected_output="Verified code and tests",
        )

        assert "executor#1" in result
        assert team.created_spec["parent_request"] == (
            "Audit and improve agent collaboration"
        )
        assert team.created_spec["peer_recipients"] == ["executor#1"]

    async def test_delegate_to_multiple_recipients(self):
        """Delegate same task to multiple agents."""
        mb = _make_mailbox("explorer#1", "executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["explorer#1", "executor#1"],
            goal="Research best practices",
            expected_output="List of 5 approaches with pros/cons",
        )
        assert "explorer#1" in result
        assert "executor#1" in result

    async def test_delegate_with_all_fields(self):
        """Full delegation with constraints, context, priority, depends_on."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            goal="Add pagination to /api/sessions",
            expected_output="team_handoff with code changes, ruff passes, 2+ tests added",
            constraints=[
                "No breaking changes to existing API",
                "Use cursor-based pagination",
            ],
            context="Current endpoint at app/api/routes/sessions.py returns all rows",
            priority="high",
            depends_on=["task_2"],
            target_paths=["app/api/routes/sessions.py"],
            complexity="multi_step",
        )
        assert "Task delegated" in result
        msg = mb.receive_nowait("executor#1")
        assert msg is not None
        assert "◉" in msg.content  # high priority icon
        assert "No breaking changes" in msg.content
        assert "cursor-based pagination" in msg.content
        assert "Depends on:" in msg.content
        assert "Target paths (exclusive):" in msg.content
        assert "**Complexity:** multi_step" in msg.content

    async def test_exclusive_paths_reject_multiple_recipients(self):
        mb = _make_mailbox("explorer#1", "executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["explorer#1", "executor#1"],
            goal="Edit the same module",
            expected_output="Implemented",
            target_paths=["app/shared.py"],
        )

        assert "exclusive target_paths" in result

    async def test_target_path_traversal_is_rejected(self):
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            goal="Unsafe",
            expected_output="No",
            target_paths=["../outside"],
        )

        assert "traversal-free" in result

    async def test_empty_goal_rejected(self):
        """Empty goal returns error."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            goal="   ",
            expected_output="something",
        )
        assert "Error" in result
        assert "goal" in result

    async def test_empty_expected_output_rejected(self):
        """Empty expected_output returns error."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            goal="Do something",
            expected_output="   ",
        )
        assert "Error" in result
        assert "expected_output" in result

    async def test_cannot_delegate_to_self(self):
        """Self-delegation returns error."""
        mb = _make_mailbox("lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["lead"],
            goal="Do something",
            expected_output="Done",
        )
        assert "cannot delegate to yourself" in result

    async def test_unknown_recipient(self):
        """Unknown recipient returns helpful error."""
        mb = _make_mailbox("lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        result = await tool(
            to=["nonexistent"],
            goal="Do something",
            expected_output="Done",
        )
        assert "not found" in result

    async def test_priority_icons(self):
        """Each priority level gets a distinct icon."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_delegate_tool(mb, agent_name="lead")

        for priority, icon in [
            ("low", "○"),
            ("normal", "●"),
            ("high", "◉"),
            ("critical", "🔴"),
        ]:
            await tool(
                to=["executor#1"],
                goal="Test task",
                expected_output="Done",
                priority=priority,
            )
            msg = mb.receive_nowait("executor#1")
            assert icon in msg.content, f"Expected {icon} for priority={priority}"
