"""Native process sandbox wrappers used by shell-like tools."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from loguru import logger

from app.agent.sandbox import SandboxConfig, _allowed_internal_roots, _path_is_under


def native_process_sandbox_backend() -> str | None:
    """Return the native containment backend available on this host."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return None


def sandboxed_process_argv(
    executable: str,
    args: list[str],
    *,
    sandbox: SandboxConfig,
    cwd: Path,
) -> tuple[str, list[str]]:
    """Wrap a process with the strongest native sandbox available.

    ``best_effort`` is the compatibility mode and returns the original argv.
    In ``required`` mode macOS uses Seatbelt via ``sandbox-exec`` and Linux
    uses Bubblewrap; unsupported hosts fail closed.
    """
    # ``best_effort`` is an explicit user opt-out from sandbox enforcement,
    # not merely a fallback mode when native containment is unavailable.
    # Return the original argv so macOS Seatbelt/Bubblewrap cannot impose a
    # second, invisible policy on commands such as ``uv run``.
    if sandbox.native_process_isolation == "best_effort":
        return executable, args

    backend = native_process_sandbox_backend()
    if backend == "seatbelt":
        sandbox_exec = shutil.which("sandbox-exec")
        if sandbox_exec is not None:
            profile = _macos_profile(sandbox)
            return sandbox_exec, ["-p", profile, executable, *args]

    if backend == "bubblewrap":
        bwrap = shutil.which("bwrap")
        if bwrap is not None:
            wrapped = [
                "--die-with-parent",
                "--new-session",
                "--ro-bind",
                "/",
                "/",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
            ]
            if not sandbox.allow_network:
                wrapped.append("--unshare-net")
            for root in _writable_roots(sandbox):
                if root.exists():
                    wrapped.extend(["--bind", str(root), str(root)])
            wrapped.extend(["--chdir", str(cwd), executable, *args])
            return bwrap, wrapped

    if sandbox.native_process_isolation == "required":
        raise PermissionError(
            "Native process isolation is required by Sandbox settings, but no "
            f"supported backend is available on {sys.platform}. Install "
            "bubblewrap on Linux or switch isolation to Best effort."
        )

    logger.warning(
        "process_sandbox_native_backend_unavailable platform={} network_allowed={}",
        sys.platform,
        sandbox.allow_network,
    )
    return executable, args


def _writable_roots(sandbox: SandboxConfig) -> list[Path]:
    roots = [
        *(
            sandbox.write_allowed_paths
            if sandbox.write_allowed_paths
            else sandbox.allowed_workspace_roots
        )
    ]
    roots = [
        path
        for path in roots
        if not any(
            _path_is_under(path.resolve(), root) for root in sandbox.read_only_paths
        )
    ]
    # A linked Git worktree stores its index, object database, and branch refs
    # in the source repository's common ``.git`` directory. When the caller has
    # a whole-workspace write lease, grant that validated Git metadata root too;
    # otherwise even ``git status``/``git commit`` fails on ``index.lock``.
    whole_workspace_leases = {path.resolve() for path in roots}
    for workspace in sandbox.allowed_workspace_roots:
        if workspace.resolve() in whole_workspace_leases:
            roots.extend(_linked_worktree_git_roots(workspace))
    roots.extend(_allowed_internal_roots(sandbox.session_id))
    return list(dict.fromkeys(path.resolve() for path in roots))


