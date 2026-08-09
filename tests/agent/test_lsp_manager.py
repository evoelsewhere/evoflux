"""Unit tests for LSP framing and server discovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.agent.lsp_manager import (
    LanguageServerClient,
    LanguageServerUnavailable,
    SPECS,
    _content_length,
    _locations,
    get_language_server,
)


def test_content_length_header_is_case_insensitive():
    assert _content_length(b"content-length: 42\r\nOther: x\r\n\r\n") == 42


def test_locations_normalizes_single_and_list_results():
    location = {"uri": "file:///tmp/a.py", "range": {}}
    assert _locations(location) == [location]
    assert _locations([location, "bad"]) == [location]
    assert _locations(None) == []


async def test_missing_language_server_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.py"
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr("app.agent.lsp_manager.shutil.which", lambda _name: None)

    with pytest.raises(LanguageServerUnavailable, match="language server"):
        await get_language_server(tmp_path, source)


@pytest.mark.asyncio
async def test_sync_document_tracks_unsaved_content_not_mtime(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    client = LanguageServerClient(
        tmp_path, SPECS[0], ("pyright-langserver", "--stdio")
    )
    client.start = AsyncMock()
    client.notify = AsyncMock()

    _uri, changed = await client.sync_document(source, "value: int = 1\n")
    assert changed is True
    _uri, changed = await client.sync_document(source, "value: int = 1\n")
    assert changed is False
    _uri, changed = await client.sync_document(source, "value: int = 'bad'\n")
    assert changed is True

    methods = [call.args[0] for call in client.notify.await_args_list]
    assert methods == ["textDocument/didOpen", "textDocument/didChange"]
