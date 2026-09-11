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
from dataclasses import dataclass, replace
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

InstallerKind = Literal["npm", "uv", "go", "rustup", "gem", "dotnet"]
#: Where an install lands. ``managed`` is staged into the EvoFlux cache and
#: resolved without consulting PATH. ``toolchain`` asks a toolchain the user
#: already has to add the server to itself — rustup components and gems have
#: no meaningful "copy it into our directory" form — and success is confirmed
#: by the server then resolving on PATH.
InstallScope = Literal["managed", "toolchain"]
#: Lifecycle of a running or finished install, as the UI reports it.
InstallPhase = Literal["idle", "running", "failed"]
ServerState = Literal["ready", "missing", "update_available"]
ServerSource = Literal["managed", "system", "missing"]


@dataclass(frozen=True, slots=True)
class InstallRecipe:
    kind: InstallerKind
    #: Pinned version, or ``None`` when the toolchain decides it (a rustup
    #: component ships with the toolchain and has no version of its own).
    version: str | None
    packages: tuple[str, ...]
    prerequisite: str
    registry: str
    scope: InstallScope = "managed"


@dataclass(frozen=True, slots=True)
class InstallJob:
    """What one install is doing, so the UI can say more than "spinner"."""

    language_id: str
    phase: InstallPhase
    started_at: str
    finished_at: str | None
    error: str | None


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
    #: Why the action is unavailable, or ``None`` when it can be taken. The UI
    #: shows a disabled button carrying this rather than hiding the control,
    #: because a hidden button and an impossible one look identical.
    blocked_reason: str | None
    install_phase: InstallPhase
    install_started_at: str | None
    install_error: str | None


@dataclass(frozen=True, slots=True)
class LanguageServerOverview:
    workspaces: tuple[str, ...]
    cache_dir: str
    servers: tuple[LanguageServerStatus, ...]
    #: True when detection stopped at the file cap, so the language list is a
    #: sample rather than the whole repository set.
    scan_truncated: bool
    scan_limit: int


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
    # The four below install through a toolchain the user already has. They
    # were "install it yourself" prose while `go`, `rustup`, `gem` and
    # `dotnet` sat on PATH ready to do it in one command.
    "go": InstallRecipe(
        kind="go",
        version="0.20.0",
        packages=("golang.org/x/tools/gopls@v0.20.0",),
        prerequisite="go",
        registry="https://proxy.golang.org",
    ),
    "rust": InstallRecipe(
        # A rustup component belongs to the toolchain and carries its
        # version, so there is nothing for EvoFlux to pin.
        kind="rustup",
        version=None,
        packages=("rust-analyzer",),
        prerequisite="rustup",
        registry="https://static.rust-lang.org",
        scope="toolchain",
    ),
    "ruby": InstallRecipe(
        kind="gem",
        version="0.28.0",
        packages=("ruby-lsp",),
        prerequisite="gem",
        registry="https://rubygems.org",
        scope="toolchain",
    ),
}


MANUAL_HINTS: dict[str, str] = {
    # csharp-ls is the obvious managed candidate and was tried: its NuGet
    # package ships without DotnetToolSettings.xml, so `dotnet tool install`
    # refuses it at every version. The spec still looks for csharp-ls on PATH,
    # so a hand-installed one is picked up.
    "csharp": (
        "Install OmniSharp or csharp-ls and expose it on PATH."
    ),
    "c": "Install clangd with the LLVM toolchain.",
    "cpp": "Install clangd with the LLVM toolchain.",
    "java": "Install Eclipse JDT Language Server (jdtls).",
    "kotlin": "Install kotlin-language-server and expose it on PATH.",
    "swift": "Install an Apple or Swift toolchain containing sourcekit-lsp.",
    "dart": "Install the Dart SDK; the server is provided by the dart executable.",
    "lua": "Install lua-language-server and expose it on PATH.",
    "markdown": "Install Marksman and expose marksman on PATH.",
}

_install_locks: dict[str, asyncio.Lock] = {}
#: Live install state, keyed by language. An install outlives the request that
#: started it, so the page can be left and come back to a running install
#: instead of a spinner that vanished with the mutation.
_install_jobs: dict[str, InstallJob] = {}
_install_tasks: dict[str, asyncio.Task[None]] = {}
_MAX_SCANNED_FILES = 50_000

