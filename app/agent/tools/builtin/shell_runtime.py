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
- Exposes ``require_bash()`` for callers that must run POSIX ``.sh``
  scripts. That path rejects the Windows WSL ``bash.exe`` stub and prefers
  Git Bash.

Both are lazy ``functools.cached_property``-style singletons — detected once
per process, cached forever.  Tests can override by patching
``app.agent.tools.builtin.shell_runtime._CACHED_SHELL`` /
``_CACHED_BASH``.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


class BashNotFoundError(RuntimeError):
    """No usable bash binary is available for POSIX script execution."""


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


def _is_wsl_bash_stub(path: str) -> bool:
    """True for the Windows Store / System32 WSL ``bash.exe`` redirector.

    That binary exists whenever WSL is advertised, even if no distro is
    installed — spawning it then fails with ``execvpe(/bin/bash)``. Prefer
    Git Bash or PowerShell instead of treating the stub as a usable shell.
    """
    normalized = path.replace("/", "\\").lower()
    return normalized.endswith(
        (
            "\\system32\\bash.exe",
            "\\sysnative\\bash.exe",
            "\\windowsapps\\bash.exe",
        )
    )


def _is_usable(path: str) -> bool:
    """True if *path* is a non-blacklisted, executable shell."""
    name = _shell_name(path)
    if name in BLACKLIST:
        return False
    if _IS_WINDOWS and name == "bash" and _is_wsl_bash_stub(path):
        return False
    # Must exist and be executable (shutil.which already guarantees this for
    # names; for absolute paths we verify directly).
    if os.path.isabs(path):
        return os.access(path, os.X_OK)
    found = _which(path)
    if found is None:
        return False
    if _IS_WINDOWS and name == "bash" and _is_wsl_bash_stub(found):
        return False
    return True


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
    """Return the best available Windows shell (Git Bash → pwsh → powershell)."""
    # Prefer a real bash first. PATH may only expose the WSL System32 stub,
    # which `_is_usable` rejects — still look for Git Bash install roots
    # before falling through to PowerShell/cmd.
    which_bash = _which("bash")
    if which_bash and _is_usable(which_bash):
        return which_bash
    for candidate in _windows_git_bash_paths():
        if _is_usable(candidate):
            return candidate
    for name in _WINDOWS_SHELLS:
        if name == "bash":
            continue
        found = _which(name)
        if found and _is_usable(found):
            return found
    # COMSPEC is always set on Windows (typically cmd.exe)
    return os.environ.get("COMSPEC", "cmd.exe")


def _windows_git_bash_paths() -> Iterator[str]:
    """Yield known Git-for-Windows bash locations (may not exist)."""
    git = _which("git")
    if git:
        git_path = Path(git).resolve()
        # Typical layouts: Git\\cmd\\git.exe or Git\\mingw64\\bin\\git.exe
        for ancestor in (git_path.parent, *git_path.parents):
            for parts in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
                candidate = ancestor.joinpath(*parts)
                if candidate.is_file():
                    yield str(candidate)
            if ancestor.name.lower() == "git":
                break

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    roots = [
        Path(program_files) / "Git",
        Path(program_files_x86) / "Git",
    ]
    if local_app_data:
        roots.append(Path(local_app_data) / "Programs" / "Git")
    for root in roots:
        for parts in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
            candidate = root.joinpath(*parts)
            if candidate.is_file():
                yield str(candidate)


def _iter_bash_candidates() -> Iterator[str]:
    """Yield candidate bash paths in preference order (may be unusable)."""
    override = os.environ.get("EVOFLUX_BASH", "").strip()
    if override:
        yield override

    which_bash = _which("bash")
    if which_bash:
        yield which_bash

    if _IS_WINDOWS:
        yield from _windows_git_bash_paths()
    else:
        yield from ("/bin/bash", "/usr/bin/bash")


# ── Module-level detection cache ────────────────────────────────────────────
# Mutate ``_CACHED_SHELL`` / ``_CACHED_BASH`` in tests to override detection
# without environment manipulation.

_CACHED_SHELL: str | None = None  # sentinel — populated on first use
_CACHED_BASH: str | None = None


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


def require_bash() -> str:
    """Return a usable bash binary path for POSIX ``.sh`` execution.

    Unlike :func:`acceptable`, this never falls back to PowerShell/cmd.
    On Windows the System32/WindowsApps WSL ``bash.exe`` stub is rejected
    because spawning it fails with ``execvpe(/bin/bash)`` when no distro is
    installed. Prefer Git Bash (PATH, install roots, or beside ``git.exe``).

    Override with ``EVOFLUX_BASH`` when needed. Raises
    :class:`BashNotFoundError` when no usable bash is available.
    """
    global _CACHED_BASH
    if _CACHED_BASH is not None:
        return _CACHED_BASH

    override = os.environ.get("EVOFLUX_BASH", "").strip()
    if override:
        resolved = override if os.path.isabs(override) else _which(override)
        if (
            resolved is not None
            and _shell_name(resolved) == "bash"
            and _is_usable(resolved)
        ):
            _CACHED_BASH = resolved
            return _CACHED_BASH
        if resolved is not None and _is_wsl_bash_stub(resolved):
            raise BashNotFoundError(
                "EVOFLUX_BASH points at the Windows WSL bash stub "
                f"({resolved}), which fails without a WSL distro. "
                "Install Git for Windows (Git Bash) or set EVOFLUX_BASH to "
                "a real bash.exe."
            )
        raise BashNotFoundError(f"EVOFLUX_BASH is not a usable bash binary: {override}")

    seen: set[str] = set()
    for candidate in _iter_bash_candidates():
        key = os.path.normcase(os.path.abspath(candidate))
        if key in seen:
            continue
        seen.add(key)
        if _shell_name(candidate) != "bash":
            continue
        if not _is_usable(candidate):
            continue
        resolved = candidate if os.path.isabs(candidate) else _which(candidate)
        if resolved is None or not _is_usable(resolved):
            continue
        _CACHED_BASH = resolved
        return _CACHED_BASH

    raise BashNotFoundError(
        "No usable bash found for POSIX .sh scripts. "
        "Install Git for Windows (Git Bash) or add a real bash to PATH "
        "(the Windows System32 WSL bash stub is not accepted). "
        "Optionally set EVOFLUX_BASH to the bash.exe path."
    )


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


def build_argv(
    shell_bin: str,
    command: str,
    *,
    load_profile: bool = True,
) -> list[str]:
    """Return argv (after the shell binary) that runs *command*.

    When ``load_profile`` is enabled, zsh/bash wrap *command* in a small
    script that sources the user's rc files before evaluating it. The sandbox
    disables this by default because profiles may execute code or export
    credentials. Other POSIX shells use a bare ``-c``.

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
    if shell_name == "zsh" and load_profile:
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

    if shell_name == "bash" and load_profile:
        wrapper = (
            "shopt -s expand_aliases; "
            "[[ -f ~/.bashrc ]] && source ~/.bashrc >/dev/null 2>&1 || true; "
            'eval "$1"'
        )
        return ["-l", "-c", wrapper, "EvoFlux", command]

    # Secure default for zsh/bash, plus sh/dash/ksh and other POSIX shells.
    return ["-c", command]


def reset_cache() -> None:
    """Clear the cached shell detection — for test isolation only."""
    global _CACHED_SHELL, _CACHED_BASH
    _CACHED_SHELL = None
    _CACHED_BASH = None
