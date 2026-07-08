"""preview tool — dev-server lifecycle for in-browser verification.

Companion to ``browser_use``: start the project's dev server from a
declarative config, wait until its port accepts connections, then verify
the app through the browser (navigate → console/snapshot → screenshot).

Configuration lives in ``.evoflux/launch.json`` at the workspace root
(``.claude/launch.json`` is read as a fallback so existing projects work
unchanged):

    {
      "version": "0.0.1",
      "configurations": [
        {
          "name": "web",
          "runtimeExecutable": "npm",
          "runtimeArgs": ["run", "dev"],
          "port": 5180,
          "cwd": "web",          // optional, relative to workspace
          "env": {"FOO": "1"}    // optional
        }
      ]
    }

Servers are tracked per (workspace, name). If the configured port is
already accepting connections the tool reuses it instead of spawning a
second copy.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from loguru import logger
from pydantic import Field

from app.agent.tools.registry import InjectedArg, Tool

_PORT_WAIT_SECONDS = 60.0
_PORT_POLL_INTERVAL = 0.5
_DEFAULT_LOG_LINES = 50
_CONFIG_FILES = (".evoflux/launch.json", ".claude/launch.json")


# ── Server registry ───────────────────────────────────────────────────────────


@dataclass
class PreviewServer:
    """One managed (or reused) dev server."""

    name: str
    port: int
    command: str
    workdir: str
    started_at: float = field(default_factory=time.monotonic)
    # _BgProcess from shell.py; None when we reused an externally-started server.
    _bg: Any = field(default=None, repr=False)

    @property
    def reused(self) -> bool:
        return self._bg is None

    @property
    def running(self) -> bool:
        return self.reused or bool(self._bg and self._bg.alive)

    @property
    def pid(self) -> int | None:
        return self._bg.pid if self._bg else None


# Keyed by (workspace_root, config name).
_servers: dict[tuple[str, str], PreviewServer] = {}


def _workspace_root() -> Path:
    from app.agent.tools.builtin.shell import _resolve_workdir

    return _resolve_workdir(None)


# ── Config loading ────────────────────────────────────────────────────────────


def _load_configurations(workspace: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Return ``(configurations, source_path)`` from the first config found."""
    for rel in _CONFIG_FILES:
        path = workspace / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid launch config at {path}: {e}") from e
        configs = data.get("configurations")
        if not isinstance(configs, list):
            raise ValueError(
                f"{path} must contain a top-level 'configurations' array."
            )
        return configs, str(path)
    return [], None


def _find_configuration(
    workspace: Path, name: str | None
) -> tuple[dict[str, Any], str]:
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
            names = ", ".join(str(c.get("name")) for c in configs)
            raise ValueError(f"Multiple configurations ({names}) — pass name=.")
    else:
        matches = [c for c in configs if c.get("name") == name]
        if not matches:
            names = ", ".join(str(c.get("name")) for c in configs)
            raise ValueError(f"No configuration named '{name}' in {source}. Available: {names}")
        cfg = matches[0]

    for field_name in ("name", "runtimeExecutable", "port"):
        if not cfg.get(field_name):
            raise ValueError(f"Configuration in {source} is missing '{field_name}'.")
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
        if server._bg is not None and not server._bg.alive:
            tail = server._bg.read_output(last_n=30)
            return (
                f"Server '{server.name}' exited with code "
                f"{server._bg.proc.returncode} before opening port {server.port}.\n"
                f"--- last output ---\n{tail}"
            )
        if await _port_open(server.port):
            return None
        await asyncio.sleep(_PORT_POLL_INTERVAL)
    tail = server._bg.read_output(last_n=30) if server._bg else ""
    return (
        f"Server '{server.name}' did not open port {server.port} within "
        f"{int(timeout)}s (still running — check logs).\n--- last output ---\n{tail}"
    )


# ── Actions ───────────────────────────────────────────────────────────────────


