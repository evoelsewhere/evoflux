"""Unit tests for LSP framing and server discovery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.lsp_manager import (
    LanguageServerClient,
    LanguageServerUnavailable,
    SPECS,
    _content_length,
    language_server_spec,
    _locations,
    get_language_server,
    managed_language_server_command,
    resolve_language_server_command,
    system_language_server_command,
)


def test_content_length_header_is_case_insensitive():
    assert _content_length(b"content-length: 42\r\nOther: x\r\n\r\n") == 42


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("main.cpp", "cpp"),
        ("Main.java", "java"),
        ("app.kt", "kotlin"),
        ("index.php", "php"),
        ("styles.scss", "css"),
        ("config.yaml", "yaml"),
        ("README.md", "markdown"),
        ("app.dart", "dart"),
    ],
)
def test_common_language_server_mappings(filename: str, language: str):
    spec = language_server_spec(Path(filename))
    assert spec is not None
    assert spec.language_id == language


def test_locations_normalizes_single_and_list_results():
    location = {"uri": "file:///tmp/a.py", "range": {}}
    assert _locations(location) == [location]
    assert _locations([location, "bad"]) == [location]
    assert _locations(None) == []


def test_managed_server_is_preferred_over_system_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    spec = next(item for item in SPECS if item.language_id == "typescript")
    managed = tmp_path / "node_modules" / ".bin" / "typescript-language-server"
    managed.parent.mkdir(parents=True)
    managed.write_text("#!/bin/sh\n", encoding="utf-8")
    managed.chmod(0o755)
    monkeypatch.setattr(
        "app.agent.lsp_manager.managed_language_server_root", lambda _language: tmp_path
    )
    monkeypatch.setattr(
        "app.agent.lsp_manager.shutil.which",
        lambda _name: "/usr/local/bin/typescript-language-server",
    )

    assert managed_language_server_command(spec) == (str(managed), "--stdio")
    command, source = resolve_language_server_command(spec) or ((), "")
    assert command == (str(managed), "--stdio")
    assert source == "managed"


def test_rustup_proxy_without_component_is_not_reported_ready(
    monkeypatch: pytest.MonkeyPatch,
):
    spec = next(item for item in SPECS if item.language_id == "rust")
    monkeypatch.setattr(
        "app.agent.lsp_manager.shutil.which",
        lambda _name: "/Users/test/.cargo/bin/rust-analyzer",
    )
    monkeypatch.setattr(
        "app.agent.lsp_manager.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    assert system_language_server_command(spec) is None


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
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
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


@pytest.mark.asyncio
async def test_semantic_requests_use_synced_document_and_one_based_positions(
    tmp_path: Path,
):
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client.sync_document = AsyncMock(return_value=(source.as_uri(), True))
    client.request = AsyncMock(
        side_effect=[
            {"contents": "int"},
            [{"title": "Fix value", "kind": "quickfix"}],
            {"changes": {source.as_uri(): []}},
            [],
            [{"name": "value", "kind": 13}],
            [{"name": "workspace_value", "kind": 13}],
        ]
    )

    hover = await client.hover(source, 3, 5, "value = 2\n")
    actions = await client.code_actions(
        source,
        start_line=3,
        start_column=5,
        end_line=3,
        end_column=10,
        diagnostics=[{"message": "bad"}],
        content="value = 2\n",
    )
    rename = await client.rename(source, 3, 5, "renamed", "value = 2\n")
    formatting = await client.formatting(source, "value = 2\n")
    document_symbols = await client.document_symbols(source, "value = 2\n")
    workspace_symbols = await client.workspace_symbols("value")

    assert hover == {"contents": "int"}
    assert actions[0]["kind"] == "quickfix"
    assert rename == {"changes": {source.as_uri(): []}}
    assert formatting == []
    assert document_symbols[0]["name"] == "value"
    assert workspace_symbols[0]["name"] == "workspace_value"
    hover_params = client.request.await_args_list[0].args[1]
    assert hover_params["position"] == {"line": 2, "character": 4}
    action_params = client.request.await_args_list[1].args[1]
    assert action_params["range"]["start"] == {"line": 2, "character": 4}
    assert action_params["context"]["diagnostics"] == [{"message": "bad"}]


@pytest.mark.asyncio
async def test_organize_imports_requests_source_action_for_whole_document(
    tmp_path: Path,
):
    source = tmp_path / "source.py"
    source.write_text("import os\n\nvalue = 1\n", encoding="utf-8")
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client.code_actions = AsyncMock(return_value=[{"title": "Organize Imports"}])

    result = await client.organize_imports(source)

    assert result == [{"title": "Organize Imports"}]
    assert client.code_actions.await_args.kwargs["only"] == ["source.organizeImports"]
    assert client.code_actions.await_args.kwargs["end_line"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        ("workspace/configuration", {"items": [{}, {}]}, [{}, {}]),
        (
            "workspace/applyEdit",
            {"edit": {}},
            {
                "applied": False,
                "failureReason": (
                    "EvoFlux applies semantic edits only through reviewed ChangeSets."
                ),
            },
        ),
        ("client/registerCapability", {"registrations": []}, None),
    ],
)
async def test_server_requests_receive_safe_responses(
    tmp_path: Path, method: str, params: dict, expected: object
):
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client._send = AsyncMock()

    await client._handle_server_request(
        {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}
    )

    client._send.assert_awaited_once_with(
        {"jsonrpc": "2.0", "id": 7, "result": expected}
    )


@pytest.mark.asyncio
async def test_sync_document_rejects_file_outside_repository(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    client = LanguageServerClient(
        workspace, SPECS[0], ("pyright-langserver", "--stdio")
    )
    client.start = AsyncMock()

    with pytest.raises(LanguageServerUnavailable, match="outside"):
        await client.sync_document(outside)


@pytest.mark.asyncio
async def test_current_version_diagnostics_wait_for_matching_publish(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("value = 2\n", encoding="utf-8")
    uri = source.as_uri()
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client.sync_document = AsyncMock(return_value=(uri, True))
    client._versions[uri] = (2, "hash")
    event = client._diagnostic_events.setdefault(uri, asyncio.Event())

    async def publish_current_version():
        await asyncio.sleep(0)
        client._diagnostics[uri] = [{"message": "current"}]
        client._diagnostic_versions[uri] = 2
        event.set()

    task = asyncio.create_task(publish_current_version())
    result = await client.diagnostics(source, require_current_version=True)
    await task

    assert result == [{"message": "current"}]


@pytest.mark.asyncio
async def test_current_diagnostics_accept_versionless_post_change_publish(
    tmp_path: Path,
):
    source = tmp_path / "source.py"
    source.write_text("value = 2\n", encoding="utf-8")
    uri = source.as_uri()
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client.sync_document = AsyncMock(return_value=(uri, True))
    client._versions[uri] = (2, "hash")
    event = client._diagnostic_events.setdefault(uri, asyncio.Event())

    async def publish_without_version():
        await asyncio.sleep(0)
        client._diagnostics[uri] = [{"message": "current without version"}]
        client._diagnostic_versions[uri] = None
        client._diagnostic_generations[uri] = 1
        event.set()

    task = asyncio.create_task(publish_without_version())
    result = await client.diagnostics(source, require_current_version=True)
    await task

    assert result == [{"message": "current without version"}]


@pytest.mark.asyncio
async def test_failed_initialize_terminates_process_and_drops_stale_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    client = LanguageServerClient(tmp_path, SPECS[0], ("pyright-langserver", "--stdio"))
    client._versions["file:///stale.py"] = (9, "stale")
    terminate = MagicMock()
    process = SimpleNamespace(
        returncode=None,
        stdin=None,
        stdout=None,
        terminate=terminate,
        kill=MagicMock(),
        wait=AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "app.agent.lsp_manager.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    monkeypatch.setattr(
        "app.agent.lsp_manager.get_sandbox",
        lambda: SimpleNamespace(inherit_shell_environment=False),
    )
    client.request = AsyncMock(side_effect=RuntimeError("initialize failed"))

    with pytest.raises(RuntimeError, match="initialize failed"):
        await client.start()

    terminate.assert_called_once()
    assert client._process is None
    assert client._versions == {}
