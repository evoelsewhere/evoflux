"""Tests for team-aware context compaction.

Covers:
- TEAM_SUMMARY_PROMPT template interpolation
- build_team_summarization_hook factory
- Hook uses coding-mode keep_last (0 = summarise everything)
- Peer names formatting (populated and empty)
- Role interpolation (lead vs member)
- Disabled when threshold <= 0
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.agent.hooks.summarization import (
    CODING_KEEP_LAST_ASSISTANTS,
    TEAM_SUMMARY_PROMPT,
    build_team_summarization_hook,
)


def _mock_provider() -> MagicMock:
    """Create a minimal mock LLM provider."""
    p = MagicMock()
    p.model = "test-model"
    return p


class TestTeamSummaryPrompt:
    def test_prompt_contains_template_placeholders(self):
        """The raw template has format placeholders."""
        assert "{agent_name}" in TEAM_SUMMARY_PROMPT
        assert "{role}" in TEAM_SUMMARY_PROMPT
        assert "{lead_name}" in TEAM_SUMMARY_PROMPT
        assert "{peers}" in TEAM_SUMMARY_PROMPT

    def test_prompt_interpolation_with_peers(self):
        rendered = TEAM_SUMMARY_PROMPT.format(
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peers="explorer#1, consultant#1",
        )
        assert "executor#1" in rendered
        assert "member" in rendered
        assert "main" in rendered
        assert "explorer#1, consultant#1" in rendered
        # No unresolved placeholders
        assert "{agent_name}" not in rendered
        assert "{role}" not in rendered

    def test_prompt_interpolation_no_peers(self):
        rendered = TEAM_SUMMARY_PROMPT.format(
            agent_name="main",
            role="lead",
            lead_name="main",
            peers="(none)",
        )
        assert "(none)" in rendered

    def test_prompt_has_team_role_section(self):
        assert "## Team Role" in TEAM_SUMMARY_PROMPT

    def test_prompt_has_assigned_tasks_section(self):
        assert "## Assigned Tasks" in TEAM_SUMMARY_PROMPT

    def test_prompt_has_handoff_history_section(self):
        assert "## Handoff History" in TEAM_SUMMARY_PROMPT

    def test_prompt_has_peer_interactions_section(self):
        assert "## Peer Interactions" in TEAM_SUMMARY_PROMPT


class TestBuildTeamSummarizationHook:
    def test_returns_hook(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=["explorer#1"],
        )
        assert hook is not None

    def test_uses_coding_keep_last(self):
        """Team compaction uses keep_last=0 (summarise everything)."""
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        assert hook is not None
        assert hook._keep_last_assistants == CODING_KEEP_LAST_ASSISTANTS

    def test_prompt_contains_agent_name(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=["explorer#1"],
        )
        assert hook is not None
        assert "executor#1" in hook._summary_prompt

    def test_prompt_contains_lead_name(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="explorer#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        assert hook is not None
        assert "main" in hook._summary_prompt

    def test_prompt_contains_peers(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=["explorer#1", "consultant#1"],
        )
        assert hook is not None
        assert "explorer#1, consultant#1" in hook._summary_prompt

    def test_empty_peers_shows_none(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        assert hook is not None
        assert "(none)" in hook._summary_prompt

    def test_lead_role(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="main",
            role="lead",
            lead_name="main",
            peer_names=["executor#1"],
        )
        assert hook is not None
        assert "Role: lead" in hook._summary_prompt

    def test_disabled_when_threshold_zero(self, monkeypatch):
        monkeypatch.setattr(
            "app.agent.hooks.summarization.DEFAULT_PROMPT_TOKEN_THRESHOLD", 0
        )
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="executor#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        assert hook is None

    def test_mode_param_ignored(self):
        """Mode is irrelevant — team always uses TEAM_SUMMARY_PROMPT."""
        hook_coding = build_team_summarization_hook(
            _mock_provider(),
            mode="coding",
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        hook_normal = build_team_summarization_hook(
            _mock_provider(),
            mode="forge",
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
        )
        assert hook_coding is not None
        assert hook_normal is not None
        # Both use the same team-specific prompt, not mode-specific
        assert "## Team Role" in hook_coding._summary_prompt
        assert "## Team Role" in hook_normal._summary_prompt


class TestStateSnapshotInjection:
    """Tests for injecting shared team state into the summarisation prompt."""

    def test_no_snapshot_no_extra_content(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
            state_snapshot=None,
        )
        assert hook is not None
        assert "Preserve the following shared team state" not in hook._summary_prompt

    def test_empty_snapshot_no_extra_content(self):
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
            state_snapshot="",
        )
        assert hook is not None
        assert "Preserve the following shared team state" not in hook._summary_prompt

    def test_snapshot_appended_to_prompt(self):
        snapshot = '## Shared Team State Snapshot\n- `api_url` = "https://example.com"  (set by explorer#1)'
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
            state_snapshot=snapshot,
        )
        assert hook is not None
        assert "Preserve the following shared team state" in hook._summary_prompt
        assert "api_url" in hook._summary_prompt
        assert "explorer#1" in hook._summary_prompt

    def test_snapshot_comes_after_template(self):
        """The template rules should precede the snapshot."""
        snapshot = '## Shared Team State Snapshot\n- `key` = "val"'
        hook = build_team_summarization_hook(
            _mock_provider(),
            agent_name="exec#1",
            role="member",
            lead_name="main",
            peer_names=[],
            state_snapshot=snapshot,
        )
        assert hook is not None
        prompt = hook._summary_prompt
        template_end = prompt.index("Do not mention the summary process")
        snapshot_start = prompt.index("Preserve the following shared team state")
        assert snapshot_start > template_end
