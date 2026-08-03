"""Tests for app/cli/pids.py — PID liveness probing across platforms.

The Windows probe goes through ``OpenProcess``/``GetExitCodeProcess`` with a
32-bit ``DWORD`` pid, so out-of-range values must be rejected before they
reach ctypes (which truncates silently) or ``os.kill`` (which raises
``OverflowError``, an exception ``cmd_stop`` does not catch).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import pytest

from app.cli.pids import _MAX_PID, _pid_alive, _write_pids


class TestPidRangeGuards:
    def test_non_positive_pids_are_dead(self) -> None:
        assert _pid_alive(0) is False
        assert _pid_alive(-1) is False

    def test_pid_above_dword_range_is_dead(self) -> None:
        """A pid wider than a DWORD must not alias onto a live process.

        ``ctypes`` truncates ``wintypes.DWORD`` arguments modulo 2**32, so
        ``os.getpid() + 2**32`` would probe this very process and report
        ``True``. POSIX raises ``OverflowError`` from ``os.kill`` instead.
        Both are wrong: the pid does not exist.
        """
        assert _pid_alive(os.getpid() + 2**32) is False

    def test_max_dword_pid_is_in_range_but_dead(self) -> None:
        assert _pid_alive(_MAX_PID) is False
        assert _pid_alive(_MAX_PID + 1) is False


class TestPidAliveLiveProcesses:
    def test_current_process_is_alive(self) -> None:
        assert _pid_alive(os.getpid()) is True

    def test_live_child_is_alive_and_exited_child_is_dead(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.2)
            assert _pid_alive(proc.pid) is True
        finally:
            proc.terminate()
            proc.wait(timeout=10)
        time.sleep(0.2)
        assert _pid_alive(proc.pid) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 OpenProcess semantics")
class TestWindowsPidProbe:
    def test_aliased_child_pid_is_not_reported_alive(self) -> None:
        """``child.pid + 2**32`` must not be confused with ``child.pid``."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            time.sleep(0.2)
            assert _pid_alive(proc.pid) is True
            assert _pid_alive(proc.pid + 2**32) is False
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_access_denied_process_is_reported_alive(self) -> None:
        """The System process (pid 4) always exists and always denies access.

        ``OpenProcess`` fails with ``ERROR_ACCESS_DENIED`` for it even with
        ``PROCESS_QUERY_LIMITED_INFORMATION``, so the probe must fall back to
        "alive" rather than declaring every protected process dead.
        """
        assert _pid_alive(4) is True


class TestStopWithCorruptPidFile:
    @pytest.mark.parametrize(
        "content",
        [
            "",
            "\n\n  \n",
            "not-a-pid\n",
            "0\n",
            "-1\n",
            "999999",
        ],
    )
    def test_stop_reports_not_running(
        self, content: str, tmp_path, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("EVOFLUX_STATE_DIR", str(tmp_path))
        from app.cli.commands.stop import cmd_stop
        from app.cli.paths import _pid_file

        pid_file = _pid_file()
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(content)

        cmd_stop(argparse.Namespace())

        assert "not running" in capsys.readouterr().out

    def test_stop_survives_out_of_range_pid(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        """An oversized pid must not reach ``os.kill``.

        ``os.kill`` raises ``OverflowError`` (not ``OSError``) for pids wider
        than a C ``long``, which would escape ``cmd_stop``'s handler and leave
        the stale pid file in place forever.
        """
        monkeypatch.setenv("EVOFLUX_STATE_DIR", str(tmp_path))
        from app.cli.commands.stop import cmd_stop

        _write_pids([2**32 + 5])

        cmd_stop(argparse.Namespace())

        assert "not running" in capsys.readouterr().out
