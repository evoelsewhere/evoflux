"""Tests for task tiering in todo_manage.

Covers:
- Creating tasks with explicit tier values
- Default tier is 'simple'
- Updating tier on existing tasks
- Tier display in formatted output
- Tier persisted in store
- Backward compatibility (old stores without tier)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.tools.builtin.todo import (
    AnyAction,
    CreateAction,
    TODOS_FILENAME,
    UpdateAction,
    _normalize_store,
    _todo_manage,
)


@dataclass
class MockState:
    metadata: dict[str, Any]


@pytest.fixture
def tmp_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SandboxConfig:
    monkeypatch.setattr(
        "app.core.config.settings.EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    sandbox = SandboxConfig(workspace=str(tmp_path), session_id="session-tier")
    set_sandbox(sandbox)
    yield sandbox


@pytest.fixture
def todos_file(tmp_sandbox: SandboxConfig) -> Path:
    return tmp_sandbox.metadata_path(TODOS_FILENAME)


# ── Create with tier ─────────────────────────────────────────────────────────


class TestCreateWithTier:
    @pytest.mark.asyncio
    async def test_default_tier_is_simple(
        self, tmp_sandbox: SandboxConfig, todos_file: Path
    ):
        """Tasks without explicit tier default to 'simple'."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Basic task",
                status="pending",
                priority="medium",
            )
        ]
        await _todo_manage(actions=actions, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "simple"

    @pytest.mark.asyncio
    async def test_explicit_tier_trivial(
        self, tmp_sandbox: SandboxConfig, todos_file: Path
    ):
        """Trivial tier is persisted correctly."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Quick lookup",
                status="pending",
                priority="low",
                tier="trivial",
            )
        ]
        await _todo_manage(actions=actions, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "trivial"

    @pytest.mark.asyncio
    async def test_explicit_tier_complex(
        self, tmp_sandbox: SandboxConfig, todos_file: Path
    ):
        """Complex tier is persisted correctly."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Multi-member refactor",
                status="pending",
                priority="high",
                tier="complex",
            )
        ]
        await _todo_manage(actions=actions, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "complex"

    @pytest.mark.asyncio
    async def test_explicit_tier_multi_step(
        self, tmp_sandbox: SandboxConfig, todos_file: Path
    ):
        """Multi-step tier is persisted correctly."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Research + write report",
                status="pending",
                priority="medium",
                tier="multi_step",
            )
        ]
        await _todo_manage(actions=actions, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "multi_step"

    def test_invalid_tier_rejected(self):
        """Invalid tier values are rejected by Pydantic."""
        with pytest.raises(ValidationError):
            CreateAction(
                action="create",
                content="Bad tier",
                status="pending",
                priority="medium",
                tier="mega",  # type: ignore[arg-type]
            )


# ── Update tier ──────────────────────────────────────────────────────────────


class TestUpdateTier:
    @pytest.mark.asyncio
    async def test_update_tier(self, tmp_sandbox: SandboxConfig, todos_file: Path):
        """Tier can be updated on an existing task."""
        create: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Initially simple",
                status="pending",
                priority="medium",
                tier="simple",
            )
        ]
        await _todo_manage(actions=create, _state=None)

        update: list[AnyAction] = [
            UpdateAction(
                action="update",
                task_id="task_1",
                tier="complex",
            )
        ]
        await _todo_manage(actions=update, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "complex"

    @pytest.mark.asyncio
    async def test_update_without_tier_preserves_existing(
        self, tmp_sandbox: SandboxConfig, todos_file: Path
    ):
        """Updating other fields without setting tier keeps original tier."""
        create: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Has tier",
                status="pending",
                priority="medium",
                tier="multi_step",
            )
        ]
        await _todo_manage(actions=create, _state=None)

        update: list[AnyAction] = [
            UpdateAction(
                action="update",
                task_id="task_1",
                content="Updated content",
            )
        ]
        await _todo_manage(actions=update, _state=None)

        store = json.loads(todos_file.read_text())
        assert store["items"][0]["tier"] == "multi_step"
        assert store["items"][0]["content"] == "Updated content"


# ── Display ──────────────────────────────────────────────────────────────────


class TestTierDisplay:
    @pytest.mark.asyncio
    async def test_simple_tier_not_shown(self, tmp_sandbox: SandboxConfig):
        """Default 'simple' tier is not shown in output (clean/compact)."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Simple task",
                status="pending",
                priority="medium",
            )
        ]
        result = await _todo_manage(actions=actions, _state=None)
        assert "{simple}" not in result

    @pytest.mark.asyncio
    async def test_non_simple_tier_shown(self, tmp_sandbox: SandboxConfig):
        """Non-default tiers are shown in curly braces."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Complex refactor",
                status="pending",
                priority="high",
                tier="complex",
            )
        ]
        result = await _todo_manage(actions=actions, _state=None)
        assert "{complex}" in result

    @pytest.mark.asyncio
    async def test_trivial_tier_shown(self, tmp_sandbox: SandboxConfig):
        """Trivial tier is shown in output."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Quick answer",
                status="pending",
                priority="low",
                tier="trivial",
            )
        ]
        result = await _todo_manage(actions=actions, _state=None)
        assert "{trivial}" in result

    @pytest.mark.asyncio
    async def test_multi_step_tier_shown(self, tmp_sandbox: SandboxConfig):
        """Multi-step tier is shown in output."""
        actions: list[AnyAction] = [
            CreateAction(
                action="create",
                content="Research + write",
                status="pending",
                priority="medium",
                tier="multi_step",
            )
        ]
        result = await _todo_manage(actions=actions, _state=None)
        assert "{multi_step}" in result


# ── Backward compatibility ───────────────────────────────────────────────────


class TestTierBackwardCompat:
    def test_normalize_adds_default_tier(self):
        """Old store items without tier get 'simple' default."""
        store = {
            "counter": 1,
            "items": [
                {
                    "task_id": "task_1",
                    "content": "Old task",
                    "status": "pending",
                    "priority": "high",
                }
            ],
        }
        normalized = _normalize_store(store)
        assert normalized["items"][0]["tier"] == "simple"

    def test_normalize_preserves_existing_tier(self):
        """Existing tier values are not overwritten by normalize."""
        store = {
            "counter": 1,
            "items": [
                {
                    "task_id": "task_1",
                    "content": "Complex task",
                    "status": "pending",
                    "priority": "high",
                    "tier": "complex",
                }
            ],
        }
        normalized = _normalize_store(store)
        assert normalized["items"][0]["tier"] == "complex"