def _linked_worktree_git_roots(workspace: Path) -> list[Path]:
    """Return a validated linked-worktree common Git directory.

    The backlink check is important: a model-writable ``.git`` file must not be
    able to point at an arbitrary host directory and turn it into a writable
    sandbox mount on the next command.
    """
    marker = workspace.resolve() / ".git"
    if not marker.is_file():
        return []
    try:
        marker_text = marker.read_text(encoding="utf-8").strip()
        if not marker_text.lower().startswith("gitdir:"):
            return []
        raw_git_dir = Path(marker_text.split(":", 1)[1].strip())
        git_dir = (
            raw_git_dir if raw_git_dir.is_absolute() else marker.parent / raw_git_dir
        ).resolve()
        if git_dir.parent.name != "worktrees":
            return []
        common_dir = git_dir.parent.parent.resolve()
        if common_dir.name != ".git":
            return []

        backlink = git_dir / "gitdir"
        common_file = git_dir / "commondir"
        if not backlink.is_file() or not common_file.is_file():
            return []
        raw_backlink = Path(backlink.read_text(encoding="utf-8").strip())
        resolved_backlink = (
            raw_backlink
            if raw_backlink.is_absolute()
            else backlink.parent / raw_backlink
        ).resolve()
        raw_common = Path(common_file.read_text(encoding="utf-8").strip())
        resolved_common = (
            raw_common if raw_common.is_absolute() else common_file.parent / raw_common
        ).resolve()
        if resolved_backlink != marker.resolve() or resolved_common != common_dir:
            return []
        return [common_dir]
    except (OSError, UnicodeError, ValueError):
        return []


def _macos_profile(sandbox: SandboxConfig) -> str:
    pattern_exclusions = [
        f'(require-not (regex #"{_seatbelt_escape(_glob_to_regex(pattern))}"))'
        for pattern in sandbox.denied_patterns
        if pattern
    ]
    write_rules = [
        _macos_allow_rule("file-write*", root, pattern_exclusions)
        for root in _writable_roots(sandbox)
    ]
    temp_exclusions = [
        *pattern_exclusions,
        *(
            f'(require-not (subpath "{_seatbelt_escape(str(root.resolve()))}"))'
            for root in [*sandbox.denied_roots, *sandbox.read_only_paths]
        ),
    ]
    write_rules.extend(
        _macos_allow_rule("file-write*", root, temp_exclusions)
        for root in _temporary_roots()
    )
    network_rule = "(allow network*)" if sandbox.allow_network else "(deny network*)"
    return " ".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            *_macos_read_rules(sandbox, pattern_exclusions),
            *write_rules,
            # Shell redirections and Git open this character device even for
            # otherwise read-only commands.  Keep the exception narrowly
            # scoped rather than allowing writes to all of /dev.
            '(allow file-write* (literal "/dev/null"))',
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            network_rule,
        ]
    )


def _macos_read_rules(
    sandbox: SandboxConfig,
    pattern_exclusions: list[str],
) -> list[str]:
    denied_root_exclusions = [
        f'(require-not (subpath "{_seatbelt_escape(str(root.resolve()))}"))'
        for root in sandbox.denied_roots
    ]
    rules = [
        _macos_allow_rule(
            "file-read*",
            None,
            [*denied_root_exclusions, *pattern_exclusions],
        )
    ]
    # Application-level policy exempts explicitly authorized roots from the
    # broad EvoFlux data/state/cache deny roots, while deny globs such as
    # ``**/.env`` continue to apply inside those workspaces.
    for root in [
        *sandbox.allowed_workspace_roots,
        *sandbox.read_only_paths,
        *_allowed_internal_roots(sandbox.session_id),
    ]:
        rules.append(_macos_allow_rule("file-read*", root, pattern_exclusions))
    return rules


def _temporary_roots() -> list[Path]:
    roots = [Path("/private/tmp"), Path("/tmp")]
    for key in ("TMPDIR", "TMP", "TEMP"):
        raw = os.environ.get(key)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_absolute() and path.exists():
            roots.append(path)
    return list(dict.fromkeys(path.resolve() for path in roots))


def _macos_allow_rule(
    operation: str,
    root: Path | None,
    exclusions: list[str],
) -> str:
    filters = [
        *(
            [f'(subpath "{_seatbelt_escape(str(root.resolve()))}")']
            if root is not None
            else []
        ),
        *exclusions,
    ]
    if not filters:
        return f"(allow {operation})"
    if len(filters) == 1:
        return f"(allow {operation} {filters[0]})"
    return f"(allow {operation} (require-all {' '.join(filters)}))"


def _glob_to_regex(pattern: str) -> str:
    """Translate the documented ``*``/``**`` path glob subset to SBPL regex."""
    out = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == ".":
            out.append("[.]")
        elif char in "^$+(){}|[]\\":
            out.append(f"\\{char}")
        else:
            out.append(char)
        index += 1
    out.append("$")
    return "".join(out)


def _seatbelt_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
