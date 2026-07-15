"""First-run detection for ``EvoFlux``.

When the user types ``EvoFlux`` and the install hasn't been initialised
yet, the CLI auto-launches ``EvoFlux init`` before starting the server
— so the headline UX is genuinely one command.

A run is considered uninitialised when **either**:

- The expected ``.env`` file is missing **and** no LLM provider
  credential is present in the environment, **or**
- ``{EVOFLUX_CONFIG_DIR}/agents/`` does not contain at least one
  ``.md`` file (so the team-manager would load nothing).

Behaviour matrix
----------------

+----------------+---------------+-----------------------------------+
| Initialised?   | Stdin is TTY? | Action                            |
+================+===============+===================================+
| Yes            | —             | Continue normally.                |
+----------------+---------------+-----------------------------------+
| No             | Yes           | Print banner, run ``cmd_init``,   |
|                |               | then continue.                    |
+----------------+---------------+-----------------------------------+
| No             | No            | Print hint, exit 1. Avoids        |
|                |               | silently starting a broken server |
|                |               | from a script / systemd unit.     |
+----------------+---------------+-----------------------------------+
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.cli.paths import _config_dir
from app.cli.ui import _bold, _cyan, _dim, _yellow

#: Env vars whose presence we treat as "user has at least one provider set up."
_PROVIDER_KEYS: tuple[str, ...] = (
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ZAI_API_KEY",
    "NVIDIA_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "FOUNDRY_API_KEY",
    "ROUTER9_API_KEY",
    "CLIPROXY_API_KEY",
    # OAuth-based providers don't expose env vars — initialisation will
    # detect them via the cached oauth.json instead.
    # Vertex AI uses ADC (no API key) plus GOOGLE_CLOUD_PROJECT.
    "GOOGLE_CLOUD_PROJECT",
)


def is_initialised() -> bool:
    """Return ``True`` if the install looks ready to start the server."""
    return _has_credentials() and _has_agents()


def ensure_initialised() -> None:
    """Run interactive ``cmd_init`` if the install isn't ready.

    Exits the process with code 1 in non-interactive contexts so that
    scripts get a clear error instead of a silently broken server.
    """
    if is_initialised():
        return

    print()
    print(f"  {_bold(_cyan('Welcome to EvoFlux!'))}")
    print(f"  {_dim('No configuration found. Setting up your install now…')}")
    print()

    if not sys.stdin.isatty():
        print(
            f"  {_yellow('!')}  No \033[1m.env\033[0m or agents detected and stdin is not a TTY."
        )
        print(f"     Run {_bold('EvoFlux init')} interactively first.")
        print()
        sys.exit(1)

    # Lazy import so plain ``--help`` / ``status`` don't pay the cost.
    import argparse

    from app.cli.commands.init import cmd_init

    cmd_init(argparse.Namespace())


# ── Internals ────────────────────────────────────────────────────────────────


def _has_credentials() -> bool:
    """A credential exists if any provider env var is set OR an .env file
    that looks populated lives where settings will load it from.
    """
    if any(os.environ.get(k) for k in _PROVIDER_KEYS):
        return True

    env_file = _env_file()
    if env_file.is_file():
        # Treat any non-comment, non-blank line as evidence the user has
        # configured something — we don't try to validate keys here.
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return True
    return False


def _has_agents() -> bool:
    """At least one ``.md`` file must live in ``{EVOFLUX_CONFIG_DIR}/agents/``."""
    agents_dir = _config_dir() / "agents"
    if not agents_dir.is_dir():
        return False
    return any(agents_dir.glob("*.md"))


def _env_file() -> Path:
    """Path to the ``.env`` we expect ``EvoFlux init`` to have written."""
    return _config_dir() / ".env"
