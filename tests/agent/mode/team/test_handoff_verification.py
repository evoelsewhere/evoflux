"""Tests for computational validation in team_handoff.

Covers:
- Verification model construction
- HandoffArtifact with verification field
- Verification params in team_handoff tool
- Verification formatting in handoff content
- Verification in serialized artifact
- Omitted verification (pure research)
"""

from __future__ import annotations

import pytest

from app.agent.mode.team.handoff import (
    HandoffArtifact,
    Verification,
    make_team_handoff_tool,
)
from app.agent.mode.team.mailbox import TeamMailbox


def _make_mailbox(*agents: str) -> TeamMailbox:
    mb = TeamMailbox()
    for name in agents:
        mb.register(name)
    return mb


# ── Verification model ───────────────────────────────────────────────────────


class TestVerificationModel:
    def test_verified_with_method(self):
        v = Verification(verified=True, method="read output file")
        assert v.verified is True
        assert v.method == "read output file"
        assert v.result is None

    def test_verified_with_result(self):
        v = Verification(
            verified=True,
            method="ran tests",
            result="all 12 tests pass",
        )
        assert v.result == "all 12 tests pass"

    def test_not_verified(self):
        v = Verification(verified=False, method="skipped — pure analysis")
        assert v.verified is False

    def test_serialization_excludes_none_result(self):
        v = Verification(verified=True, method="ls directory")
        dumped = v.model_dump(mode="json", exclude_none=True)
        assert "result" not in dumped
        assert dumped["verified"] is True
        assert dumped["method"] == "ls directory"


# ── HandoffArtifact with verification ────────────────────────────────────────


class TestHandoffArtifactVerification:
    def test_artifact_without_verification(self):
        """Default: no verification."""
        artifact = HandoffArtifact(summary="Done.")
        assert artifact.verification is None

    def test_artifact_with_verification(self):
        """Full verification attached."""
        artifact = HandoffArtifact(
            summary="File written.",
            verification=Verification(
                verified=True,
                method="read file",
                result="45 lines, valid JSON",
            ),
        )
        assert artifact.verification is not None
        assert artifact.verification.verified is True
        assert artifact.verification.method == "read file"

    def test_artifact_serialization_includes_verification(self):
        """Verification is included in model_dump."""
        artifact = HandoffArtifact(
            summary="Config updated.",
            verification=Verification(
                verified=True,
                method="read config",
                result="key present",
            ),
        )
        dumped = artifact.model_dump(mode="json", exclude_none=True)
        assert "verification" in dumped
        assert dumped["verification"]["verified"] is True

    def test_artifact_serialization_excludes_none_verification(self):
        """None verification is excluded with exclude_none."""
        artifact = HandoffArtifact(summary="Research only.")
        dumped = artifact.model_dump(mode="json", exclude_none=True)
        assert "verification" not in dumped


# ── Tool verification params ─────────────────────────────────────────────────


class TestHandoffToolVerification:
    @pytest.mark.asyncio
    async def test_verified_true_in_content(self):
        """Verified handoff shows checkmark in formatted content."""
        mb = _make_mailbox("executor", "lead")
        tool = make_team_handoff_tool(mb, agent_name="executor")

        await tool(
            to=["lead"],
            summary="File written successfully to disk as expected.",
            findings=["Output file created at expected path"],
            verified=True,
            verification_method="read output file",
            verification_result="file exists, 45 lines",
        )

        msg = await mb.receive("lead")
        assert "✅" in msg.content
        assert "read output file" in msg.content
        assert "file exists, 45 lines" in msg.content

    @pytest.mark.asyncio
    async def test_verified_false_in_content(self):
        """Unverified handoff shows warning in formatted content."""
        mb = _make_mailbox("executor", "lead")
        tool = make_team_handoff_tool(mb, agent_name="executor")

        await tool(
            to=["lead"],
            summary="Command ran but verification was not performed.",
            findings=["Command executed with exit code 0"],
            verified=False,
            verification_method="no time to check",
        )

        msg = await mb.receive("lead")
        assert "⚠️" in msg.content
        assert "Not verified" in msg.content

    @pytest.mark.asyncio
    async def test_no_verification_no_line(self):
        """Omitted verification produces no verification line."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="Pure research findings on the topic.",
            findings=["Insight 1"],
            status="partial",
        )

        msg = await mb.receive("lead")
        assert "Verification" not in msg.content
        assert "✅" not in msg.content
        assert "⚠️" not in msg.content

    @pytest.mark.asyncio
    async def test_verified_without_method_uses_unspecified(self):
        """verified=True with no method falls back to 'unspecified'."""
        mb = _make_mailbox("executor", "lead")
        tool = make_team_handoff_tool(mb, agent_name="executor")

        await tool(
            to=["lead"],
            summary="Task completed successfully and output verified.",
            findings=["Task done"],
            verified=True,
        )

        msg = await mb.receive("lead")
        assert "✅" in msg.content
        assert "unspecified" in msg.content

    @pytest.mark.asyncio
    async def test_verification_in_artifact_metadata(self):
        """Structured artifact stashed on message includes verification."""
        mb = _make_mailbox("executor", "lead")
        tool = make_team_handoff_tool(mb, agent_name="executor")

        await tool(
            to=["lead"],
            summary="All tests pass in the test suite successfully.",
            findings=["12 tests pass"],
            verified=True,
            verification_method="ran test suite",
            verification_result="all 12 tests pass",
        )

        msg = await mb.receive("lead")
        artifact = msg.__dict__.get("_handoff_artifact", {})
        assert artifact.get("verification", {}).get("verified") is True
        assert artifact["verification"]["method"] == "ran test suite"
        assert artifact["verification"]["result"] == "all 12 tests pass"

    @pytest.mark.asyncio
    async def test_no_verification_not_in_artifact(self):
        """Omitted verification not present in artifact metadata."""
        mb = _make_mailbox("explorer", "lead")
        tool = make_team_handoff_tool(mb, agent_name="explorer")

        await tool(
            to=["lead"],
            summary="Analysis done with partial results.",
            findings=["Partial insight found"],
            status="partial",
        )

        msg = await mb.receive("lead")
        artifact = msg.__dict__.get("_handoff_artifact", {})
        assert "verification" not in artifact

    @pytest.mark.asyncio
    async def test_verified_false_without_method_uses_skipped(self):
        """verified=False with no method falls back to 'skipped'."""
        mb = _make_mailbox("executor", "lead")
        tool = make_team_handoff_tool(mb, agent_name="executor")

        await tool(
            to=["lead"],
            summary="Partial work delivered, not fully complete yet.",
            findings=["Initial implementation done"],
            verified=False,
        )

        msg = await mb.receive("lead")
        assert "⚠️" in msg.content
        assert "skipped" in msg.content