#: What to tell someone whose machine lacks the installer a recipe needs.
PREREQUISITE_HINTS: dict[InstallerKind, str] = {
    "npm": "Install Node.js to get npm, then refresh.",
    "uv": "Install uv (astral.sh/uv), then refresh.",
    "go": "Install the Go toolchain, then refresh.",
    "rustup": "Install Rust with rustup, then refresh.",
    "gem": "Install Ruby to get gem, then refresh.",
    "dotnet": "Install the .NET SDK, then refresh.",
}


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
) -> tuple[dict[str, tuple[DetectedRepository, ...]], bool]:
    """Count matching files per language. Also reports whether the file cap
    cut the walk short, because a truncated scan under-reports languages and
    the page should say so rather than quietly listing fewer of them."""
    extension_map: dict[str, str] = {}
    for spec in SPECS:
        for extension in spec.extensions:
            extension_map.setdefault(extension, spec.language_id)

    by_language: dict[str, list[DetectedRepository]] = {}
    truncated = False
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
                truncated = True
                break
        for language_id, file_count in counts.items():
            by_language.setdefault(language_id, []).append(
                DetectedRepository(
                    workspace=str(workspace),
                    name=workspace.name,
                    file_count=file_count,
                )
            )
    return {key: tuple(value) for key, value in by_language.items()}, truncated


def language_server_overview(
    workspaces: tuple[Path, ...] = (),
) -> LanguageServerOverview:
    """Return detected and installed state across authorized repositories."""
    roots = tuple(dict.fromkeys(workspace.resolve() for workspace in workspaces))
    detected, truncated = _detect_languages(roots)
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
                if (
                    recipe is not None
                    and recipe.version is not None
                    and installed_version != recipe.version
                )
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
        job = _install_jobs.get(spec.language_id)
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
                blocked_reason=_blocked_reason(
                    recipe, prerequisite_available, state, source
                ),
                install_phase=job.phase if job else "idle",
                install_started_at=job.started_at if job else None,
                install_error=job.error if job else None,
            )
        )
    statuses.sort(key=lambda item: (not item.detected, item.display_name.casefold()))
    return LanguageServerOverview(
        workspaces=tuple(str(root) for root in roots),
        cache_dir=str(Path(settings.EVOFLUX_CACHE_DIR) / "language-servers"),
        servers=tuple(statuses),
        scan_truncated=truncated,
        scan_limit=_MAX_SCANNED_FILES,
    )


def _blocked_reason(
    recipe: InstallRecipe | None,
    prerequisite_available: bool,
    state: ServerState,
    source: ServerSource,
) -> str | None:
    """Why the install button is disabled, or None when it is not.

    A row with no recipe and a row whose installer is missing used to render
    identically — as no button at all — so "nothing happens when I click
    install" was really "there was never anything to click, and no one said
    why".
    """
    if recipe is None:
        return "No managed installer for this server yet — install it yourself."
    if not prerequisite_available:
        return PREREQUISITE_HINTS.get(
            recipe.kind, f"Install {recipe.prerequisite} first."
        )
    if state == "ready" and source == "managed":
        return "Already installed and up to date."
    if state == "ready" and source == "system":
        return "Already available from your system PATH."
    return None


#: Seconds an installer may run. npm and uv unpack prebuilt artifacts; `go
#: install` compiles gopls from source and `dotnet tool install` restores and
#: builds, which measured 98s here on a warm network and would exceed the
#: shared 180s budget on a slower machine or a cold module cache.
_INSTALL_TIMEOUTS: dict[InstallerKind, float] = {
    "npm": 180,
    "uv": 180,
    "gem": 300,
    "rustup": 300,
    "dotnet": 600,
    "go": 600,
}


