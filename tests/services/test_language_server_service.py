from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services import language_server_service as service


def test_overview_detects_languages_across_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    web = tmp_path / "web"
    api = tmp_path / "api"
    web.mkdir()
    api.mkdir()
    (web / "app.ts").write_text("export const value = 1\n", encoding="utf-8")
    (web / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    ignored = web / "node_modules"
    ignored.mkdir()
    (ignored / "ignored.ts").write_text("bad\n", encoding="utf-8")
    (api / "main.py").write_text("value: int = 1\n", encoding="utf-8")

    monkeypatch.setattr(service.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)

    overview = service.language_server_overview((web, api))
    by_language = {item.language_id: item for item in overview.servers}

    assert overview.workspaces == (str(web), str(api))
    assert by_language["typescript"].detected is True
    assert by_language["typescript"].file_count == 1
    assert by_language["typescript"].repositories[0].workspace == str(web)
    assert by_language["typescript"].state == "missing"
    assert by_language["typescript"].installable is True
    assert by_language["python"].file_count == 1


@pytest.mark.asyncio
async def test_install_activates_pinned_managed_server_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cache = tmp_path / "cache"
    monkeypatch.setattr(service.settings, "EVOFLUX_CACHE_DIR", str(cache))
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )
    close = AsyncMock()
    monkeypatch.setattr(service, "close_language_servers", close)
    installs = 0

    async def fake_install(recipe: service.InstallRecipe, stage: Path) -> None:
        nonlocal installs
        installs += 1
        assert recipe.packages == (
            "typescript-language-server@5.3.0",
            "typescript@5.9.3",
        )
        executable = stage / "node_modules" / ".bin" / "typescript-language-server"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(service, "_install_into_stage", fake_install)

    installed = await service.install_language_server("typescript")
    installed_again = await service.install_language_server("typescript")

    target = cache / "language-servers" / "typescript"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert installed.source == "managed"
    assert installed.state == "ready"
    assert installed.installed_version == "5.3.0"
    assert installed_again.source == "managed"
    assert manifest["packages"] == [
        "typescript-language-server@5.3.0",
        "typescript@5.9.3",
    ]
    assert installs == 1
    close.assert_awaited_once_with("typescript")


@pytest.mark.asyncio
async def test_install_requires_allowlisted_recipe():
    with pytest.raises(service.LanguageServerInstallError, match="LLVM"):
        await service.install_language_server("cpp")


@pytest.mark.asyncio
async def test_npm_installer_uses_fixed_registry_and_disables_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )
    monkeypatch.setattr(
        service, "_scrubbed_env", lambda *, inherit: {"PATH": "/usr/bin"}
    )
    run = AsyncMock()
    monkeypatch.setattr(service, "_run_installer_command", run)

    recipe = service.INSTALL_RECIPES["typescript"]
    await service._install_into_stage(recipe, tmp_path)

    command = run.await_args.args[0]
    assert "--ignore-scripts" in command
    assert "--registry" in command
    assert recipe.registry in command
    assert command[-2:] == recipe.packages
    assert run.await_args.kwargs["env"] == {
        "PATH": "/usr/bin",
        "NPM_CONFIG_CACHE": str(tmp_path / ".npm-cache"),
        "NPM_CONFIG_UPDATE_NOTIFIER": "false",
    }
