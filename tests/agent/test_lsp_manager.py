"""Unit tests for LSP framing and server discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.lsp_manager import (
    LanguageServerUnavailable,
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
