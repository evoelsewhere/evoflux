"""Tests for team_delegate tool — structured task delegation.

Covers:
- Single and multiple recipient delivery
- TaskSpec field population (goal, expected_output, constraints, context, priority)
- Content formatting (human-readable delegation message)
- Error handling (self-delegate, empty goal/expected_output, missing recipient)
- Validation of required fields
"""

from __future__ import annotations

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
        )
        assert "Task delegated" in result
        msg = mb.receive_nowait("executor#1")
        assert msg is not None
        assert "◉" in msg.content  # high priority icon
        assert "No breaking changes" in msg.content
        assert "cursor-based pagination" in msg.content
        assert "Depends on:" in msg.content

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