async def _run_installer_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 180,
) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise LanguageServerInstallError(
            f"Installation timed out after {timeout:.0f} seconds."
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
    elif recipe.kind == "uv":
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
    elif recipe.kind == "go":
        # GOBIN puts the built binary exactly where the managed resolver
        # looks. Every cache is redirected into the stage so a failed install
        # leaves nothing behind and the user's own Go caches are untouched.
        env.update(
            {
                "GOBIN": str(stage / "bin"),
                "GOPATH": str(stage / "gopath"),
                "GOMODCACHE": str(stage / "gopath" / "pkg" / "mod"),
                "GOCACHE": str(stage / "gocache"),
                "GOPROXY": recipe.registry,
                "GOFLAGS": "-mod=mod",
                "GOTOOLCHAIN": "local",
                "CGO_ENABLED": "0",
            }
        )
        command = (executable, "install", recipe.packages[0])
    elif recipe.kind == "dotnet":
        env.update(
            {
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
                "DOTNET_CLI_HOME": str(stage / "dotnet-home"),
                "NUGET_PACKAGES": str(stage / "nuget"),
            }
        )
        command = (
            executable,
            "tool",
            "install",
            recipe.packages[0],
            "--tool-path",
            str(stage / "bin"),
            *(("--version", recipe.version) if recipe.version else ()),
            "--add-source",
            recipe.registry,
        )
    else:
        raise LanguageServerInstallError(
            f"Installer '{recipe.kind}' does not install into the managed cache."
        )
    await _run_installer_command(
        command, cwd=stage, env=env, timeout=_INSTALL_TIMEOUTS[recipe.kind]
    )


async def _install_into_toolchain(recipe: InstallRecipe, cwd: Path) -> None:
    """Ask a toolchain to add the server to itself.

    A rustup component and a gem belong to the toolchain that owns them;
    there is no copy of them EvoFlux could keep in its own cache and still
    have work. The install succeeds when the server afterwards resolves on
    PATH, which the caller checks.
    """
    executable = shutil.which(recipe.prerequisite)
    if executable is None:
        raise LanguageServerInstallError(
            f"Required installer '{recipe.prerequisite}' is not available."
        )
    env = _scrubbed_env(inherit=False)
    if recipe.kind == "rustup":
        command = (executable, "component", "add", recipe.packages[0])
    elif recipe.kind == "gem":
        command = (
            executable,
            "install",
            recipe.packages[0],
            *(("--version", recipe.version) if recipe.version else ()),
            "--no-document",
            "--source",
            recipe.registry,
        )
    else:
        raise LanguageServerInstallError(
            f"Installer '{recipe.kind}' has no toolchain form."
        )
    await _run_installer_command(
        command, cwd=cwd, env=env, timeout=_INSTALL_TIMEOUTS[recipe.kind]
    )


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
    """Install or update one allowlisted server."""
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

        if recipe.scope == "toolchain":
            with tempfile.TemporaryDirectory(prefix=f".{language_id}-install-") as cwd:
                await _install_into_toolchain(recipe, Path(cwd))
            if _system_command(spec) is None:
                raise LanguageServerInstallError(
                    f"{recipe.prerequisite} reported success, but "
                    f"{spec.commands[0][0]} is still not on PATH. Open a new "
                    "terminal session or check the toolchain's bin directory."
                )
            await close_language_servers(language_id)
            logger.info(
                "language_server_installed language={} installer={} scope=toolchain",
                language_id,
                recipe.kind,
            )
            return next(
                item
                for item in language_server_overview().servers
                if item.language_id == language_id
            )

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



def _now() -> str:
    return datetime.now(UTC).isoformat()


def install_job(language_id: str) -> InstallJob | None:
    """The install state for one language, if anything ever ran for it."""
    return _install_jobs.get(language_id)


def start_language_server_install(language_id: str) -> InstallJob:
    """Begin an install and return immediately with its state.

    The install itself can take minutes. Holding the HTTP request open for it
    meant the only status anyone had was a spinner that belonged to that one
    request: navigate away and the install continued with nothing to show for
    it. The work now outlives the request and the overview reports it.
    """
    spec = _spec(language_id)
    if spec is None:
        raise LanguageServerInstallError(f"Unknown language server: {language_id}")
    recipe = INSTALL_RECIPES.get(language_id)
    if recipe is None:
        raise LanguageServerInstallError(
            MANUAL_HINTS.get(language_id, "This server requires a system toolchain.")
        )
    if shutil.which(recipe.prerequisite) is None:
        raise LanguageServerInstallError(
            PREREQUISITE_HINTS.get(
                recipe.kind, f"Install {recipe.prerequisite} first."
            )
        )

    existing = _install_tasks.get(language_id)
    if existing is not None and not existing.done():
        return _install_jobs[language_id]

    job = InstallJob(
        language_id=language_id,
        phase="running",
        started_at=_now(),
        finished_at=None,
        error=None,
    )
    _install_jobs[language_id] = job

    async def _run() -> None:
        try:
            await install_language_server(language_id)
        except LanguageServerInstallError as exc:
            _install_jobs[language_id] = replace(
                job, phase="failed", finished_at=_now(), error=str(exc)
            )
            logger.warning(
                "language_server_install_failed language={} error={}",
                language_id,
                exc,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            _install_jobs[language_id] = replace(
                job, phase="failed", finished_at=_now(), error=str(exc)
            )
            logger.exception("language_server_install_crashed language={}", language_id)
        else:
            # Success is visible in the row's own state; a finished job with
            # nothing to say would only keep a stale banner on screen.
            _install_jobs.pop(language_id, None)

    _install_tasks[language_id] = asyncio.create_task(
        _run(), name=f"lsp-install-{language_id}"
    )
    return job


def dismiss_install_error(language_id: str) -> None:
    """Clear a failed job so its message stops being reported."""
    job = _install_jobs.get(language_id)
    if job is not None and job.phase == "failed":
        _install_jobs.pop(language_id, None)


__all__ = [
    "DISPLAY_NAMES",
    "INSTALL_RECIPES",
    "PREREQUISITE_HINTS",
    "DetectedRepository",
    "InstallJob",
    "LanguageServerInstallError",
    "LanguageServerOverview",
    "LanguageServerStatus",
    "dismiss_install_error",
    "install_job",
    "install_language_server",
    "language_server_overview",
    "start_language_server_install",
]
