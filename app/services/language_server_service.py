"""Managed language-server catalog, detection, and pinned installation.

Installations are explicit user actions and live under the regeneratable
EvoFlux cache. Repository contents are only scanned for known extensions;
they never choose packages, versions, commands, or download locations.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from loguru import logger

from app.agent.lsp_manager import (
    SPECS,
    LanguageServerSpec,
    close_language_servers,
    managed_language_server_command,
    managed_language_server_root,
    system_language_server_command,
)
from app.agent.tools.builtin.filesystem._ignore import (
    is_ignored_workspace_path,
    load_gitignore_rules,
)
from app.agent.tools.builtin.shell import _scrubbed_env
from app.core.config import settings

InstallerKind = Literal["npm", "uv"]
ServerState = Literal["ready", "missing", "update_available"]
ServerSource = Literal["managed", "system", "missing"]


@dataclass(frozen=True, slots=True)
class InstallRecipe:
    kind: InstallerKind
    version: str
    packages: tuple[str, ...]
    prerequisite: str
    registry: str


@dataclass(frozen=True, slots=True)
class DetectedRepository:
    workspace: str
    name: str
    file_count: int


@dataclass(frozen=True, slots=True)
class LanguageServerStatus:
    language_id: str
    display_name: str
    extensions: tuple[str, ...]
    detected: bool
    file_count: int
    repositories: tuple[DetectedRepository, ...]
    state: ServerState
    source: ServerSource
    command: str | None
    installed_version: str | None
    expected_version: str | None
    installable: bool
    installer: InstallerKind | None
    installer_available: bool
    install_hint: str


@dataclass(frozen=True, slots=True)
class LanguageServerOverview:
    workspaces: tuple[str, ...]
    cache_dir: str
    servers: tuple[LanguageServerStatus, ...]


class LanguageServerInstallError(RuntimeError):
    """A catalog or installer failure safe to expose through the API."""


DISPLAY_NAMES: dict[str, str] = {
    "python": "Python",
    "typescript": "TypeScript & JavaScript",
    "c": "C / Objective-C",
    "cpp": "C++ / Objective-C++",
    "java": "Java",
    "kotlin": "Kotlin",
    "csharp": "C#",
    "php": "PHP",
    "swift": "Swift",
    "dart": "Dart",
    "ruby": "Ruby",
    "lua": "Lua",
    "html": "HTML",
    "css": "CSS",
    "json": "JSON",
    "yaml": "YAML",
    "bash": "Shell",
    "markdown": "Markdown",
    "toml": "TOML",
    "vue": "Vue",
    "svelte": "Svelte",
    "go": "Go",
    "rust": "Rust",
}


# Versions are deliberately pinned. Updating this catalog is an application
# release decision, not a mutable npm/PyPI "latest" lookup at install time.
INSTALL_RECIPES: dict[str, InstallRecipe] = {
    "python": InstallRecipe(
        kind="uv",
        version="1.39.10",
        packages=("basedpyright==1.39.10",),
        prerequisite="uv",
        registry="https://pypi.org/simple",
    ),
    "typescript": InstallRecipe(
        kind="npm",
        version="5.3.0",
        packages=(
            "typescript-language-server@5.3.0",
            "typescript@5.9.3",
        ),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "php": InstallRecipe(
        kind="npm",
        version="1.18.5",
        packages=("intelephense@1.18.5",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "html": InstallRecipe(
        kind="npm",
        version="4.10.0",
        packages=("vscode-langservers-extracted@4.10.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "css": InstallRecipe(
        kind="npm",
        version="4.10.0",
        packages=("vscode-langservers-extracted@4.10.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "json": InstallRecipe(
        kind="npm",
        version="4.10.0",
        packages=("vscode-langservers-extracted@4.10.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "yaml": InstallRecipe(
        kind="npm",
        version="1.24.0",
        packages=("yaml-language-server@1.24.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "bash": InstallRecipe(
        kind="npm",
        version="5.6.0",
        packages=("bash-language-server@5.6.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "toml": InstallRecipe(
        kind="npm",
        version="0.7.0",
        packages=("@taplo/cli@0.7.0",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "vue": InstallRecipe(
        kind="npm",
        version="3.3.10",
        packages=("@vue/language-server@3.3.10", "typescript@5.9.3"),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
    "svelte": InstallRecipe(
        kind="npm",
        version="0.18.4",
        packages=("svelte-language-server@0.18.4",),
        prerequisite="npm",
        registry="https://registry.npmjs.org/",
    ),
}


MANUAL_HINTS: dict[str, str] = {
    "c": "Install clangd with the LLVM toolchain.",
    "cpp": "Install clangd with the LLVM toolchain.",
    "java": "Install Eclipse JDT Language Server (jdtls).",
    "kotlin": "Install kotlin-language-server and expose it on PATH.",
    "csharp": "Install OmniSharp and expose OmniSharp or omnisharp on PATH.",
    "swift": "Install an Apple or Swift toolchain containing sourcekit-lsp.",
    "dart": "Install the Dart SDK; the server is provided by the dart executable.",
    "ruby": "Install ruby-lsp or solargraph with the active Ruby toolchain.",
    "lua": "Install lua-language-server and expose it on PATH.",
    "markdown": "Install Marksman and expose marksman on PATH.",
    "go": "Install gopls with the active Go toolchain.",
    "rust": "Install rust-analyzer with rustup or your Rust toolchain.",
}

_install_locks: dict[str, asyncio.Lock] = {}
_MAX_SCANNED_FILES = 50_000


def _spec(language_id: str) -> LanguageServerSpec | None:
    return next((item for item in SPECS if item.language_id == language_id), None)


def _manifest_path(language_id: str) -> Path:
    return managed_language_server_root(language_id) / "manifest.json"


def _read_manifest(language_id: str) -> dict[str, object]:
    try:
        payload = json.loads(_manifest_path(language_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _system_command(spec: LanguageServerSpec) -> tuple[str, ...] | None:
    return system_language_server_command(spec)


def _detect_languages(
    workspaces: tuple[Path, ...],
) -> dict[str, tuple[DetectedRepository, ...]]:
    extension_map: dict[str, str] = {}
    for spec in SPECS:
        for extension in spec.extensions:
            extension_map.setdefault(extension, spec.language_id)

    by_language: dict[str, list[DetectedRepository]] = {}
    for workspace in workspaces:
        counts: dict[str, int] = {}
        rules = load_gitignore_rules(workspace)
        scanned = 0
        for base, directories, filenames in os.walk(workspace):
            base_path = Path(base)
            directories[:] = sorted(
                directory
                for directory in directories
                if directory != ".git"
                and not (base_path / directory).is_symlink()
                and not is_ignored_workspace_path(
                    (base_path / directory).relative_to(workspace).as_posix(),
                    is_dir=True,
                    rules=rules,
                )
            )
            for filename in filenames:
                scanned += 1
                if scanned > _MAX_SCANNED_FILES:
                    break
                path = base_path / filename
                if path.is_symlink():
                    continue
                relative = path.relative_to(workspace).as_posix()
                if is_ignored_workspace_path(relative, is_dir=False, rules=rules):
                    continue
                language_id = extension_map.get(path.suffix.casefold())
                if language_id:
                    counts[language_id] = counts.get(language_id, 0) + 1
            if scanned > _MAX_SCANNED_FILES:
                break
        for language_id, file_count in counts.items():
            by_language.setdefault(language_id, []).append(
                DetectedRepository(
                    workspace=str(workspace),
                    name=workspace.name,
                    file_count=file_count,
                )
            )
    return {key: tuple(value) for key, value in by_language.items()}


def language_server_overview(
    workspaces: tuple[Path, ...] = (),
) -> LanguageServerOverview:
    """Return detected and installed state across authorized repositories."""
    roots = tuple(dict.fromkeys(workspace.resolve() for workspace in workspaces))
    detected = _detect_languages(roots)
    statuses: list[LanguageServerStatus] = []
    for spec in SPECS:
        repositories = detected.get(spec.language_id, ())
        recipe = INSTALL_RECIPES.get(spec.language_id)
        managed = managed_language_server_command(spec)
        system = _system_command(spec) if managed is None else None
        manifest = _read_manifest(spec.language_id) if managed is not None else {}
        installed_version = (
            str(manifest.get("version"))
            if manifest.get("version") is not None
            else None
        )
        if managed is not None:
            source: ServerSource = "managed"
            state: ServerState = (
                "update_available"
                if recipe is not None and installed_version != recipe.version
                else "ready"
            )
            command = managed[0]
        elif system is not None:
            source = "system"
            state = "ready"
            command = system[0]
        else:
            source = "missing"
            state = "missing"
            command = None

        prerequisite_available = bool(
            recipe is not None and shutil.which(recipe.prerequisite)
        )
        if source == "managed" and state == "ready":
            install_hint = "Managed by EvoFlux and shared across repositories."
        elif source == "managed" and recipe is not None:
            install_hint = f"Downloads the pinned update from {recipe.registry}."
        elif source == "system":
            install_hint = "Using a compatible executable from the system PATH."
        elif recipe is not None:
            install_hint = (
                f"Downloads pinned packages from {recipe.registry}."
                if prerequisite_available
                else f"Install {recipe.prerequisite} to enable managed installation."
            )
        else:
            install_hint = MANUAL_HINTS.get(
                spec.language_id,
                "Install a compatible language server and expose it on PATH.",
            )
        statuses.append(
            LanguageServerStatus(
                language_id=spec.language_id,
                display_name=DISPLAY_NAMES.get(spec.language_id, spec.language_id),
                extensions=tuple(sorted(spec.extensions)),
                detected=bool(repositories),
                file_count=sum(item.file_count for item in repositories),
                repositories=repositories,
                state=state,
                source=source,
                command=command,
                installed_version=installed_version,
                expected_version=recipe.version if recipe else None,
                installable=recipe is not None,
                installer=recipe.kind if recipe else None,
                installer_available=prerequisite_available,
                install_hint=install_hint,
            )
        )
    statuses.sort(key=lambda item: (not item.detected, item.display_name.casefold()))
    return LanguageServerOverview(
        workspaces=tuple(str(root) for root in roots),
        cache_dir=str(Path(settings.EVOFLUX_CACHE_DIR) / "language-servers"),
        servers=tuple(statuses),
    )


async def _run_installer_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise LanguageServerInstallError(
            "Installation timed out after 180 seconds."
        ) from exc
    if process.returncode == 0:
        return
    detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
    detail = " ".join(detail.split())[-1000:]
    raise LanguageServerInstallError(
        f"Installer exited with code {process.returncode}: {detail or 'no output'}"
    )


async def _install_into_stage(recipe: InstallRecipe, stage: Path) -> None:
    executable = shutil.which(recipe.prerequisite)
    if executable is None:
        raise LanguageServerInstallError(
            f"Required installer '{recipe.prerequisite}' is not available."
        )
    # Package managers receive only process-discovery and locale variables;
    # provider keys, OAuth tokens, SSH sockets, and EvoFlux internals stay out.
    env = _scrubbed_env(inherit=False)
    if recipe.kind == "npm":
        user_config = stage / "empty.npmrc"
        user_config.write_text("", encoding="utf-8")
        env.update(
            {
                "NPM_CONFIG_CACHE": str(stage / ".npm-cache"),
                "NPM_CONFIG_UPDATE_NOTIFIER": "false",
            }
        )
        command = (
            executable,
            "install",
            "--prefix",
            str(stage),
            "--no-save",
            "--no-audit",
            "--no-fund",
            "--ignore-scripts",
            "--loglevel=error",
            "--registry",
            recipe.registry,
            "--userconfig",
            str(user_config),
            *recipe.packages,
        )
    else:
        env.update(
            {
                "UV_TOOL_DIR": str(stage / "tools"),
                "UV_TOOL_BIN_DIR": str(stage / "bin"),
            }
        )
        command = (
            executable,
            "tool",
            "install",
            "--force",
            "--no-config",
            "--no-managed-python",
            "--no-python-downloads",
            "--link-mode",
            "copy",
            "--python",
            sys.executable,
            "--default-index",
            recipe.registry,
            recipe.packages[0],
        )
    await _run_installer_command(command, cwd=stage, env=env)


def _activate_stage(stage: Path, target: Path) -> None:
    backup: Path | None = None
    if target.exists():
        backup = target.with_name(f".{target.name}.previous-{os.getpid()}")
        if backup.exists():
            shutil.rmtree(backup)
        target.rename(backup)
    try:
        stage.rename(target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)


async def install_language_server(language_id: str) -> LanguageServerStatus:
    """Install or update one allowlisted server into the managed cache."""
    spec = _spec(language_id)
    if spec is None:
        raise LanguageServerInstallError(f"Unknown language server: {language_id}")
    recipe = INSTALL_RECIPES.get(language_id)
    if recipe is None:
        raise LanguageServerInstallError(
            MANUAL_HINTS.get(language_id, "This server requires a system toolchain.")
        )

    lock = _install_locks.setdefault(language_id, asyncio.Lock())
    async with lock:
        current = next(
            item
            for item in language_server_overview().servers
            if item.language_id == language_id
        )
        if current.source == "managed" and current.state == "ready":
            return current

        target = managed_language_server_root(language_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(
            tempfile.mkdtemp(prefix=f".{language_id}-install-", dir=target.parent)
        )
        try:
            await _install_into_stage(recipe, stage)
            if managed_language_server_command(spec, root=stage) is None:
                raise LanguageServerInstallError(
                    "The package installed, but its language-server executable was missing."
                )
            (stage / "manifest.json").write_text(
                json.dumps(
                    {
                        "language_id": language_id,
                        "version": recipe.version,
                        "installer": recipe.kind,
                        "packages": list(recipe.packages),
                        "registry": recipe.registry,
                        "installed_at": datetime.now(UTC).isoformat(),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            _activate_stage(stage, target)
            await close_language_servers(language_id)
            logger.info(
                "language_server_installed language={} version={} installer={}",
                language_id,
                recipe.version,
                recipe.kind,
            )
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)

    return next(
        item
        for item in language_server_overview().servers
        if item.language_id == language_id
    )


__all__ = [
    "DISPLAY_NAMES",
    "INSTALL_RECIPES",
    "DetectedRepository",
    "LanguageServerInstallError",
    "LanguageServerOverview",
    "LanguageServerStatus",
    "install_language_server",
    "language_server_overview",
]
