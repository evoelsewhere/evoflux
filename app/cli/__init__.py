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

from app.cli.commands.address import cmd_address
from app.cli.commands.auth import cmd_auth
from app.cli.commands.cleanup import cmd_cleanup
from app.cli.commands.doctor import cmd_doctor
from app.cli.commands.health import cmd_health
from app.cli.commands.init import cmd_init
from app.cli.commands.logs import cmd_logs
from app.cli.commands.migrate import cmd_migrate
from app.cli.commands.restart import cmd_restart
from app.cli.commands.start import cmd_start
from app.cli.commands.status import cmd_status
from app.cli.commands.stop import cmd_stop
from app.cli.commands.upgrade import cmd_upgrade
from app.cli.commands.version import cmd_version
from app.cli.main import build_parser, main
from app.cli.paths import (
    _config_dir,
    _data_dir,
    _pid_file,
    _server_log,
    _state_dir,
    _web_log,
)
from app.cli.pids import (
    _clear_pids,
    _find_pids,
    _pid_alive,
    _read_pids,
    _write_pids,
)

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
