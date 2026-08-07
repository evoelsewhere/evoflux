"""preview tool — dev-server lifecycle for in-browser verification.

Companion to ``browser_use``: start the project's dev server from a
declarative config, wait until its port accepts connections, then verify
the app through the browser (navigate → console/snapshot → screenshot).

Configuration lives in ``.evoflux/launch.json`` at the workspace root
(``.claude/launch.json`` is read as a fallback so existing projects work
unchanged). The example is valid JSON; ``cwd``, ``env``, ``reuseExisting``,
and ``startupTimeoutSeconds`` are optional::

    {
      "version": "0.0.2",
      "configurations": [
        {
          "name": "web",
          "runtimeExecutable": "npm",
          "runtimeArgs": ["run", "dev"],
          "port": 5180,
          "cwd": "web",
          "env": {"FOO": "1"},
          "reuseExisting": true,
          "startupTimeoutSeconds": 60
        }
      ]
    }

Servers are tracked per (workspace, name). If the configured port is
already accepting connections the tool reuses it instead of spawning a
second copy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.process_sandbox import sandboxed_process_argv
from app.agent.tools.builtin.process import TrackedProcess, command_process_scope
from app.agent.tools.registry import InjectedArg, Tool

_PORT_WAIT_SECONDS = 60.0
_PORT_POLL_INTERVAL = 0.5
_DEFAULT_LOG_LINES = 50
_CONFIG_FILES = (".evoflux/launch.json", ".claude/launch.json")
_MIN_STARTUP_TIMEOUT_SECONDS = 1.0
_MAX_STARTUP_TIMEOUT_SECONDS = 300.0


# ── Server registry ───────────────────────────────────────────────────────────


@dataclass
class PreviewServer:
    """One managed (or reused) dev server."""

    name: str
    port: int
    command: str
    workdir: str
    config_fingerprint: str
    started_at: float = field(default_factory=time.monotonic)
    # None when an externally-started server was reused.
    _process: TrackedProcess | None = field(default=None, repr=False)

    @property
    def reused(self) -> bool:
        return self._process is None

    @property
    def running(self) -> bool:
        return self.reused or bool(self._process and self._process.running)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None


# Keyed by (workspace_root, config name).
_servers: dict[tuple[str, str], PreviewServer] = {}


@dataclass(slots=True)
class _ServerLockEntry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


_server_locks: dict[tuple[str, str], _ServerLockEntry] = {}
_port_locks: dict[int, _ServerLockEntry] = {}


@asynccontextmanager
async def _locked_server(key: tuple[str, str]) -> AsyncIterator[None]:
    """Serialize one preview identity and retire unused lock entries safely."""
    entry = _server_locks.setdefault(key, _ServerLockEntry())
    entry.users += 1
    acquired = False
    try:
        await entry.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry.lock.release()
        entry.users -= 1
        if entry.users == 0 and key not in _servers:
            _server_locks.pop(key, None)


@asynccontextmanager
async def _locked_port(port: int) -> AsyncIterator[None]:
    """Serialize ownership checks and launches for one localhost port."""
    entry = _port_locks.setdefault(port, _ServerLockEntry())
    entry.users += 1
    acquired = False
    try:
        await entry.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            entry.lock.release()
        entry.users -= 1
        if entry.users == 0:
            _port_locks.pop(port, None)


@asynccontextmanager
async def _locked_ports(ports: set[int]) -> AsyncIterator[None]:
    """Acquire port locks in stable order so config changes cannot deadlock."""
    async with AsyncExitStack() as stack:
        for port in sorted(ports):
            await stack.enter_async_context(_locked_port(port))
        yield


@dataclass(frozen=True, slots=True)
class LaunchConfiguration:
    """Validated launch configuration used by the process manager."""

    name: str
    runtime_executable: str
    runtime_args: tuple[str, ...]
    port: int
    cwd: str | None = None
    env: tuple[tuple[str, str], ...] = ()
    reuse_existing: bool = True
    startup_timeout_seconds: float = _PORT_WAIT_SECONDS

    @property
    def command_argv(self) -> list[str]:
        return [self.runtime_executable, *self.runtime_args]

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "name": self.name,
                "runtimeExecutable": self.runtime_executable,
                "runtimeArgs": self.runtime_args,
                "port": self.port,
                "cwd": self.cwd,
                "env": self.env,
                "reuseExisting": self.reuse_existing,
                "startupTimeoutSeconds": self.startup_timeout_seconds,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _workspace_root() -> Path:
    from app.agent.tools.builtin.shell import _resolve_workdir

    return _resolve_workdir(None)


# ── Config loading ────────────────────────────────────────────────────────────


def _validate_configuration(raw: Any, source: str, index: int) -> LaunchConfiguration:
    if not isinstance(raw, dict):
        raise ValueError(f"Configuration #{index + 1} in {source} must be an object.")

    name = raw.get("name")
    executable = raw.get("runtimeExecutable")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Configuration #{index + 1} in {source} is missing 'name'.")
    normalized_name = name.strip()
    if len(normalized_name) > 100 or any(ord(char) < 32 for char in normalized_name):
        raise ValueError(
            f"Configuration name in {source} must be at most 100 printable characters."
        )
    if not isinstance(executable, str) or not executable.strip():
        raise ValueError(
            f"Configuration '{name}' in {source} is missing 'runtimeExecutable'."
        )

    raw_port = raw.get("port")
    if isinstance(raw_port, bool) or not isinstance(raw_port, int):
        raise ValueError(
            f"Configuration '{name}' in {source} must use an integer 'port'."
        )
    if not 1 <= raw_port <= 65_535:
        raise ValueError(
            f"Configuration '{name}' in {source} has an invalid port: {raw_port}."
        )

    raw_args = raw.get("runtimeArgs", [])
    if not isinstance(raw_args, list) or not all(
        isinstance(arg, str) for arg in raw_args
    ):
        raise ValueError(
            f"Configuration '{name}' in {source} must use a string array for 'runtimeArgs'."
        )
    if any("\0" in arg for arg in raw_args) or "\0" in executable:
        raise ValueError(
            f"Configuration '{name}' in {source} contains a NUL byte in its command."
        )

    raw_cwd = raw.get("cwd")
    if raw_cwd is not None:
        if not isinstance(raw_cwd, str) or not raw_cwd.strip() or "\0" in raw_cwd:
            raise ValueError(
                f"Configuration '{name}' in {source} must use a non-empty, NUL-free string for 'cwd'."
            )

    raw_env = raw.get("env", {})
    if not isinstance(raw_env, dict):
        raise ValueError(
            f"Configuration '{name}' in {source} must use an object for 'env'."
        )
    env: list[tuple[str, str]] = []
    for key, value in raw_env.items():
        if not isinstance(key, str) or not key or "=" in key or "\0" in key:
            raise ValueError(
                f"Configuration '{name}' in {source} contains an invalid environment key."
            )
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(
                f"Configuration '{name}' in {source} must use scalar values in 'env'."
            )
        rendered = str(value)
        if "\0" in rendered:
            raise ValueError(
                f"Configuration '{name}' in {source} contains a NUL byte in 'env'."
            )
        env.append((key, rendered))

    reuse_existing = raw.get("reuseExisting", True)
    if not isinstance(reuse_existing, bool):
        raise ValueError(
            f"Configuration '{name}' in {source} must use a boolean 'reuseExisting'."
        )

    timeout = raw.get("startupTimeoutSeconds", _PORT_WAIT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError(
            f"Configuration '{name}' in {source} must use a numeric 'startupTimeoutSeconds'."
        )
    timeout = float(timeout)
    if not _MIN_STARTUP_TIMEOUT_SECONDS <= timeout <= _MAX_STARTUP_TIMEOUT_SECONDS:
        raise ValueError(
            f"Configuration '{name}' in {source} must set 'startupTimeoutSeconds' "
            f"between {int(_MIN_STARTUP_TIMEOUT_SECONDS)} and {int(_MAX_STARTUP_TIMEOUT_SECONDS)}."
        )

    return LaunchConfiguration(
        name=normalized_name,
        runtime_executable=executable.strip(),
        runtime_args=tuple(raw_args),
        port=raw_port,
        cwd=raw_cwd,
        env=tuple(sorted(env)),
        reuse_existing=reuse_existing,
        startup_timeout_seconds=timeout,
    )


def _load_configurations(
    workspace: Path,
) -> tuple[list[LaunchConfiguration], str | None]:
    """Return ``(configurations, source_path)`` from the first config found."""
    for rel in _CONFIG_FILES:
        path = workspace / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid launch config at {path}: {e}") from e
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a top-level JSON object.")
        version = data.get("version")
        if version is not None and not isinstance(version, str):
            raise ValueError(f"{path} must use a string 'version' when provided.")
        configs = data.get("configurations")
        if not isinstance(configs, list):
            raise ValueError(f"{path} must contain a top-level 'configurations' array.")
        validated = [
            _validate_configuration(item, str(path), index)
            for index, item in enumerate(configs)
        ]
        names = [item.name for item in validated]
        if len(names) != len(set(names)):
            raise ValueError(f"{path} contains duplicate configuration names.")
        return validated, str(path)
    return [], None


def _find_configuration(
    workspace: Path, name: str | None
) -> tuple[LaunchConfiguration, str]:
    configs, source = _load_configurations(workspace)
    if source is None:
        raise ValueError(
            "No launch config found. Create .evoflux/launch.json in the "
            "workspace with the format shown in the preview tool description "
            "(configurations: [{name, runtimeExecutable, runtimeArgs, port}]), "
            "then call preview(action='start', name='<name>') again."
        )
    if not configs:
        raise ValueError(f"{source} has an empty 'configurations' array.")
    if name is None:
        if len(configs) == 1:
            cfg = configs[0]
        else:
            names = ", ".join(c.name for c in configs)
            raise ValueError(f"Multiple configurations ({names}) — pass name=.")
    else:
        matches = [c for c in configs if c.name == name]
        if not matches:
            names = ", ".join(c.name for c in configs)
            raise ValueError(
                f"No configuration named '{name}' in {source}. Available: {names}"
            )
        cfg = matches[0]

    return cfg, source


# ── Port probing ──────────────────────────────────────────────────────────────


async def _port_open(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=1.0
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _wait_for_port(server: PreviewServer, timeout: float) -> str | None:
    """Wait until the port opens. Returns an error string on failure."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server._process is not None and not server._process.running:
            tail = server._process.read_output(last_n=30)
            return (
                f"Server '{server.name}' exited with code "
                f"{server._process.exit_code} before opening port {server.port}.\n"
                f"--- last output ---\n{tail}"
            )
        if await _port_open(server.port):
            return None
        await asyncio.sleep(_PORT_POLL_INTERVAL)
    tail = server._process.read_output(last_n=30) if server._process else ""
    return (
        f"Server '{server.name}' did not open port {server.port} within "
        f"{int(timeout)}s.\n--- last output ---\n{tail}"
    )


