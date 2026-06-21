"""XDG-aware directory resolvers and standard log/PID file paths.

Uses the XDG base-directory layout under ``$HOME``.  Each resolver honours an
``EVOFLUX_*`` env var override so tests (and power users) can redirect paths.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_WEB_DIR = _ROOT / "web"


def _state_dir() -> Path:
    """Return the state directory (logs, pid files).

    Defaults to ``~/.local/state/EvoFlux`` (XDG_STATE_HOME). Respects an
    explicit ``EVOFLUX_STATE_DIR`` env var.
    """
    if "EVOFLUX_STATE_DIR" in os.environ:
        return Path(os.environ["EVOFLUX_STATE_DIR"])
    return Path.home() / ".local" / "state" / "EvoFlux"


def _data_dir() -> Path:
    """Return the data directory (DB, workspaces).

    Defaults to ``~/.local/share/EvoFlux`` (XDG_DATA_HOME).
    """
    if "EVOFLUX_DATA_DIR" in os.environ:
        return Path(os.environ["EVOFLUX_DATA_DIR"])
    return Path.home() / ".local" / "share" / "EvoFlux"


def _config_dir() -> Path:
    """Return the config directory (agents, skills, .env).

    Defaults to ``~/.config/EvoFlux`` (XDG_CONFIG_HOME).
    """
    if "EVOFLUX_CONFIG_DIR" in os.environ:
        return Path(os.environ["EVOFLUX_CONFIG_DIR"])
    return Path.home() / ".config" / "EvoFlux"


def _pid_file() -> Path:
    return _state_dir() / "evoflux.pid"


def _server_log() -> Path:
    return _state_dir() / "logs" / "app" / "app.log"


def _web_log() -> Path:
    return _state_dir() / "logs" / "web.log"
