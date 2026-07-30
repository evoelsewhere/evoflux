"""Shell binary selection — honours the user's $SHELL with safety guardrails.

Mirrors the design of opencode's ``shell.ts``:

- Reads ``$SHELL`` from the environment.
- Rejects incompatible shells (``fish``, ``nu``) that do not speak
  POSIX syntax — agents produce POSIX commands so incompatible shells
  would misinterpret them.
- Falls back through ``zsh`` → ``bash`` → ``sh`` when no usable shell is
  found or the preference is blocked.
- On Windows, uses PowerShell (preferred) or cmd.exe.
- Exposes ``preferred()`` (exact user preference, may be None) and
  ``acceptable()`` (always non-None, safe to pass to subprocess).

Both are lazy ``functools.cached_property``-style singletons — detected once
per process, cached forever.  Tests can override by patching
``app.agent.tools.builtin.shell_runtime._CACHED_SHELL``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"

# ── Shell name sets ──────────────────────────────────────────────────────────

# Shells that do not understand POSIX syntax; agents generate POSIX commands
# so we must never dispatch to these.
BLACKLIST: frozenset[str] = frozenset({"fish", "nu", "nushell"})

# POSIX-compatible shells — ordered by preference (best first)
_POSIX_FALLBACKS: tuple[str, ...] = ("zsh", "bash", "sh")

# Windows shells — ordered by preference.
# bash (Git Bash) gives full POSIX compatibility; pwsh (PS7) supports &&
# as a pipeline chain operator; powershell (PS5.1) is a reasonable fallback;
# cmd.exe is the last resort.
_WINDOWS_SHELLS: tuple[str, ...] = (
    "bash",
    "pwsh",
    "pwsh.exe",
    "powershell",
    "powershell.exe",
    "cmd.exe",
)


# ── Internal helpers ─────────────────────────────────────────────────────────


def _shell_name(path: str) -> str:
    """Return the lowercase basename of a shell path (no extension on any OS)."""
    stem = Path(path).stem.lower()
    return stem


def _which(name: str) -> str | None:
    """Return the full path to *name* if it is on PATH, else None."""
    return shutil.which(name)


def _is_usable(path: str) -> bool:
    """True if *path* is a non-blacklisted, executable shell."""
    name = _shell_name(path)
    if name in BLACKLIST:
        return False
    # Must exist and be executable (shutil.which already guarantees this for
    # names; for absolute paths we verify directly).
    if os.path.isabs(path):
        return os.access(path, os.X_OK)
    return _which(path) is not None


def _fallback() -> str:
    """Return the best available shell on this machine."""
    if _IS_WINDOWS:
        return _windows_fallback()
    # macOS always ships /bin/zsh since Catalina
    if sys.platform == "darwin":
        return "/bin/zsh"
    for name in _POSIX_FALLBACKS:
        found = _which(name)
        if found:
            return found
    return "/bin/sh"  # POSIX guarantee — always present


def _windows_fallback() -> str:
    """Return the best available Windows shell (PowerShell preferred)."""
    for name in _WINDOWS_SHELLS:
        found = _which(name)
        if found:
            return found
    # COMSPEC is always set on Windows (typically cmd.exe)
    return os.environ.get("COMSPEC", "cmd.exe")


# ── Module-level detection cache ────────────────────────────────────────────
# Mutate ``_CACHED_SHELL`` in tests to override detection without environment
# manipulation.

_CACHED_SHELL: str | None = None  # sentinel — populated on first use


def _detect() -> str:
    """Detect the best shell, caching the result in ``_CACHED_SHELL``.

    Detection order:
    1. ``$SHELL`` environment variable (POSIX) or ``COMSPEC`` (Windows).
    2. Platform-specific fallbacks.
    """
    global _CACHED_SHELL
    if _CACHED_SHELL is not None:
        return _CACHED_SHELL

    if _IS_WINDOWS:
        # Prefer the _windows_fallback order (bash → pwsh → powershell → cmd)
        # over COMSPEC which almost always resolves to cmd.exe.  cmd.exe does
        # not understand POSIX commands that agents generate, so it must be
        # the last resort, not the first.
        _CACHED_SHELL = _windows_fallback()
        return _CACHED_SHELL

    env_shell = os.environ.get("SHELL", "")
    if env_shell and _is_usable(env_shell):
        _CACHED_SHELL = env_shell
        return _CACHED_SHELL

    # env_shell was blacklisted (e.g. fish) or empty — pick a POSIX fallback
    _CACHED_SHELL = _fallback()
    return _CACHED_SHELL


# ── Public API ───────────────────────────────────────────────────────────────


def acceptable() -> str:
    """Return the shell binary path to use for subprocess execution.

    Always returns a non-None, executable path.
    """
    return _detect()


def name(shell_path: str | None = None) -> str:
    """Return the lowercase name of a shell (basename without extension).

    If *shell_path* is None, uses :func:`acceptable` to get the current shell.
    """
    return _shell_name(shell_path or acceptable())


def is_posix(shell_path: str | None = None) -> bool:
    """True if the shell speaks POSIX sh syntax."""
    n = name(shell_path)
    return n in {"bash", "dash", "ksh", "sh", "zsh"}


def is_windows(shell_path: str | None = None) -> bool:
    """True if the shell is a Windows shell (cmd or PowerShell)."""
    n = name(shell_path)
    return n in {"cmd", "powershell", "pwsh"}


# ── argv construction ───────────────────────────────────────────────────────
# Mirrors opencode's ``shell.ts`` (packages/opencode/src/shell/shell.ts).
#
# When a GUI app (or any non-interactive context) launches the daemon, its
# PATH only contains system defaults — user dirs like ``~/.local/bin``,
# ``~/.bun/bin``, ``~/.cargo/bin``, and ``$(brew --prefix)/bin`` are missing
# because they are added by interactive rc files (``~/.zshrc``, ``~/.bashrc``).
# A plain ``zsh -c`` does NOT source those files, so the agent cannot find
# tools the user installed.
#
# Fix: invoke the shell with ``-l`` (login) AND explicitly source the
# interactive rc files.  Errors during sourcing are swallowed so a broken
# rc never blocks a command.  Other POSIX shells (sh/dash/ksh) fall back
# to bare ``-c`` — they have no widely-used per-user rc convention.


def build_argv(shell_bin: str, command: str) -> list[str]:
    """Return argv (after the shell binary) that runs *command* with full user PATH.

    For zsh/bash we wrap *command* in a small script that sources the user's
    rc files before evaluating it.  For other POSIX shells we use a bare
    ``-c`` since they have no portable per-user rc convention.

    For Windows shells we use the appropriate flag (``/c`` for cmd,
    ``-Command`` for PowerShell).

    The shell's ``cwd`` is set by the caller via ``subprocess`` ``cwd=`` —
    we don't ``cd`` inside the script so a missing workdir raises a clear
    OS-level error instead of an opaque shell error.
    """
    shell_name = _shell_name(shell_bin)

    # ── Windows shells ─────────────────────────────────────────────────
    if shell_name == "cmd":
        return ["/c", command]

    if shell_name in ("powershell", "pwsh"):
        # -NoProfile: skip loading profile (faster, no side effects)
        # -NonInteractive: no prompts
        # -Command: run the following string as a script
        return ["-NoProfile", "-NonInteractive", "-Command", command]

    # ── POSIX shells ───────────────────────────────────────────────────
    if shell_name == "zsh":
        # -l loads ~/.zprofile/~/.zlogin; explicit source covers ~/.zshenv
        # and ~/.zshrc which a non-interactive login shell skips.
        # ``eval $1`` keeps quoting/$VAR semantics identical to ``zsh -c``.
        wrapper = (
            "[[ -f ~/.zshenv ]] && source ~/.zshenv >/dev/null 2>&1 || true; "
            '[[ -f "${ZDOTDIR:-$HOME}/.zshrc" ]] && '
            'source "${ZDOTDIR:-$HOME}/.zshrc" >/dev/null 2>&1 || true; '
            'eval "$1"'
        )
        return ["-l", "-c", wrapper, "EvoFlux", command]

    if shell_name == "bash":
        wrapper = (
            "shopt -s expand_aliases; "
            "[[ -f ~/.bashrc ]] && source ~/.bashrc >/dev/null 2>&1 || true; "
            'eval "$1"'
        )
        return ["-l", "-c", wrapper, "EvoFlux", command]

    # sh, dash, ksh, anything else POSIX-compatible
    return ["-c", command]


def reset_cache() -> None:
    """Clear the cached shell detection — for test isolation only."""
    global _CACHED_SHELL
    _CACHED_SHELL = None
