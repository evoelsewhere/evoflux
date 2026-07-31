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
    SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS,
    SIDE_CHAT_SESSION_TAG,
    TIER_DENIED_TOOLS,
    WEBBRIDGE_SESSION_DENIED_WEB_TOOLS,
    deferred_tools_for_run,
    denied_tools_for_tier,
    resolve_member_tier,
    side_chat_session_excluded_tools,
    webbridge_session_excluded_tools,
)
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.tools import Tool
from app.webbridge_tags import WEBBRIDGE_SESSION_TAG


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

    def test_trivial_denies_new_side_effecting_tools_from_metadata(self):
        future_tool = Tool(
            lambda: None,
            name="future_side_effect",
            deferred=True,
            read_only=False,
        )

        denied = denied_tools_for_tier("trivial", [future_tool])

        assert "future_side_effect" in denied

    def test_trivial_allows_new_read_only_tools_from_metadata(self):
        future_tool = Tool(
            lambda: None,
            name="future_inspector",
            deferred=True,
            read_only=True,
        )

        denied = denied_tools_for_tier("trivial", [future_tool])

        assert "future_inspector" not in denied

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


# ── Registry-driven deferred tools ───────────────────────────────────────


class TestDefaultDeferredTools:
    def test_includes_browser_tools(self):
        from app.agent.loader import _default_tool_registry

        registry = _default_tool_registry()
        assert registry["browser_use"].deferred
        assert registry["webbridge"].deferred

    def test_includes_long_tail_tools(self):
        from app.agent.loader import _default_tool_registry

        registry = _default_tool_registry()
        expected = {
            "aim_units",
            "aim_compare",
            "terminal_run",
            "worktree_start",
            "worktree_finish",
            "lsp_diagnostics",
            "lsp_definition",
            "lsp_references",
            "visualize_read_me",
            "show_widget",
            "create_pull_request",
            "schedule_task",
        }
        assert all(registry[name].deferred for name in expected)
        assert all(registry[name].deferred_summary for name in expected)

    def test_excludes_core_coding_tools(self):
        """Tools nearly every turn needs must never be deferred."""
        from app.agent.loader import _default_tool_registry

        registry = _default_tool_registry()
        assert not any(
            registry[name].deferred
            for name in (
                "read",
                "write",
                "edit",
                "grep",
                "glob",
                "shell",
                "todo_manage",
                "skill",
            )
        )

    def test_loader_is_core_and_read_only(self):
        from app.agent.loader import _default_tool_registry

        loader = _default_tool_registry()["load_tool"]
        assert not loader.deferred
        assert loader.read_only

    def test_lead_registry_core_stays_between_ten_and_fifteen_tools(self):
        from app.agent.builtin_prompts import tier_tools
        from app.agent.loader import _default_tool_registry

        registry = _default_tool_registry()
        expected_core = {
            "edit",
            "glob",
            "grep",
            "load_tool",
            "ls",
            "patch",
            "read",
            "shell",
            "skill",
            "todo_manage",
            "write",
        }
        for mode in ("work", "coding", "aim"):
            granted = set(tier_tools(registry, mode=mode, role="lead"))
            granted.update({"skill", "todo_manage", "schedule_task", "note"})
            eager = {name for name in granted if not registry[name].deferred}
            assert 10 <= len(eager) <= 15
            assert eager == expected_core

    def test_actual_coding_lead_payload_has_fourteen_eager_tools(self):
        from app.agent.builtin_prompts import tier_tools
        from app.agent.loader import _default_tool_registry
        from tests.agent.mode.team.conftest import MockTeamProvider

        registry = _default_tool_registry()
        names = set(tier_tools(registry, mode="coding", role="lead"))
        names.update({"skill", "todo_manage", "schedule_task", "note"})
        agent = Agent(
            name="lead",
            llm_provider=MockTeamProvider(),
            tools=[registry[name] for name in sorted(names)],
        )
        lead = TeamLead(agent)
        team = AgentTeam(lead=lead, mode="coding")
        merged = {
            tool.name: tool
            for tool in (*agent._tools.values(), *team.get_injected_tools("lead"))
        }

        eager = {name for name, tool in merged.items() if not tool.deferred}

        assert eager == {
            "edit",
            "glob",
            "grep",
            "load_tool",
            "ls",
            "patch",
            "read",
            "shell",
            "skill",
            "team_delegate",
            "team_manage",
            "team_message",
            "todo_manage",
            "write",
        }


class TestDeferredTools:
    @staticmethod
    def _tool(name: str, *, deferred: bool = False) -> Tool:
        return Tool(lambda: None, name=name, deferred=deferred)

    def test_browser_and_preview_stay_deferred_until_explicitly_loaded(self):
        tools = [
            self._tool("load_tool"),
            self._tool("browser_use", deferred=True),
            self._tool("preview", deferred=True),
            self._tool("webbridge", deferred=True),
            self._tool("lsp_diagnostics", deferred=True),
        ]

        deferred = deferred_tools_for_run(tools)

        assert {"browser_use", "preview", "webbridge", "lsp_diagnostics"} <= deferred

    def test_webbridge_tag_reveals_webbridge_without_headless_browser(self):
        tools = [
            self._tool("load_tool"),
            self._tool("browser_use", deferred=True),
            self._tool("webbridge", deferred=True),
        ]

        deferred = deferred_tools_for_run(tools, reveal_webbridge=True)

        assert "webbridge" not in deferred
        assert "browser_use" in deferred


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


