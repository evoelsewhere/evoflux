"""Tests for static source tools and real LSP tool contracts."""

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
async def test_lsp_diagnostics_no_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """lsp_diagnostics returns OK when ruff finds no issues."""
    from app.agent.tools.builtin.lsp import static_diagnostics

    clean_file = tmp_path / "ok.py"
    clean_file.write_text("x = 1\n")

    state = _make_state(tmp_path)
    monkeypatch.setattr(
        "app.agent.tools.builtin.lsp.shutil.which", lambda _name: "ruff"
    )

    # Patch _run to simulate ruff returning empty JSON array
    with patch(
        "app.agent.tools.builtin.lsp._run",
        return_value=(0, "[]", ""),
    ):
        result = await static_diagnostics.arun(path="ok.py", _state=state)

    assert "OK" in result or "No issues" in result


@pytest.mark.asyncio
async def test_lsp_diagnostics_with_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """lsp_diagnostics parses ruff JSON output and returns formatted issues."""
    from app.agent.tools.builtin.lsp import static_diagnostics

    py_file = tmp_path / "bad.py"
    py_file.write_text("import os\n")

    state = _make_state(tmp_path)
    monkeypatch.setattr(
        "app.agent.tools.builtin.lsp.shutil.which", lambda _name: "ruff"
    )

    ruff_output = json.dumps(
        [
            {
                "code": "F401",
                "message": "'os' imported but unused",
                "filename": str(py_file),
                "location": {"row": 1, "column": 1},
            }
        ]
    )

    with patch("app.agent.tools.builtin.lsp._run", return_value=(1, ruff_output, "")):
        result = await static_diagnostics.arun(path="bad.py", _state=state)

    assert "F401" in result
    assert "imported but unused" in result


@pytest.mark.asyncio
async def test_lsp_diagnostics_missing_path(tmp_path: Path):
    """lsp_diagnostics returns error for non-existent path."""
    from app.agent.tools.builtin.lsp import static_diagnostics

    state = _make_state(tmp_path)
    result = await static_diagnostics.arun(path="nonexistent.py", _state=state)
    assert "Error" in result or "does not exist" in result.lower()


@pytest.mark.asyncio
async def test_real_lsp_diagnostics_uses_persistent_client(tmp_path: Path):
    from app.agent.tools.builtin.lsp import lsp_diagnostics

    source = tmp_path / "live.py"
    source.write_text("value: int = 'wrong'\n", encoding="utf-8")
    state = _make_state(tmp_path)
    client = AsyncMock()
    client.diagnostics.return_value = [
        {
            "severity": 1,
            "code": "reportAssignmentType",
            "message": "str is not assignable to int",
            "range": {"start": {"line": 0, "character": 13}},
        }
    ]

    with patch(
        "app.agent.tools.builtin.lsp.get_language_server",
        new_callable=AsyncMock,
        return_value=client,
    ):
        result = await lsp_diagnostics.arun(path="live.py", _state=state)

    assert "live LSP diagnostic" in result
    assert "live.py:1:14" in result
    assert "reportAssignmentType" in result


@pytest.mark.asyncio
async def test_real_lsp_definition_requires_exact_position(tmp_path: Path):
    from app.agent.tools.builtin.lsp import lsp_definition

    source = tmp_path / "live.py"
    target = tmp_path / "definition.py"
    source.write_text("call()\n", encoding="utf-8")
    target.write_text("def call(): ...\n", encoding="utf-8")
    state = _make_state(tmp_path)
    client = AsyncMock()
    client.definition.return_value = [
        {
            "uri": target.as_uri(),
            "range": {"start": {"line": 0, "character": 4}},
        }
    ]

    with patch(
        "app.agent.tools.builtin.lsp.get_language_server",
        new_callable=AsyncMock,
        return_value=client,
    ):
        result = await lsp_definition.arun(
            path="live.py", line=1, column=2, _state=state
        )

    assert "definition.py:1:5" in result


@pytest.mark.asyncio
async def test_lsp_semantic_returns_unapplied_rename_workspace_edit(tmp_path: Path):
    from app.agent.tools.builtin.lsp import lsp_semantic

    source = tmp_path / "live.py"
    source.write_text("value = 1\n", encoding="utf-8")
    state = _make_state(tmp_path)
    client = AsyncMock()
    client.rename.return_value = {
        "changes": {
            source.as_uri(): [
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 5},
                    },
                    "newText": "renamed",
                }
            ]
        }
    }

    with patch(
        "app.agent.tools.builtin.lsp.get_language_server",
        new_callable=AsyncMock,
        return_value=client,
    ):
        result = await lsp_semantic.arun(
            action="rename",
            path="live.py",
            line=1,
            column=2,
            new_name="renamed",
            _state=state,
        )

    payload = json.loads(result)
    assert payload["changes"][source.as_uri()][0]["newText"] == "renamed"
    client.rename.assert_awaited_once_with(source.resolve(), 1, 2, "renamed")


@pytest.mark.asyncio
async def test_lsp_semantic_code_actions_include_live_diagnostics(tmp_path: Path):
    from app.agent.tools.builtin.lsp import lsp_semantic

    source = tmp_path / "live.py"
    source.write_text("value = 1\n", encoding="utf-8")
    state = _make_state(tmp_path)
    client = AsyncMock()
    client.diagnostics.return_value = [{"message": "Type mismatch"}]
    client.code_actions.return_value = [
        {"title": "Fix type mismatch", "kind": "quickfix"}
    ]

    with patch(
        "app.agent.tools.builtin.lsp.get_language_server",
        new_callable=AsyncMock,
        return_value=client,
    ):
        result = await lsp_semantic.arun(
            action="code_actions",
            path="live.py",
            line=1,
            column=1,
            end_line=1,
            end_column=6,
            _state=state,
        )

    assert json.loads(result)[0]["kind"] == "quickfix"
    client.code_actions.assert_awaited_once_with(
        source.resolve(),
        start_line=1,
        start_column=1,
        end_line=1,
        end_column=6,
        diagnostics=[{"message": "Type mismatch"}],
    )
