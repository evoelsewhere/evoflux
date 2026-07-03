"""PID file helpers: write/read/find running EvoFlux processes."""

from __future__ import annotations

import os

from app.cli.paths import _pid_file


def _write_pids(pids: list[int]) -> None:
    pid_file = _pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("\n".join(str(p) for p in pids))


def _read_pids() -> list[int]:
    pid_file = _pid_file()
    if not pid_file.exists():
        return []
    try:
        return [int(line) for line in pid_file.read_text().splitlines() if line.strip()]
    except ValueError:
        return []


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _find_pids() -> list[int]:
    """Find running PIDs, filtered to those still alive."""
    pids = _read_pids()
    if pids and any(_pid_alive(p) for p in pids):
        return pids
    return []


def _clear_pids() -> None:
    _pid_file().unlink(missing_ok=True)
