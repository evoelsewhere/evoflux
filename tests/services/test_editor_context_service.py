from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.editor_context_service import (
    EditorContextError,
    build_editor_context,
)


@pytest.mark.asyncio
async def test_context_collects_explicit_bounded_provenance(tmp_path: Path):
    active = tmp_path / "src/main.py"
    active.parent.mkdir()
    active.write_text("value = helper()\n", encoding="utf-8")
    mention = tmp_path / "docs/note.md"
    mention.parent.mkdir()
    mention.write_text("relevant note\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Follow project rules.\n", encoding="utf-8")
    (tmp_path / ".aiignore").write_text("secret/**\n", encoding="utf-8")
    ignored = tmp_path / "secret/token.txt"
    ignored.parent.mkdir()
    ignored.write_text("do not send\n", encoding="utf-8")

    with patch(
        "app.services.editor_context_service._graph_context",
        new_callable=AsyncMock,
        return_value=([{"name": "helper"}], [], []),
    ):
        context = await build_editor_context(
            tmp_path,
            active_file="src/main.py",
            content="value = helper()\n",
            document_version=4,
            selection={
                "text": "helper()",
                "start_line": 1,
                "start_column": 9,
                "end_line": 1,
                "end_column": 17,
            },
            cursor_symbol="helper",
            diagnostics=[{"message": "problem"}],
            mention_paths=["docs/note.md", "docs", "secret/token.txt"],
            relevant_terminal_failure="tests failed",
        )

    assert context.active_file == "src/main.py"
    assert context.document_version == 4
    assert context.selection is not None
    assert context.selection["text"] == "helper()"
    assert context.attachments[0] == {
        "path": "docs/note.md",
        "content": "relevant note\n",
    }
    assert context.attachments[1]["path"] == "docs/"
    assert "docs/note.md" in context.attachments[1]["content"]
    assert context.project_instructions[0]["path"] == "AGENTS.md"
    assert context.related_symbols == [{"name": "helper"}]
    assert {item.kind for item in context.provenance} >= {
        "active_file",
        "attachment",
        "project_instructions",
        "related_symbols",
        "terminal_failure",
    }
    assert "do not send" not in str(context.to_dict())


@pytest.mark.asyncio
async def test_active_file_respects_aiignore(tmp_path: Path):
    target = tmp_path / "secret.py"
    target.write_text("TOKEN = 'x'\n", encoding="utf-8")
    (tmp_path / ".aiignore").write_text("secret.py\n", encoding="utf-8")

    with pytest.raises(EditorContextError, match=".aiignore"):
        await build_editor_context(
            tmp_path,
            active_file="secret.py",
            content=target.read_text(),
            document_version=1,
            selection=None,
            cursor_symbol=None,
            diagnostics=[],
        )
