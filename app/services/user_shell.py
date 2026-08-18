"""User-shell discovery for desktop subprocesses.

GUI applications do not inherit the login environment that Terminal.app does.
This module resolves the account's real shell and can read only its resulting
``PATH`` without importing the rest of the profile environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache

_PATH_MARKER = "__EVOFLUX_LOGIN_PATH__="
_PROFILE_TIMEOUT_SECONDS = 5
_PYTHON_RUNTIME_KEYS = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONEXECUTABLE",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
        "VIRTUAL_ENV_PROMPT",
        "UV_PYTHON",
        "UV_PROJECT_ENVIRONMENT",
    }
)


def _usable_shell(value: str | None) -> str | None:
    if not value:
        return None
    candidate = os.path.expanduser(value)
    if os.path.isabs(candidate):
        return (
            candidate
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK)
            else None
        )
    return shutil.which(candidate)


def resolve_login_shell() -> str:
    """Return the account's real shell, even when a GUI process lacks SHELL."""
    if sys.platform == "win32":
        return os.environ.get("COMSPEC") or "cmd.exe"

    configured = _usable_shell(os.environ.get("SHELL"))
    if configured:
        return configured

    try:
        import pwd

        account_shell = _usable_shell(pwd.getpwuid(os.getuid()).pw_shell)
        if account_shell:
            return account_shell
    except (ImportError, KeyError, OSError):
        pass

    if sys.platform == "darwin" and _usable_shell("/bin/zsh"):
        return "/bin/zsh"
    return _usable_shell("bash") or _usable_shell("sh") or "/bin/sh"


def interactive_login_argv(shell: str) -> list[str]:
    """Argv for a human-facing interactive shell with login profiles loaded."""
    if os.path.basename(shell) in {"bash", "zsh"}:
        return [shell, "-il"]
    if os.path.basename(shell) == "sh":
        return [shell, "-i"]
    return [shell]


def _profile_probe_env(shell: str) -> dict[str, str]:
    allowed = {"HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TERM", "TMPDIR"}
    env = {
        key: value
        for key, value in os.environ.items()
        if key in allowed or key.startswith("LC_")
    }
    env["PATH"] = os.environ.get("PATH", os.defpath)
    env["SHELL"] = shell
    env["TERM"] = env.get("TERM") or "dumb"
    env["EVOFLUX_PATH_DISCOVERY"] = "1"
    return env


@lru_cache(maxsize=16)
def _discover_login_path_cached(
    shell: str, home: str, inherited_path: str
) -> str | None:
    shell_name = os.path.basename(shell)
    if shell_name not in {"bash", "zsh"}:
        return None
    env = _profile_probe_env(shell)
    env["HOME"] = home
    env["PATH"] = inherited_path
    probe = f'printf "\\n{_PATH_MARKER}%s\\n" "$PATH"'
    try:
        completed = subprocess.run(  # noqa: S603 — resolved account shell
            [shell, "-l", "-i", "-c", probe],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_PROFILE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    for line in reversed(completed.stdout.splitlines()):
        if not line.startswith(_PATH_MARKER):
            continue
        value = line.removeprefix(_PATH_MARKER).strip()
        if value and "\x00" not in value:
            return value
    return None


def discover_login_path(shell: str | None = None) -> str | None:
    """Return PATH produced by the login shell, ignoring all other exports."""
    if sys.platform == "win32":
        return os.environ.get("PATH")
    resolved = shell or resolve_login_shell()
    return _discover_login_path_cached(
        resolved,
        os.path.expanduser("~"),
        os.environ.get("PATH", os.defpath),
    )


def user_terminal_environment() -> dict[str, str]:
    """Copy host env without leaking EvoFlux or bundled-Python internals."""
    blocked_upper = {key.upper() for key in _PYTHON_RUNTIME_KEYS}
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("EVOFLUX_") and key.upper() not in blocked_upper
    }
