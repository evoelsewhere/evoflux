"""EvoFlux — unified CLI entry point.

Usage
-----
  EvoFlux               Start server + web UI in the background
  EvoFlux init          First-time setup: write .env and seed config files
  EvoFlux migrate       Import agent config from another local agent tool
  EvoFlux auth          Authenticate with an OAuth-based provider (e.g. copilot)
  EvoFlux stop          Stop the background server and web UI
  EvoFlux restart       Restart the background server
  EvoFlux status        Show whether the server is running
  EvoFlux address       Show local and LAN server URLs
  EvoFlux health        Run server and mobile diagnostics
  EvoFlux logs          Tail the server log
  EvoFlux version       Print version and exit
  EvoFlux doctor        Check system health and report issues
  EvoFlux upgrade       Upgrade EvoFlux to the latest version

This package replaces the former monolithic ``app/cli.py`` module.  The
package-level ``__init__`` re-exports the public (and legacy-private) API so
that ``EvoFlux = "app.cli:main"`` and existing test imports keep working.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


def build_parser():  # noqa: ANN201 - argparse parser type stays owned by cli.main
    from app.cli.main import build_parser as _build_parser

    return _build_parser()


def main() -> None:
    from app.cli.main import main as _main

    _main()


_LAZY_EXPORTS = {
    "cmd_address": ("app.cli.commands.address", "cmd_address"),
    "cmd_auth": ("app.cli.commands.auth", "cmd_auth"),
    "cmd_cleanup": ("app.cli.commands.cleanup", "cmd_cleanup"),
    "cmd_doctor": ("app.cli.commands.doctor", "cmd_doctor"),
    "cmd_health": ("app.cli.commands.health", "cmd_health"),
    "cmd_init": ("app.cli.commands.init", "cmd_init"),
    "cmd_logs": ("app.cli.commands.logs", "cmd_logs"),
    "cmd_migrate": ("app.cli.commands.migrate", "cmd_migrate"),
    "cmd_restart": ("app.cli.commands.restart", "cmd_restart"),
    "cmd_start": ("app.cli.commands.start", "cmd_start"),
    "cmd_status": ("app.cli.commands.status", "cmd_status"),
    "cmd_stop": ("app.cli.commands.stop", "cmd_stop"),
    "cmd_upgrade": ("app.cli.commands.upgrade", "cmd_upgrade"),
    "cmd_version": ("app.cli.commands.version", "cmd_version"),
    "_config_dir": ("app.cli.paths", "_config_dir"),
    "_data_dir": ("app.cli.paths", "_data_dir"),
    "_pid_file": ("app.cli.paths", "_pid_file"),
    "_server_log": ("app.cli.paths", "_server_log"),
    "_state_dir": ("app.cli.paths", "_state_dir"),
    "_web_log": ("app.cli.paths", "_web_log"),
    "_clear_pids": ("app.cli.pids", "_clear_pids"),
    "_find_pids": ("app.cli.pids", "_find_pids"),
    "_pid_alive": ("app.cli.pids", "_pid_alive"),
    "_read_pids": ("app.cli.pids", "_read_pids"),
    "_write_pids": ("app.cli.pids", "_write_pids"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 - compatibility re-export
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value

__all__ = [
    "build_parser",
    "main",
    # commands
    "cmd_address",
    "cmd_auth",
    "cmd_cleanup",
    "cmd_doctor",
    "cmd_health",
    "cmd_init",
    "cmd_logs",
    "cmd_migrate",
    "cmd_restart",
    "cmd_start",
    "cmd_status",
    "cmd_stop",
    "cmd_upgrade",
    "cmd_version",
    # path helpers (kept public for tests)
    "_config_dir",
    "_data_dir",
    "_pid_file",
    "_server_log",
    "_state_dir",
    "_web_log",
    # pid helpers
    "_clear_pids",
    "_find_pids",
    "_pid_alive",
    "_read_pids",
    "_write_pids",
]
