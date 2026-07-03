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

from app.agent.mode.team.tier_policy import (
    TIER_DENIED_TOOLS,
    denied_tools_for_tier,
    resolve_member_tier,
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
