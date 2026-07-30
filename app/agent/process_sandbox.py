"""Native process sandbox wrappers used by shell-like tools."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from loguru import logger

from app.agent.sandbox import SandboxConfig, _allowed_internal_roots


def sandboxed_process_argv(
    executable: str,
    args: list[str],
    *,
    sandbox: SandboxConfig,
    cwd: Path,
) -> tuple[str, list[str]]:
    """Wrap a process with the strongest native sandbox available.

    macOS uses Seatbelt via ``sandbox-exec``. Linux uses Bubblewrap when
    installed. Other hosts keep the application-level allowlist and emit an
    explicit warning instead of pretending OS containment exists.
    """
    if sys.platform == "darwin":
        sandbox_exec = shutil.which("sandbox-exec")
        if sandbox_exec:
            profile = _macos_profile(sandbox)
            return sandbox_exec, ["-p", profile, executable, *args]

    if sys.platform.startswith("linux"):
        bwrap = shutil.which("bwrap")
        if bwrap:
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
    roots.extend(_allowed_internal_roots(sandbox.session_id))
    return list(dict.fromkeys(path.resolve() for path in roots))


def _macos_profile(sandbox: SandboxConfig) -> str:
    writable = " ".join(
        f'(subpath "{_seatbelt_escape(str(root))}")'
        for root in [*_writable_roots(sandbox), Path("/private/tmp"), Path("/tmp")]
    )
    network_rule = "(allow network*)" if sandbox.allow_network else "(deny network*)"
    return " ".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow file-read*)",
            f"(allow file-write* {writable})",
            "(allow sysctl-read)",
            "(allow mach-lookup)",
            "(allow ipc-posix-shm)",
            network_rule,
        ]
    )


def _seatbelt_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