# Representative lead tool set: workspace/core tools, competing web backends,
# deferred loaders, injected team tools, and browser/non-browser MCP tools.
def _policy_tool(
    name: str,
    *,
    capabilities: tuple[str, ...] = (),
    origin: str = "builtin",
) -> Tool:
    tool = Tool(lambda: None, name=name, capabilities=capabilities)
    tool.origin = origin
    return tool


_LEAD_REGISTRY_TOOLS = [
    _policy_tool(
        name,
        capabilities=(
            ("browser",)
            if name == "mcp_browser_navigate"
            else ("webbridge-safe",)
            if name == "mcp_filesystem_read_file"
            else ()
        ),
        origin="mcp" if name.startswith("mcp_") else "builtin",
    )
    for name in [
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
        "load_tool",
        "preview",
        "mcp_browser_navigate",
        "mcp_filesystem_read_file",
        "team_message",
        "team_handoff",
        "team_state",
        "team_manage",
        "team_delegate",
        "team_reject",
        "team_worktree",
    ]
]


class TestWebbridgeSessionExcludedTools:
    def test_web_tools_excluded(self):
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert {"browser_use", "web_search", "web_fetch", "image_search"} <= excluded

    def test_workspace_and_loader_tools_survive(self):
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert {
            "read",
            "write",
            "shell",
            "skill",
            "load_tool",
            "preview",
            "mcp_filesystem_read_file",
        }.isdisjoint(excluded)

    def test_denied_web_tools_match_pinned_contract(self):
        assert WEBBRIDGE_SESSION_DENIED_WEB_TOOLS == frozenset(
            {"browser_use", "web_search", "web_fetch", "image_search"}
        )

    def test_mcp_tools_excluded(self):
        # An MCP browser server must not bypass the webbridge-only rule.
        excluded = webbridge_session_excluded_tools(_LEAD_REGISTRY_TOOLS)
        assert "mcp_browser_navigate" in excluded

    def test_mcp_name_does_not_imply_browser_capability(self):
        tool = _policy_tool(
            "mcp_playwright_navigate",
            capabilities=("webbridge-safe",),
            origin="mcp",
        )

        assert tool.name not in webbridge_session_excluded_tools([tool])

    def test_unclassified_mcp_tool_is_excluded(self):
        tool = _policy_tool("mcp_custom_action", origin="mcp")

        assert tool.name in webbridge_session_excluded_tools([tool])

    def test_all_injected_team_tools_survive(self):
        injected = {
            "team_message",
            "team_handoff",
            "todo_manage",
            "team_state",
            "team_manage",
            "team_delegate",
            "team_reject",
            "team_worktree",
        }

        excluded = webbridge_session_excluded_tools(
            [Tool(lambda: None, name=name) for name in {"webbridge", *injected}]
        )

        assert injected.isdisjoint(excluded)


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
        assert "read and edit files" in prompt
        assert "delegate workspace work" in prompt
        assert "browser_use, web_search, web_fetch" in prompt

    def test_untagged_lead_prompt_has_no_webbridge_suffix(self):
        team = AgentTeam(lead=self._make_lead())
        prompt = team.lead.build_protocol("base", team)
        assert "WebBridge session" not in prompt


# ── Side Chat session scoping ────────────────────────────────────────────


class TestSideChatExcludedTools:
    @staticmethod
    def _make_tool(name: str, *, read_only: bool = False) -> Tool:
        def implementation() -> None:
            return None

        return Tool(implementation, name=name, read_only=read_only)

    def test_new_tools_are_denied_by_default(self):
        tools = [
            self._make_tool("read", read_only=True),
            self._make_tool("terminal_run"),
            self._make_tool("future_plugin_tool"),
        ]

        assert side_chat_session_excluded_tools(tools) == frozenset(
            {"terminal_run", "future_plugin_tool"}
        )

    def test_does_not_exclude_read_tools(self):
        tools = [
            self._make_tool(name, read_only=True)
            for name in ("read", "grep", "glob", "ls")
        ]

        assert side_chat_session_excluded_tools(tools) == frozenset()

    def test_always_excludes_coordination_and_presentation_tools(self):
        tools = [
            self._make_tool(name, read_only=True)
            for name in SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS
        ]

        assert side_chat_session_excluded_tools(tools) == (
            SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS
        )


class TestSideChatSessionTagOnTeam:
    def _make_lead(self):
        from tests.agent.mode.team.conftest import MockTeamProvider

        return TeamLead(Agent(name="lead", llm_provider=MockTeamProvider()))

    def test_tagged_lead_prompt_has_side_chat_suffix(self):
        team = AgentTeam(
            lead=self._make_lead(), session_tags=frozenset({SIDE_CHAT_SESSION_TAG})
        )
        prompt = team.lead.build_protocol("base", team)
        assert "Side Chat session" in prompt
        assert "read-only" in prompt

    def test_untagged_lead_prompt_has_no_side_chat_suffix(self):
        team = AgentTeam(lead=self._make_lead())
        prompt = team.lead.build_protocol("base", team)
        assert "Side Chat session" not in prompt

    def test_webbridge_and_side_chat_suffixes_independent(self):
        """A team tagged only "webbridge" must not also get the side-chat
        suffix, and vice versa — the two elif-free `if`s must not bleed
        into each other."""
        webbridge_team = AgentTeam(
            lead=self._make_lead(), session_tags=frozenset({WEBBRIDGE_SESSION_TAG})
        )
        prompt = webbridge_team.lead.build_protocol("base", webbridge_team)
        assert "WebBridge session" in prompt
        assert "Side Chat session" not in prompt
