"""Start a real backend process and read its ``EVOFLUX_HANDSHAKE`` line."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Target = Literal["python", "rust", "gateway"]

REPO_ROOT = Path(__file__).resolve().parent.parent
RUST_BINARY = (
    REPO_ROOT
    / "server"
    / "target"
    / "debug"
    / ("evoflux-server.exe" if os.name == "nt" else "evoflux-server")
)
# Gateway test binary (Task 10): the gateway library in front of Python,
# located through the EVOFLUX_GATEWAY_* variables set in start_backend.
GATEWAY_HARNESS = RUST_BINARY.with_name(
    "evoflux-gateway-harness.exe" if os.name == "nt" else "evoflux-gateway-harness"
)
HANDSHAKE_PREFIX = "EVOFLUX_HANDSHAKE "
HANDSHAKE_TIMEOUT_S = 90.0
_LOG_TAIL_LINES = 200
_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
)


class BackendStartError(RuntimeError):
    pass


def wait_for_exit(pid: int, timeout_s: float = 15.0) -> None:
    """Wait for the handshake PID, not just the Windows venv launcher.

    ``taskkill /T`` returns, and the launcher exits, while the backend itself
    can still be releasing its SQLite file and WAL index handles; opening the
    database before that finishes can fail with ``disk I/O error``.
    """
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the PID no longer exists
            return
        raise ctypes.WinError(error)
    try:
        result = kernel.WaitForSingleObject(handle, int(timeout_s * 1000))
        if result != 0:  # WAIT_OBJECT_0
            raise RuntimeError(f"backend PID {pid} did not exit: wait result {result}")
    finally:
        kernel.CloseHandle(handle)


@dataclass
class Backend:
    base_url: str
    token: str
    pid: int
    process: subprocess.Popen[str]
    log: deque[str]

    def stop(self) -> None:
        if self.process.poll() is None:
            if os.name == "nt":
                # The venv launcher can own a Python child. Terminate the
                # entire tree and wait before the temp directory is removed.
                result = subprocess.run(
                    ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode and self.process.poll() is None:
                    raise RuntimeError(
                        f"backend tree termination failed: {result.stderr}"
                    )
                self.process.wait(timeout=15)
            else:
                self.process.terminate()
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
        wait_for_exit(self.pid)

    def log_tail(self) -> str:
        return "\n".join(self.log)


def _command(
    target: Target, python: str | None = None, binary: Path | None = None
) -> list[str]:
    serve_flags = [
        "--handshake",
        "--generate-token",
        "--port",
        "0",
    ]
    # Python v3's Windows parent watcher calls os.kill(pid, 0), which sends a
    # console control event instead of checking process existence. It can
    # interrupt pytest. Windows cleanup is performed by Backend.stop instead.
    if not (os.name == "nt" and target == "python"):
        serve_flags.extend(["--parent-pid", str(os.getpid())])
    if target == "python":
        return [python or sys.executable, "-m", "app.cli", "serve", *serve_flags]
    # rust and gateway are the same binary; routing.toml decides which one runs.
    # EVOFLUX_CONTRACT_SERVER_BIN (or ``binary``) substitutes a test binary.
    override = os.environ.get("EVOFLUX_CONTRACT_SERVER_BIN")
    server = binary or (Path(override) if override else RUST_BINARY)
    if not server.exists():
        raise BackendStartError(
            f"TARGET={target} needs {server}; it is built by Phase 0 task 11."
        )
    return [str(server), "serve", *serve_flags]


def start_backend(
    target: Target,
    data_dir: Path,
    db_fixture: Path | None = None,
    *,
    source_root: Path | None = None,
    python: str | None = None,
    binary: Path | None = None,
    extra_env: dict[str, str] | None = None,
    config_fixture: Path | None = None,
) -> Backend:
    """Start ``target`` with fresh data/config/state/cache dirs under ``data_dir``.

    ``db_fixture`` is copied to ``<data>/evoflux.db`` before launch.
    ``source_root`` and ``python`` run the Python target from another checkout
    (the upgrade fixture builder starts each v3.x tag this way); they default
    to this repository and the current interpreter. ``binary`` replaces the
    Rust server binary; ``extra_env`` is added last.
    """
    dirs = {
        "EVOFLUX_DATA_DIR": data_dir / "data",
        "EVOFLUX_CONFIG_DIR": data_dir / "config",
        "EVOFLUX_STATE_DIR": data_dir / "state",
        "EVOFLUX_CACHE_DIR": data_dir / "cache",
        "EVOFLUX_WORKSPACE_DIR": data_dir / "workspace",
        "EVOFLUX_WIKI_DIR": data_dir / "wiki",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    if config_fixture is not None:
        shutil.copytree(config_fixture, dirs["EVOFLUX_CONFIG_DIR"], dirs_exist_ok=True)
    if db_fixture is not None:
        shutil.copyfile(db_fixture, dirs["EVOFLUX_DATA_DIR"] / "evoflux.db")

    # Allow-list, not "everything but EVOFLUX_*": DATABASE_URL, provider keys,
    # XDG_* and the like must not reach the backend. HOME and the app-data dirs
    # point into the temp dir so ~/.config/evoflux/.env and user skills are not
    # read, and cwd is the temp dir so the repo's .env is not either.
    home = data_dir / "home"
    cwd = data_dir / "cwd"
    home.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "PYTHONPATH": str(source_root or REPO_ROOT),
        }
    )
    env.update({k: str(v) for k, v in dirs.items()})
    env["EVOFLUX_MODEL_REGISTRY_REFRESH"] = "false"
    env["APP_ENV"] = "production"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if target != "python":
        # Where the gateway test binary finds the Python sidecar (dev layout).
        root = source_root or REPO_ROOT
        env["EVOFLUX_GATEWAY_PYTHON_BIN"] = python or sys.executable
        env["EVOFLUX_GATEWAY_SITE_PACKAGES"] = str(root)
        env["EVOFLUX_GATEWAY_CLI_ENTRY"] = str(root / "app" / "cli" / "__main__.py")
    env.update(extra_env or {})

    process = subprocess.Popen(
        _command(target, python, binary),
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    log: deque[str] = deque(maxlen=_LOG_TAIL_LINES)
    handshakes: queue.Queue[dict | None] = queue.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip("\r\n")
            log.append(line)
            if line.startswith(HANDSHAKE_PREFIX):
                handshakes.put(json.loads(line[len(HANDSHAKE_PREFIX) :]))
        handshakes.put(None)

    threading.Thread(target=pump, name="backend-log", daemon=True).start()
    try:
        info = handshakes.get(timeout=HANDSHAKE_TIMEOUT_S)
    except queue.Empty:
        info = None
    if info is None:
        Backend("", "", process.pid, process, log).stop()
        raise BackendStartError(
            f"{target} backend gave no handshake:\n" + "\n".join(log)
        )
    return Backend(
        base_url=f"http://127.0.0.1:{info['port']}",
        token=info["token"],
        pid=int(info["pid"]),
        process=process,
        log=log,
    )
