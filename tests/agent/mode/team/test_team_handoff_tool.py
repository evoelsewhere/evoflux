"""Tests for team_handoff tool — structured artifact delivery.

Covers:
- Single and multiple recipient delivery
- Artifact field population (summary, findings, evidence, confidence, etc.)
- Content formatting (human-readable + structured metadata)
- Partial vs final status
- Error handling (self-message, missing recipient, invalid confidence)
- Role-specific descriptions (lead vs member)
"""

from __future__ import annotations

from app.agent.mode.team.handoff import HandoffArtifact, make_team_handoff_tool
from app.agent.mode.team.mailbox import TeamMailbox


def _make_mailbox(*agents: str) -> TeamMailbox:
    """Create a mailbox with the given agents registered."""
    mb = TeamMailbox()
    for name in agents:
        mb.register(name)
    return mb


class TestHandoffArtifactSchema:
    """Test HandoffArtifact Pydantic model."""

    def test_minimal_artifact(self):
        """Only summary is required."""
        artifact = HandoffArtifact(summary="Task complete.")
        assert artifact.summary == "Task complete."
        assert artifact.status == "final"
        assert artifact.findings == []
        assert artifact.evidence == []
        assert artifact.confidence is None
        assert artifact.next_actions == []
        assert artifact.raw_data is None

    def test_full_artifact(self):
        """All fields populated."""
        artifact = HandoffArtifact(
            summary="Found 3 critical issues.",
            status="final",
            findings=["Issue A", "Issue B", "Issue C"],
            evidence=["file.py:42", "logs/error.log"],
            confidence=0.85,
            next_actions=["Fix Issue A first"],
            raw_data="Full analysis text...",
        )
        assert len(artifact.findings) == 3
        assert artifact.confidence == 0.85
        assert artifact.status == "final"

    def test_partial_status(self):
        """Partial handoff for incremental delivery."""
        artifact = HandoffArtifact(
            summary="Initial findings — more coming.",
            status="partial",
            findings=["Preliminary result"],
        )
        assert artifact.status == "partial"

    def test_serialization_excludes_none(self):
        """model_dump with exclude_none drops empty optional fields."""
        artifact = HandoffArtifact(summary="Done.")
        dumped = artifact.model_dump(mode="json", exclude_none=True)
        assert "raw_data" not in dumped
        assert "confidence" not in dumped
        assert "summary" in dumped


class TestTeamHandoffTool:
    """Test team_handoff tool delivery and formatting."""

    async def test_send_to_single_recipient(self):
        """Handoff to one agent, verify mailbox delivery."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["lead"],
            summary="Found 2 patterns.",
            findings=["Pattern A: supervisor", "Pattern B: sequential"],
        )

        assert "Handoff delivered" in result
        assert "lead" in result

        msg = await mb.receive("lead")
        assert "HANDOFF" in msg.content
        assert "Found 2 patterns." in msg.content
        assert "Pattern A: supervisor" in msg.content

    async def test_send_to_multiple_recipients(self):
        """Handoff to 2 agents, verify both receive."""
        mb = _make_mailbox("explorer", "consultant", "debate")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["consultant", "debate"],
            summary="Research complete.",
            findings=["Finding 1"],
        )

        assert "consultant" in result
        assert "debate" in result

        msg_c = await mb.receive("consultant")
        msg_d = await mb.receive("debate")
        assert "HANDOFF" in msg_c.content
        assert "HANDOFF" in msg_d.content

    async def test_self_only_returns_error(self):
        """Handoff to only self returns error."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["explorer"],
            summary="Self-handoff",
        )

        assert "No valid recipients" in result

    async def test_missing_recipient_returns_error(self):
        """Handoff to non-existent agent returns error."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["ghost"],
            summary="Will fail.",
        )

        assert "not found" in result

    async def test_content_includes_findings(self):
        """Message content includes formatted findings list."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="Analysis done.",
            findings=["Issue A is critical", "Issue B is minor"],
            evidence=["app/core.py:100", "logs/debug.log"],
        )

        msg = await mb.receive("lead")
        assert "Issue A is critical" in msg.content
        assert "Issue B is minor" in msg.content
        assert "app/core.py:100" in msg.content

    async def test_content_includes_confidence(self):
        """Message content includes confidence percentage."""
        mb = _make_mailbox("consultant", "lead")
        tool = make_team_handoff_tool(mb, agent_name="consultant")

        await tool(
            to=["lead"],
            summary="Strategy proposal.",
            confidence=0.92,
        )

        msg = await mb.receive("lead")
        assert "92%" in msg.content

    async def test_partial_status_label(self):
        """Partial handoffs show PARTIAL label."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="First batch.",
            status="partial",
        )

        msg = await mb.receive("lead")
        assert "PARTIAL" in msg.content

    async def test_final_status_label(self):
        """Final handoffs show FINAL label."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="All done.",
            status="final",
        )

        msg = await mb.receive("lead")
        assert "FINAL" in msg.content

    async def test_next_actions_in_content(self):
        """Next actions appear in formatted content."""
        mb = _make_mailbox("consultant", "lead")
        tool = make_team_handoff_tool(mb, agent_name="consultant")

        await tool(
            to=["lead"],
            summary="Review complete.",
            next_actions=["Implement option B", "Run stress tests"],
        )

        msg = await mb.receive("lead")
        assert "Implement option B" in msg.content
        assert "Run stress tests" in msg.content

    async def test_lead_gets_lead_description(self):
        """make_team_handoff_tool with role='lead' has lead description."""
        mb = _make_mailbox("lead", "worker")
        tool = make_team_handoff_tool(mb, agent_name="lead", role="lead")

        assert "structured result" in tool.description.lower()

    async def test_member_gets_member_description(self):
        """make_team_handoff_tool with role='member' has member description."""
        mb = _make_mailbox("lead", "worker")
        tool = make_team_handoff_tool(mb, agent_name="worker", role="member")

        assert "required" in tool.description.lower()

    async def test_invalid_confidence_returns_error(self):
        """Confidence outside 0-1 range returns error."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["lead"],
            summary="Bad confidence.",
            confidence=1.5,
        )

        assert "Error" in result
        assert "confidence" in result.lower()

    async def test_raw_data_not_in_formatted_content(self):
        """Raw data is in the message but summary + findings are the readable part."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="Quick summary.",
            raw_data="Very long raw analysis data...",
        )

        msg = await mb.receive("lead")
        assert "Quick summary." in msg.content
        # raw_data should not be in the human-readable formatted section
        # (it's in the structured artifact only)

    async def test_returns_success_message(self):
        """Tool returns 'Handoff delivered to ...' on success."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        result = await tool(
            to=["lead"],
            summary="Done.",
        )

        assert "Handoff delivered" in result
        assert "lead" in result

    async def test_from_agent_in_content_header(self):
        """Content header includes sender name."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="My work.",
        )

        msg = await mb.receive("lead")
        assert "[explorer]" in msg.content
        assert msg.from_agent == "explorer"
