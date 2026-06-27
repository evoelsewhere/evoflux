"""Tests for team_reject tool — structured rejection feedback loop.

Covers:
- Single and multiple recipient delivery
- RejectionFeedback field population (reason, issues, suggestions, severity)
- Content formatting (human-readable rejection message)
- Error handling (self-reject, empty reason, missing recipient)
- Severity levels (minor, major, redo) with correct icons/labels
"""

from __future__ import annotations

from app.agent.mode.team.mailbox import TeamMailbox
from app.agent.mode.team.reject import RejectionFeedback, make_team_reject_tool


def _make_mailbox(*agents: str) -> TeamMailbox:
    """Create a mailbox with the given agents registered."""
    mb = TeamMailbox()
    for name in agents:
        mb.register(name)
    return mb


class TestRejectionFeedbackSchema:
    """Test RejectionFeedback Pydantic model."""

    def test_minimal_feedback(self):
        """Only reason is semantically required."""
        fb = RejectionFeedback(reason="Missing tests")
        assert fb.reason == "Missing tests"
        assert fb.issues == []
        assert fb.suggestions == []
        assert fb.severity == "major"

    def test_full_feedback(self):
        """All fields populated."""
        fb = RejectionFeedback(
            reason="Output doesn't meet expected_output criteria",
            issues=["No error handling", "Hardcoded values", "No tests"],
            suggestions=["Add try/except", "Use env vars", "Add 3 pytest tests"],
            severity="redo",
        )
        assert fb.severity == "redo"
        assert len(fb.issues) == 3
        assert len(fb.suggestions) == 3

    def test_serialization(self):
        """model_dump produces expected structure."""
        fb = RejectionFeedback(reason="Incomplete", severity="minor")
        dumped = fb.model_dump(mode="json")
        assert dumped["reason"] == "Incomplete"
        assert dumped["severity"] == "minor"
        assert dumped["issues"] == []
        assert dumped["suggestions"] == []


class TestTeamRejectTool:
    """Test team_reject tool delivery and formatting."""

    async def test_reject_single_recipient(self):
        """Reject to one agent, verify mailbox delivery."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            reason="Missing error handling for network timeouts",
            issues=["No try/except around HTTP calls", "No retry logic"],
            suggestions=["Wrap requests in try/except", "Add exponential backoff"],
        )
        assert "Rejection sent to executor#1" in result
        assert "severity: major" in result

        msg = mb.receive_nowait("executor#1")
        assert msg is not None
        assert "REJECTED" in msg.content
        assert "Missing error handling" in msg.content
        assert "No try/except" in msg.content
        assert "Wrap requests" in msg.content

    async def test_reject_multiple_recipients(self):
        """Reject sent to multiple agents."""
        mb = _make_mailbox("explorer#1", "executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        result = await tool(
            to=["explorer#1", "executor#1"],
            reason="Both deliverables lack evidence",
        )
        assert "explorer#1" in result
        assert "executor#1" in result

    async def test_severity_minor(self):
        """Minor severity uses warning icon."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        await tool(
            to=["executor#1"],
            reason="Small typo in output",
            severity="minor",
        )
        msg = mb.receive_nowait("executor#1")
        assert "⚠️" in msg.content
        assert "MINOR FIXES NEEDED" in msg.content

    async def test_severity_major(self):
        """Major severity uses reject icon."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        await tool(
            to=["executor#1"],
            reason="Significant gaps in implementation",
            severity="major",
        )
        msg = mb.receive_nowait("executor#1")
        assert "❌" in msg.content
        assert "REWORK NEEDED" in msg.content

    async def test_severity_redo(self):
        """Redo severity uses stop icon."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        await tool(
            to=["executor#1"],
            reason="Wrong approach entirely",
            severity="redo",
        )
        msg = mb.receive_nowait("executor#1")
        assert "🚫" in msg.content
        assert "REDO FROM SCRATCH" in msg.content

    async def test_includes_fix_instruction(self):
        """Rejection message includes instruction to re-deliver via team_handoff."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        await tool(
            to=["executor#1"],
            reason="Incomplete",
        )
        msg = mb.receive_nowait("executor#1")
        assert "team_handoff" in msg.content

    async def test_empty_reason_rejected(self):
        """Empty reason returns error."""
        mb = _make_mailbox("executor#1", "lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        result = await tool(
            to=["executor#1"],
            reason="   ",
        )
        assert "Error" in result
        assert "reason" in result

    async def test_cannot_reject_self(self):
        """Self-rejection returns error."""
        mb = _make_mailbox("lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        result = await tool(
            to=["lead"],
            reason="Bad work",
        )
        assert "cannot reject yourself" in result

    async def test_unknown_recipient(self):
        """Unknown recipient returns helpful error."""
        mb = _make_mailbox("lead")
        tool = make_team_reject_tool(mb, agent_name="lead")

        result = await tool(
            to=["nonexistent"],
            reason="Bad work",
        )
        assert "not found" in result
