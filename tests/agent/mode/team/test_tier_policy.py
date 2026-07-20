"""Tests for tier-based tool access policies.

Covers:
- TIER_DENIED_TOOLS mapping completeness
- denied_tools_for_tier for each tier level
- resolve_member_tier from todo store
- Tier resolution with multiple tasks (highest wins)
- Tier resolution with completed/cancelled tasks (ignored)
- Edge cases (no tasks, unknown tier, None tier)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.agent_loop import Agent
from app.agent.mode.team.member import TeamLead
from app.agent.mode.team.team import AgentTeam
from app.agent.mode.team.tier_policy import (
    TIER_DENIED_TOOLS,
    WEBBRIDGE_SESSION_ALLOWED_TOOLS,
    WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS,
    WEBBRIDGE_SESSION_TAG,
    denied_tools_for_tier,
    resolve_member_tier,
    webbridge_session_excluded_tools,
)
from app.agent.sandbox import SandboxConfig, set_sandbox


# ── denied_tools_for_tier ────────────────────────────────────────────────


class TestDeniedToolsForTier:
    def test_trivial_denies_write_tools(self):
        denied = denied_tools_for_tier("trivial")
        assert "write" in denied
        assert "edit" in denied
        assert "patch" in denied
        assert "rm" in denied

    def test_trivial_denies_execution_tools(self):
        denied = denied_tools_for_tier("trivial")
        assert "shell" in denied
        assert "bg" in denied
        assert "python" in denied

    def test_trivial_denies_browser(self):
        denied = denied_tools_for_tier("trivial")
        assert "browser_use" in denied

    def test_simple_denies_browser(self):
        denied = denied_tools_for_tier("simple")
        assert "browser_use" in denied

    def test_simple_allows_write_tools(self):
        denied = denied_tools_for_tier("simple")
        assert "write" not in denied
        assert "edit" not in denied
        assert "shell" not in denied

    def test_multi_step_no_restrictions(self):
        denied = denied_tools_for_tier("multi_step")
        assert len(denied) == 0

    def test_complex_no_restrictions(self):
        denied = denied_tools_for_tier("complex")
        assert len(denied) == 0

    def test_none_tier_no_restrictions(self):
        denied = denied_tools_for_tier(None)
        assert len(denied) == 0

    def test_unknown_tier_no_restrictions(self):
        denied = denied_tools_for_tier("unknown_tier")
        assert len(denied) == 0

    def test_all_tiers_present_in_mapping(self):
        assert "trivial" in TIER_DENIED_TOOLS
        assert "simple" in TIER_DENIED_TOOLS
        assert "multi_step" in TIER_DENIED_TOOLS
        assert "complex" in TIER_DENIED_TOOLS


# ── resolve_member_tier ──────────────────────────────────────────────────


@pytest.fixture
def tmp_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SandboxConfig:
    monkeypatch.setattr(
        "app.core.config.settings.EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    sandbox = SandboxConfig(workspace=str(tmp_path), session_id="session-tier")
    set_sandbox(sandbox)
    return sandbox


def _write_todos(tmp_sandbox: SandboxConfig, items: list[dict]) -> None:
    """Write a todo store to disk at the session artifact path."""
    from app.core.config import settings

    todos_dir = Path(settings.EVOFLUX_DATA_DIR) / "sessions" / tmp_sandbox.session_id
    todos_dir.mkdir(parents=True, exist_ok=True)
    store = {"counter": len(items), "items": items}
    (todos_dir / ".todos.json").write_text(
        json.dumps(store, indent=2), encoding="utf-8"
    )


class TestResolveMemberTier:
    def test_no_tasks_returns_none(self, tmp_sandbox):
        _write_todos(tmp_sandbox, [])
        assert resolve_member_tier("exec#1") is None

    def test_single_pending_task(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "do X",
                    "status": "pending",
                    "tier": "simple",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "simple"

    def test_single_in_progress_task(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "do X",
                    "status": "in_progress",
                    "tier": "complex",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "complex"

    def test_completed_tasks_ignored(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "done",
                    "status": "completed",
                    "tier": "complex",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") is None

    def test_cancelled_tasks_ignored(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "nope",
                    "status": "cancelled",
                    "tier": "complex",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") is None

    def test_highest_tier_wins(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "easy",
                    "status": "pending",
                    "tier": "trivial",
                    "assigned_to": "exec#1",
                },
                {
                    "task_id": "task_2",
                    "content": "hard",
                    "status": "in_progress",
                    "tier": "multi_step",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "multi_step"

    def test_complex_beats_all(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "easy",
                    "status": "pending",
                    "tier": "simple",
                    "assigned_to": "exec#1",
                },
                {
                    "task_id": "task_2",
                    "content": "hard",
                    "status": "pending",
                    "tier": "complex",
                    "assigned_to": "exec#1",
                },
                {
                    "task_id": "task_3",
                    "content": "mid",
                    "status": "in_progress",
                    "tier": "multi_step",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "complex"

    def test_other_agent_tasks_ignored(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "not mine",
                    "status": "pending",
                    "tier": "complex",
                    "assigned_to": "explorer#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") is None

    def test_claimed_by_fallback(self, tmp_sandbox):
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "claimed",
                    "status": "in_progress",
                    "tier": "multi_step",
                    "claimed_by": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "multi_step"

    def test_default_tier_is_simple(self, tmp_sandbox):
        """Tasks without an explicit tier default to 'simple'."""
        _write_todos(
            tmp_sandbox,
            [
                {
                    "task_id": "task_1",
                    "content": "no tier",
                    "status": "pending",
                    "assigned_to": "exec#1",
                },
            ],
        )
        assert resolve_member_tier("exec#1") == "simple"

    def test_no_todo_file(self, tmp_sandbox):
        """When the todo file doesn't exist, returns None."""
        assert resolve_member_tier("exec#1") is None


