"""Tests for LSP tools (lsp_diagnostics, lsp_definition, lsp_references)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state(workspace: Path) -> MagicMock:
    state = MagicMock()
    state.metadata = {}
    from app.agent.sandbox import SandboxConfig, set_sandbox
    set_sandbox(SandboxConfig(workspace=workspace, session_id="test"))
    return state


# ── lsp_diagnostics ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lsp_diagnostics_no_issues(tmp_path: Path):
    """lsp_diagnostics returns OK when ruff finds no issues."""
    from app.agent.tools.builtin.lsp import lsp_diagnostics

    clean_file = tmp_path / "ok.py"
    clean_file.write_text("x = 1\n")

    state = _make_state(tmp_path)

    # Patch _run to simulate ruff returning empty JSON array
    with patch(
        "app.agent.tools.builtin.lsp._run",
        return_value=(0, "[]", ""),
    ):
        result = await lsp_diagnostics.arun(path="ok.py", _state=state)

    assert "OK" in result or "No issues" in result


@pytest.mark.asyncio
async def test_lsp_diagnostics_with_issues(tmp_path: Path):
    """lsp_diagnostics parses ruff JSON output and returns formatted issues."""
    from app.agent.tools.builtin.lsp import lsp_diagnostics

    py_file = tmp_path / "bad.py"
    py_file.write_text("import os\n")

    state = _make_state(tmp_path)

    ruff_output = json.dumps([
        {
            "code": "F401",
            "message": "'os' imported but unused",
            "filename": str(py_file),
            "location": {"row": 1, "column": 1},
        }
    ])

    with patch("app.agent.tools.builtin.lsp._run", return_value=(1, ruff_output, "")):
        result = await lsp_diagnostics.arun(path="bad.py", _state=state)

    assert "F401" in result
    assert "imported but unused" in result


@pytest.mark.asyncio
async def test_lsp_diagnostics_missing_path(tmp_path: Path):
    """lsp_diagnostics returns error for non-existent path."""
    from app.agent.tools.builtin.lsp import lsp_diagnostics

    state = _make_state(tmp_path)
    result = await lsp_diagnostics.arun(path="nonexistent.py", _state=state)
    assert "Error" in result or "does not exist" in result.lower()


# ── lsp_definition ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lsp_definition_no_workspace(tmp_path: Path):
    """lsp_definition returns helpful message when workspace is not indexed."""
    from app.agent.tools.builtin.lsp import lsp_definition

    state = _make_state(tmp_path)

    # Patch resolve_workspace_id to return None (not indexed)
    with patch(
        "app.services.code_graph_service.resolve_workspace_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with patch("app.core.db.async_session_factory") as mock_factory:
            mock_db = AsyncMock()
            mock_factory.return_value = mock_db
            result = await lsp_definition.arun(name="MyClass", _state=state)

    assert "not indexed" in result.lower() or "Info" in result


# ── lsp_references ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lsp_references_no_workspace(tmp_path: Path):
    """lsp_references returns helpful message when workspace is not indexed."""
    from app.agent.tools.builtin.lsp import lsp_references

    state = _make_state(tmp_path)

    with patch(
        "app.services.code_graph_service.resolve_workspace_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        with patch("app.core.db.async_session_factory") as mock_factory:
            mock_db = AsyncMock()
            mock_factory.return_value = mock_db
            result = await lsp_references.arun(name="my_func", _state=state)

    assert "not indexed" in result.lower() or "Info" in result