async def _start(name: str | None, workspace: Path) -> str:
    cfg, _source = _find_configuration(workspace, name)
    cfg_name = str(cfg["name"])
    port = int(cfg["port"])
    key = (str(workspace), cfg_name)

    existing = _servers.get(key)
    if existing and existing.running:
        label = "external (reused)" if existing.reused else f"pid {existing.pid}"
        return (
            f"Server '{cfg_name}' already running on http://localhost:{existing.port} "
            f"({label}). Use browser_use navigate to open it."
        )

    if await _port_open(port):
        _servers[key] = PreviewServer(
            name=cfg_name,
            port=port,
            command="(external process)",
            workdir=str(workspace),
        )
        return (
            f"Port {port} is already serving — reusing the existing server.\n"
            f"URL: http://localhost:{port}\n"
            f"Note: logs are unavailable for reused servers."
        )

    argv = [str(cfg["runtimeExecutable"]), *[str(a) for a in cfg.get("runtimeArgs", [])]]
    command = " ".join(argv)
    cwd = workspace / str(cfg["cwd"]) if cfg.get("cwd") else workspace
    if not cwd.is_dir():
        return f"Configured cwd does not exist: {cwd}"

    from app.agent.sandbox import get_sandbox
    from app.agent.tools.builtin.shell import _BgProcess, _scrubbed_env

    hit = get_sandbox().check_command(command)
    if hit is not None:
        resolved, denied = hit
        raise PermissionError(
            f"Sandbox blocked 'preview start': command touches "
            f"'{resolved}' (denied by '{denied}')."
        )

    env = _scrubbed_env()
    extra_env = cfg.get("env")
    if isinstance(extra_env, dict):
        env.update({str(k): str(v) for k, v in extra_env.items()})

    import subprocess
    import sys as _sys

    _extra: dict[str, object] = {}
    if _sys.platform == "win32":
        _extra["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        _extra["start_new_session"] = True

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
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
        name=cfg_name,
        port=port,
        command=command,
        workdir=str(cwd),
        _bg=_BgProcess(proc, command),
    )
    _servers[key] = server
    logger.info(
        "preview_server_started name={} port={} pid={} command={}",
        cfg_name,
        port,
        server.pid,
        command,
    )

    error = await _wait_for_port(server, _PORT_WAIT_SECONDS)
    if error:
        return error
    return (
        f"Server '{cfg_name}' ready on http://localhost:{port} (pid {server.pid}).\n"
        f"Next: browser_use navigate to http://localhost:{port}, then check "
        f"console + snapshot."
    )


async def _stop(name: str | None, workspace: Path) -> str:
    key_prefix = str(workspace)
    matches = [
        (key, s)
        for key, s in _servers.items()
        if key[0] == key_prefix and (name is None or s.name == name)
    ]
    if not matches:
        return f"No preview server {'named ' + repr(name) + ' ' if name else ''}is tracked for this workspace."
    lines = []
    for key, server in matches:
        if server._bg is not None:
            await server._bg.stop()
            lines.append(f"Stopped '{server.name}' (was pid {server.pid}).")
        else:
            lines.append(
                f"'{server.name}' was an external server (reused) — not stopped, "
                f"only removed from tracking."
            )
        del _servers[key]
        logger.info("preview_server_stopped name={} port={}", server.name, server.port)
    return "\n".join(lines)


def _status(workspace: Path) -> str:
    rows = [s for key, s in _servers.items() if key[0] == str(workspace)]
    if not rows:
        return "No preview servers tracked for this workspace."
    lines = []
    for s in rows:
        state = "running" if s.running else f"exited ({s._bg.proc.returncode})"
        origin = "reused external" if s.reused else f"pid {s.pid}"
        lines.append(
            f"{s.name}: {state} — http://localhost:{s.port} ({origin})"
        )
    return "\n".join(lines)


def _logs(name: str | None, workspace: Path, lines: int, search: str | None) -> str:
    matches = [
        s
        for key, s in _servers.items()
        if key[0] == str(workspace) and (name is None or s.name == name)
    ]
    if not matches:
        return "No preview server to read logs from. Start one first."
    if len(matches) > 1:
        names = ", ".join(s.name for s in matches)
        return f"Multiple servers running ({names}) — pass name=."
    server = matches[0]
    if server._bg is None:
        return f"'{server.name}' is an external server — logs unavailable."
    output = server._bg.read_output()
    out_lines = output.splitlines()
    if search:
        out_lines = [ln for ln in out_lines if search in ln]
    out_lines = out_lines[-lines:]
    if not out_lines:
        return "(no matching log output)" if search else "(no log output yet)"
    return "\n".join(out_lines)


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

        {"version": "0.0.1", "configurations": [
          {"name": "web", "runtimeExecutable": "npm",
           "runtimeArgs": ["run", "dev"], "port": 5173}]}

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
        return _status(workspace)
    if action == "logs":
        return _logs(name, workspace, lines, search)
    return f"Unknown action: {action}"


preview_tool = Tool(
    _preview,
    name="preview",
    concurrency_safe=False,
)