# ── WebBridge session scoping ────────────────────────────────────────────

# Representative lead tool set (registry keys): the allowlisted names, the
# web tools that must be excluded, loader-managed lead tools, and an MCP tool.
_LEAD_REGISTRY_TOOLS = [
    "webbridge",
    "ask_user",
    "todo_manage",
    "note",
    "date",
    "browser_use",
    "web_search",
    "web_fetch",
    "image_search",
    "schedule_task",
    "skill",
    "read",
    "write",
    "shell",
    "mcp_playwright_navigate",
]


class TestWebbridgeSessionExcludedTools:
    def test_web_tools_excluded(self):
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert {"browser_use", "web_search", "web_fetch", "image_search"} <= excluded

    def test_allowlist_survives(self):
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert WEBBRIDGE_SESSION_ALLOWED_TOOLS.isdisjoint(excluded)

    def test_allowlist_matches_pinned_contract(self):
        assert WEBBRIDGE_SESSION_ALLOWED_TOOLS == frozenset(
            {"webbridge", "ask_user", "todo_manage", "note", "date"}
        )

    def test_everything_outside_allowlist_excluded(self):
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert excluded >= (
            frozenset(_LEAD_REGISTRY_TOOLS) - WEBBRIDGE_SESSION_ALLOWED_TOOLS
        )

    def test_mcp_tools_excluded(self):
        # An MCP browser server must not bypass the webbridge-only rule.
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert "mcp_playwright_navigate" in excluded

    def test_roster_tools_excluded(self):
        # Injected (non-registry) lead tools that could spawn/delegate to
        # non-scoped members are denied even though they are never in
        # tool_names.
        excluded = webbridge_session_excluded_tools(["webbridge"])
        assert WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS <= excluded
        assert WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS == frozenset(
            {"team_manage", "team_delegate", "team_reject"}
        )


class TestWebbridgeSessionTagOnTeam:
    def _make_lead(self):
        from tests.agent.mode.team.conftest import MockTeamProvider

        return TeamLead(Agent(name="lead", llm_provider=MockTeamProvider()))

    def test_session_tags_default_empty(self):
        team = AgentTeam(lead=self._make_lead())
        assert team.session_tags == frozenset()
        # Untagged → no webbridge scoping, lead keeps full access (no regression).
        assert WEBBRIDGE_SESSION_TAG not in team.session_tags

    def test_tagged_lead_prompt_has_webbridge_suffix(self):
        team = AgentTeam(
            lead=self._make_lead(), session_tags=frozenset({WEBBRIDGE_SESSION_TAG})
        )
        prompt = team.lead.build_protocol("base", team)
        assert "WebBridge session" in prompt
        assert "webbridge" in prompt
        assert "browser_use/web_search/web_fetch are unavailable" in prompt

    def test_untagged_lead_prompt_has_no_webbridge_suffix(self):
        team = AgentTeam(lead=self._make_lead())
        prompt = team.lead.build_protocol("base", team)
        assert "WebBridge session" not in prompt