# ── Actions ───────────────────────────────────────────────────────────────────


async def _start(name: str | None, workspace: Path) -> str:
    cfg, _source = _find_configuration(workspace, name)
    key = (str(workspace), cfg.name)
    async with _locked_server(key):
        existing = _servers.get(key)
        ports = {cfg.port}
        if existing is not None:
            ports.add(existing.port)
        async with _locked_ports(ports):
            return await _start_locked(cfg, workspace, key)


async def _start_locked(
    cfg: LaunchConfiguration,
    workspace: Path,
    key: tuple[str, str],
) -> str:
    from app.agent.sandbox import get_sandbox
    from app.agent.tools.builtin.shell import _scrubbed_env

    sandbox = get_sandbox()
    if not sandbox.allow_network:
        return (
            "Preview requires Network access because the development server must "
            "bind a local port. Enable it in Settings → Sandbox, then retry."
        )

    existing = _servers.get(key)
    if existing is not None:
        same_config = existing.config_fingerprint == cfg.fingerprint
        port_ready = await _port_open(existing.port)
        if existing.running and same_config and port_ready:
            label = "external (reused)" if existing.reused else f"pid {existing.pid}"
            return (
                f"Server '{cfg.name}' already running on http://localhost:{existing.port} "
                f"({label}). Use browser_use navigate to open it."
            )
        if existing._process is not None:
            await existing._process.terminate()
        _servers.pop(key, None)
        logger.info(
            "preview_server_replaced name={} old_port={} config_changed={} port_ready={}",
            existing.name,
            existing.port,
            not same_config,
            port_ready,
        )

    tracked_owner = next(
        (
            (owner_key, server)
            for owner_key, server in _servers.items()
            if owner_key != key and server.port == cfg.port
        ),
        None,
    )
    if tracked_owner is not None and await _port_open(cfg.port):
        owner_key, owner = tracked_owner
        return (
            f"Port {cfg.port} is already managed by preview configuration "
            f"'{owner.name}' in workspace {owner_key[0]}. Stop that preview or "
            "choose another port; it will not be reused under a second identity."
        )

    if await _port_open(cfg.port):
        if not cfg.reuse_existing:
            return (
                f"Port {cfg.port} is already in use and configuration '{cfg.name}' "
                "sets reuseExisting=false. Stop the conflicting process or choose another port."
            )
        _servers[key] = PreviewServer(
            name=cfg.name,
            port=cfg.port,
            command="(external process)",
            workdir=str(workspace),
            config_fingerprint=cfg.fingerprint,
        )
        return (
            f"Port {cfg.port} is already serving — reusing the existing server.\n"
            f"URL: http://localhost:{cfg.port}\n"
            f"Note: logs are unavailable for reused servers."
        )

    argv = cfg.command_argv
    command = shlex.join(argv)
    cwd = workspace / cfg.cwd if cfg.cwd else workspace
    cwd = sandbox.validate_path(str(cwd))
    if not cwd.is_dir():
        return f"Configured cwd does not exist: {cwd}"
    executable = Path(argv[0])
    executable_exists = (
        executable.is_file()
        if executable.is_absolute()
        else (
            (cwd / executable).is_file()
            if executable.parent != Path(".")
            else shutil.which(argv[0]) is not None
        )
    )
    if not executable_exists:
        return f"Executable not found: {argv[0]!r} (command: {command})"

    hit = sandbox.check_command(command)
    if hit is not None:
        resolved, denied = hit
        raise PermissionError(
            f"Sandbox blocked 'preview start': command touches "
            f"'{resolved}' (denied by '{denied}')."
        )

    env = _scrubbed_env(inherit=sandbox.inherit_shell_environment)
    env.update(dict(cfg.env))

    import subprocess
    import sys as _sys

    _extra: dict[str, Any] = {}
    if _sys.platform == "win32":
        _extra["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        _extra["start_new_session"] = True

    try:
        exec_bin, exec_argv = sandboxed_process_argv(
            argv[0],
            argv[1:],
            sandbox=sandbox,
            cwd=cwd,
        )
        proc = await asyncio.create_subprocess_exec(
            exec_bin,
            *exec_argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(cwd),
            env=env,
            **_extra,
        )
    except FileNotFoundError:
        return f"Executable not found: {argv[0]!r} (command: {command})"

    server = PreviewServer(
        name=cfg.name,
        port=cfg.port,
        command=command,
        workdir=str(cwd),
        config_fingerprint=cfg.fingerprint,
        _process=TrackedProcess(
            proc,
            command=command,
            cwd=cwd,
            timeout_seconds=None,
            scope=command_process_scope(sandbox.session_id, sandbox.workspace_root),
        ),
    )
    _servers[key] = server
    logger.info(
        "preview_server_started name={} port={} pid={} command={}",
        cfg.name,
        cfg.port,
        server.pid,
        command,
    )

    try:
        error = await _wait_for_port(server, cfg.startup_timeout_seconds)
    except asyncio.CancelledError:
        assert server._process is not None
        await server._process.terminate()
        _servers.pop(key, None)
        logger.info(
            "preview_server_start_cancelled name={} pid={}", cfg.name, server.pid
        )
        raise
    if error:
        assert server._process is not None
        await server._process.terminate()
        _servers.pop(key, None)
        logger.warning(
            "preview_server_start_failed name={} port={}", cfg.name, cfg.port
        )
        return f"{error}\nThe managed process was stopped and removed from tracking."
    return (
        f"Server '{cfg.name}' ready on http://localhost:{cfg.port} (pid {server.pid}).\n"
        f"Next: browser_use navigate to http://localhost:{cfg.port}, then check "
        f"console + snapshot."
    )


async def _stop(name: str | None, workspace: Path) -> str:
    key_prefix = str(workspace)
    keys = sorted(
        key
        for key in {*_servers, *_server_locks}
        if key[0] == key_prefix and (name is None or key[1] == name)
    )
    if not keys:
        return f"No preview server {'named ' + repr(name) + ' ' if name else ''}is tracked for this workspace."
    lines: list[str] = []
    for key in keys:
        async with _locked_server(key):
            server = _servers.get(key)
            if server is None:
                continue
            async with _locked_port(server.port):
                server = _servers.pop(key, None)
                if server is None:
                    continue
                if server._process is not None:
                    pid = server.pid
                    await server._process.terminate()
                    lines.append(f"Stopped '{server.name}' (was pid {pid}).")
                else:
                    lines.append(
                        f"'{server.name}' was an external server (reused) — not stopped, "
                        f"only removed from tracking."
                    )
                logger.info(
                    "preview_server_stopped name={} port={}",
                    server.name,
                    server.port,
                )
    if not lines:
        return f"No preview server {'named ' + repr(name) + ' ' if name else ''}is tracked for this workspace."
    return "\n".join(lines)


async def _status(workspace: Path) -> str:
    keys = sorted(key for key in _servers if key[0] == str(workspace))
    if not keys:
        return "No preview servers tracked for this workspace."
    config_error: str | None = None
    try:
        configurations, source = _load_configurations(workspace)
        configured = {
            configuration.name: configuration for configuration in configurations
        }
    except ValueError as exc:
        configured = {}
        source = None
        config_error = str(exc)
    lines: list[str] = []
    for key in keys:
        async with _locked_server(key):
            server = _servers.get(key)
            if server is None:
                continue
            port_ready = await _port_open(server.port)
            if server.reused and not port_ready:
                _servers.pop(key, None)
                lines.append(
                    f"{server.name}: stopped — port {server.port} closed "
                    "(stale external tracking removed)"
                )
                continue
            if server.reused:
                state = "running"
                origin = "reused external"
            elif server._process is not None and not server._process.running:
                state = f"exited ({server._process.exit_code})"
                origin = f"pid {server.pid}"
            elif not port_ready:
                state = "unhealthy (process alive, port closed)"
                origin = f"pid {server.pid}"
            else:
                state = "running"
                origin = f"pid {server.pid}"
            config_note = ""
            current = configured.get(server.name)
            if config_error:
                config_note = " — launch config invalid"
            elif source is None or current is None:
                config_note = " — configuration removed"
            elif current.fingerprint != server.config_fingerprint:
                config_note = " — configuration changed; call start to restart"
            lines.append(
                f"{server.name}: {state} — http://localhost:{server.port} "
                f"({origin}){config_note}"
            )
    if config_error:
        lines.append(f"Launch config error: {config_error}")
    return "\n".join(lines) or "No preview servers tracked for this workspace."


async def _logs(
    name: str | None, workspace: Path, lines: int, search: str | None
) -> str:
    matches = [
        (key, server)
        for key, server in _servers.items()
        if key[0] == str(workspace) and (name is None or server.name == name)
    ]
    if not matches:
        return "No preview server to read logs from. Start one first."
    if len(matches) > 1:
        names = ", ".join(server.name for _key, server in matches)
        return f"Multiple servers running ({names}) — pass name=."
    key, _server = matches[0]
    async with _locked_server(key):
        server = _servers.get(key)
        if server is None:
            return "No preview server to read logs from. Start one first."
        if server._process is None:
            return f"'{server.name}' is an external server — logs unavailable."
        output = server._process.read_output()
        out_lines = output.splitlines()
        if search:
            out_lines = [ln for ln in out_lines if search in ln]
        out_lines = out_lines[-lines:]
        if not out_lines:
            return "(no matching log output)" if search else "(no log output yet)"
        return "\n".join(out_lines)


async def stop_all_servers() -> None:
    """Stop every managed preview server — called from app shutdown.

    Spawned servers run in their own process groups and would outlive the
    sidecar otherwise. External (reused) servers are left alone.
    """
    for key, server in list(_servers.items()):
        if server._process is not None:
            try:
                await server._process.terminate()
            except Exception:
                pass
        _servers.pop(key, None)
    _server_locks.clear()
    _port_locks.clear()
    logger.info("preview_servers_stopped_on_shutdown")


# ── Tool ──────────────────────────────────────────────────────────────────────


async def _preview(
    action: Annotated[
        Literal["start", "stop", "status", "logs"],
        Field(description="Lifecycle action to perform."),
    ],
    name: Annotated[
        str | None,
        Field(
            description=(
                "Configuration name from launch.json. Optional when only one "
                "configuration/server exists."
            )
        ),
    ] = None,
    lines: Annotated[
        int,
        Field(ge=1, le=500, description="Max log lines to return (logs action)."),
    ] = _DEFAULT_LOG_LINES,
    search: Annotated[
        str | None,
        Field(description="Only return log lines containing this text (logs action)."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Start and manage the project's dev server for browser verification.

    Reads ``.evoflux/launch.json`` (or ``.claude/launch.json``) from the
    workspace root. If neither exists, create one first with the `write`
    tool::

        {"version": "0.0.2", "configurations": [
          {"name": "web", "runtimeExecutable": "npm",
           "runtimeArgs": ["run", "dev"], "port": 5173,
           "reuseExisting": true, "startupTimeoutSeconds": 60}]}

    ``start`` reuses a server that is already listening on the configured
    port; otherwise it spawns the command, captures its output, and waits
    for the port to accept connections. Then use ``browser_use`` to
    navigate to the returned URL and verify (console → snapshot →
    screenshot). ``logs`` returns captured stdout/stderr — check it when
    the page misbehaves or the server fails to start.
    """
    workspace = _workspace_root()
    if action == "start":
        return await _start(name, workspace)
    if action == "stop":
        return await _stop(name, workspace)
    if action == "status":
        return await _status(workspace)
    if action == "logs":
        return await _logs(name, workspace, lines, search)
    return f"Unknown action: {action}"


preview_tool = Tool(
    _preview,
    name="preview",
    concurrency_safe=False,
    tiers=("work", "coding"),
    deferred=True,
    deferred_summary="Start, inspect, or stop a configured development server for browser verification.",
    search_aliases=(
        "devserver",
        "localhost",
        "npm",
        "vite",
        "port",
        "frontend",
    ),
)
