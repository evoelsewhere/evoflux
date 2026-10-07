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


# ---------------------------------------------------------------------------
# Activating a staged install on Windows
# ---------------------------------------------------------------------------


def _make_stage(parent: Path, name: str = ".bash-install-rd96ikj2") -> Path:
    stage = parent / name
    (stage / "bin").mkdir(parents=True)
    (stage / "bin" / "server").write_text("ok", encoding="utf-8")
    return stage


class _LockedRename:
    """Make the first *failures* renames of a path raise like Windows does."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, failures: int) -> None:
        self.remaining = failures
        self.attempts = 0
        real_rename = Path.rename

        def rename(path: Path, target):  # type: ignore[no-untyped-def]
            self.attempts += 1
            if self.remaining > 0:
                self.remaining -= 1
                raise PermissionError(
                    5, "Access is denied", str(path), None, str(target)
                )
            return real_rename(path, target)

        monkeypatch.setattr(Path, "rename", rename)
        monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)


def test_activate_stage_rides_out_a_transient_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``PermissionError: [WinError 5] '.bash-install-…' -> 'bash'`` was a moment's
    lock from the scanner or the old server, not a failed install."""
    stage = _make_stage(tmp_path)
    target = tmp_path / "bash"
    lock = _LockedRename(monkeypatch, failures=3)

    service._activate_stage(stage, target)

    assert lock.attempts == 4
    assert (target / "bin" / "server").read_text(encoding="utf-8") == "ok"
    assert not stage.exists()


def test_activate_stage_replaces_an_existing_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "bash"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "server").write_text("old", encoding="utf-8")
    stage = _make_stage(tmp_path)
    _LockedRename(monkeypatch, failures=2)

    service._activate_stage(stage, target)

    assert (target / "bin" / "server").read_text(encoding="utf-8") == "ok"
    assert not list(tmp_path.glob(".bash.previous-*"))


def test_activate_stage_gives_up_with_a_readable_error_and_keeps_the_old_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "bash"
    (target / "bin").mkdir(parents=True)
    (target / "bin" / "server").write_text("old", encoding="utf-8")
    stage = _make_stage(tmp_path)
    real_rename = Path.rename

    def rename(path: Path, destination):  # type: ignore[no-untyped-def]
        # Moving the old install aside works; moving the new one in never does.
        if path == stage:
            raise PermissionError(
                5, "Access is denied", str(path), None, str(destination)
            )
        return real_rename(path, destination)

    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(service.time, "sleep", lambda _seconds: None)

    with pytest.raises(service.LanguageServerInstallError, match="still has files"):
        service._activate_stage(stage, target)

    assert (target / "bin" / "server").read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".bash.previous-*"))


def test_remove_stale_install_dirs_only_touches_this_servers_leftovers(
    tmp_path: Path,
):
    stale_stage = _make_stage(tmp_path, ".bash-install-aaaa1111")
    stale_backup = _make_stage(tmp_path, ".bash.previous-1234")
    other_stage = _make_stage(tmp_path, ".python-install-bbbb2222")
    live = tmp_path / "bash"
    live.mkdir()

    service._remove_stale_install_dirs(tmp_path, "bash")

    assert not stale_stage.exists()
    assert not stale_backup.exists()
    assert other_stage.exists()
    assert live.exists()


@pytest.mark.asyncio
async def test_install_stops_the_running_server_before_swapping_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The old server's open files are what blocks the rename on Windows."""
    monkeypatch.setattr(service.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )
    order: list[str] = []

    async def close(_language_id: str) -> None:
        order.append("close")

    real_activate = service._activate_stage

    def activate(stage: Path, target: Path) -> None:
        order.append("activate")
        real_activate(stage, target)

    async def fake_install(recipe: service.InstallRecipe, stage: Path) -> None:
        executable = stage / "node_modules" / ".bin" / "typescript-language-server"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(service, "close_language_servers", close)
    monkeypatch.setattr(service, "_activate_stage", activate)
    monkeypatch.setattr(service, "_install_into_stage", fake_install)

    await service.install_language_server("typescript")

    assert order == ["close", "activate"]


@pytest.mark.asyncio
async def test_install_clears_staging_left_by_a_crashed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cache = tmp_path / "cache"
    monkeypatch.setattr(service.settings, "EVOFLUX_CACHE_DIR", str(cache))
    monkeypatch.setattr(
        service.shutil,
        "which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )
    monkeypatch.setattr(service, "close_language_servers", AsyncMock())
    leftover = _make_stage(cache / "language-servers", ".typescript-install-dead0000")

    async def fake_install(recipe: service.InstallRecipe, stage: Path) -> None:
        executable = stage / "node_modules" / ".bin" / "typescript-language-server"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(service, "_install_into_stage", fake_install)

    await service.install_language_server("typescript")

    assert not leftover.exists()
