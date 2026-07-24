"""Tests for team_state tool — shared cross-member KV store.

Covers:
- Set / get / list / delete operations
- Owner tracking and attribution
- Overwrite semantics
- Error handling (missing key, missing value)
- JSON-serializable value types (string, number, bool, list, dict)
- Empty state
- Persistence across invocations (load/save cycle)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.mode.team.shared_state import (
    STATE_FILENAME,
    _load_state,
    _save_state,
    format_state_snapshot,
    make_team_state_tool,
)
from app.agent.sandbox import SandboxConfig, set_sandbox


@pytest.fixture
def tmp_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SandboxConfig:
    monkeypatch.setattr(
        "app.core.config.settings.EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    sandbox = SandboxConfig(workspace=str(tmp_path), session_id="session-state")
    set_sandbox(sandbox)
    return sandbox


@pytest.fixture
def state_file(tmp_sandbox: SandboxConfig) -> Path:
    return Path(str(tmp_sandbox.workspace_root)) / ".evoflux" / STATE_FILENAME


# ── Set action ───────────────────────────────────────────────────────────


class TestSetAction:
    @pytest.mark.asyncio
    async def test_set_stores_value(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="set", key="api_url", value="https://example.com")
        assert "Stored" in result
        assert "'api_url'" in result

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["api_url"]["value"] == "https://example.com"
        assert raw["api_url"]["owner"] == "explorer#1"
        assert "updated_at" in raw["api_url"]

    @pytest.mark.asyncio
    async def test_set_overwrites_existing(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="k", value="v1")
        await tool(action="set", key="k", value="v2")

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["k"]["value"] == "v2"

    @pytest.mark.asyncio
    async def test_set_different_owners(self, tmp_sandbox, state_file):
        tool_a = make_team_state_tool("explorer#1")
        tool_b = make_team_state_tool("executor#1")
        await tool_a(action="set", key="k1", value="from_a")
        await tool_b(action="set", key="k2", value="from_b")

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["k1"]["owner"] == "explorer#1"
        assert raw["k2"]["owner"] == "executor#1"

    @pytest.mark.asyncio
    async def test_set_requires_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="set", key=None, value="x")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_set_requires_value(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="set", key="k", value=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_set_numeric_value(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="count", value=42)
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["count"]["value"] == 42

    @pytest.mark.asyncio
    async def test_set_bool_value(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="flag", value=True)
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["flag"]["value"] is True

    @pytest.mark.asyncio
    async def test_set_list_value(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="items", value=["a", "b", "c"])
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["items"]["value"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_set_dict_value(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(
            action="set", key="config", value={"host": "localhost", "port": 8080}
        )
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert raw["config"]["value"] == {"host": "localhost", "port": 8080}


# ── Get action ───────────────────────────────────────────────────────────


class TestGetAction:
    @pytest.mark.asyncio
    async def test_get_existing_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="url", value="https://example.com")
        result = await tool(action="get", key="url")
        assert "https://example.com" in result
        assert "explorer#1" in result

    @pytest.mark.asyncio
    async def test_get_missing_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="get", key="nonexistent")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_get_requires_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="get", key=None)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_cross_agent_read(self, tmp_sandbox):
        """One agent sets, another reads."""
        tool_a = make_team_state_tool("explorer#1")
        tool_b = make_team_state_tool("executor#1")
        await tool_a(action="set", key="shared", value="data")
        result = await tool_b(action="get", key="shared")
        assert "data" in result
        assert "explorer#1" in result  # shows who set it


# ── List action ──────────────────────────────────────────────────────────


class TestListAction:
    @pytest.mark.asyncio
    async def test_list_empty(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="list")
        assert "No shared state" in result

    @pytest.mark.asyncio
    async def test_list_with_entries(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="alpha", value=1)
        await tool(action="set", key="beta", value="two")
        result = await tool(action="list")
        assert "alpha" in result
        assert "beta" in result
        assert "Shared team state" in result

    @pytest.mark.asyncio
    async def test_list_sorted_keys(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="zebra", value=1)
        await tool(action="set", key="alpha", value=2)
        result = await tool(action="list")
        alpha_pos = result.index("alpha")
        zebra_pos = result.index("zebra")
        assert alpha_pos < zebra_pos


# ── Delete action ────────────────────────────────────────────────────────


class TestDeleteAction:
    @pytest.mark.asyncio
    async def test_delete_existing(self, tmp_sandbox, state_file):
        tool = make_team_state_tool("explorer#1")
        await tool(action="set", key="tmp", value="data")
        result = await tool(action="delete", key="tmp")
        assert "Deleted" in result

        raw = json.loads(state_file.read_text(encoding="utf-8"))
        assert "tmp" not in raw

    @pytest.mark.asyncio
    async def test_delete_missing_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="delete", key="nope")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_delete_requires_key(self, tmp_sandbox):
        tool = make_team_state_tool("explorer#1")
        result = await tool(action="delete", key=None)
        assert "Error" in result


# ── Tool metadata ────────────────────────────────────────────────────────


class TestToolMetadata:
    def test_tool_name(self):
        tool = make_team_state_tool("explorer#1")
        assert tool.name == "team_state"

    def test_tool_description_non_empty(self):
        tool = make_team_state_tool("explorer#1")
        assert len(tool.description) > 50


# ── Low-level store helpers ──────────────────────────────────────────────


class TestStoreHelpers:
    def test_load_missing_file(self, tmp_sandbox):
        result = _load_state()
        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_sandbox):
        data = {"k": {"value": "v", "owner": "test", "updated_at": 1.0}}
        _save_state(data)
        loaded = _load_state()
        assert loaded == data

    def test_load_corrupt_file(self, tmp_sandbox, state_file):
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("not json", encoding="utf-8")
        result = _load_state()
        assert result == {}


# ── format_state_snapshot ────────────────────────────────────────────────


class TestFormatStateSnapshot:
    def test_empty_store_returns_empty(self, tmp_sandbox):
        result = format_state_snapshot()
        assert result == ""

    def test_single_entry(self, tmp_sandbox):
        _save_state(
            {
                "api_url": {
                    "value": "https://example.com",
                    "owner": "explorer#1",
                    "updated_at": 1.0,
                }
            }
        )
        result = format_state_snapshot()
        assert "## Shared Team State Snapshot" in result
        assert "`api_url`" in result
        assert "https://example.com" in result
        assert "explorer#1" in result

    def test_multiple_entries_sorted(self, tmp_sandbox):
        _save_state(
            {
                "z_key": {"value": "last", "owner": "a#1", "updated_at": 1.0},
                "a_key": {"value": "first", "owner": "b#1", "updated_at": 2.0},
            }
        )
        result = format_state_snapshot()
        lines = result.strip().split("\n")
        # Header + 2 entries
        assert len(lines) == 3
        assert "a_key" in lines[1]
        assert "z_key" in lines[2]

    def test_non_string_values(self, tmp_sandbox):
        _save_state(
            {
                "count": {"value": 42, "owner": "x#1", "updated_at": 1.0},
                "flags": {"value": [True, False], "owner": "x#1", "updated_at": 1.0},
            }
        )
        result = format_state_snapshot()
        assert "42" in result
        assert "[true, false]" in result
