from __future__ import annotations

import os
from pathlib import Path

from app.core import officecli


def test_officecli_bin_dir_none_when_not_bundled_and_no_override(monkeypatch, tmp_path):
    monkeypatch.delenv("EVOFLUX_OFFICECLI_DIR", raising=False)
    # A bare python.exe with no sibling bin/ dir looks like a normal dev venv,
    # not a sidecar bundle.
    fake_exe = tmp_path / "python" / "python.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("")
    monkeypatch.setattr(officecli.sys, "executable", str(fake_exe))
    monkeypatch.setattr(officecli.sys, "platform", "win32")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli.exe")

    assert officecli.officecli_bin_dir() is None


def test_officecli_bin_dir_finds_bundled_binary_windows_layout(monkeypatch, tmp_path):
    """Windows layout: <bundle>/python/python.exe, <bundle>/bin/officecli.exe."""
    monkeypatch.delenv("EVOFLUX_OFFICECLI_DIR", raising=False)
    bundle = tmp_path / "sidecar-bundle"
    python_exe = bundle / "python" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("")
    bin_dir = bundle / "bin"
    bin_dir.mkdir()
    (bin_dir / "officecli.exe").write_text("")

    monkeypatch.setattr(officecli.sys, "executable", str(python_exe))
    monkeypatch.setattr(officecli.sys, "platform", "win32")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli.exe")

    assert officecli.officecli_bin_dir() == bin_dir


def test_officecli_bin_dir_finds_bundled_binary_unix_layout(monkeypatch, tmp_path):
    """Unix layout: <bundle>/python/bin/python3.12, <bundle>/bin/officecli."""
    monkeypatch.delenv("EVOFLUX_OFFICECLI_DIR", raising=False)
    bundle = tmp_path / "sidecar-bundle"
    python_bin = bundle / "python" / "bin" / "python3.12"
    python_bin.parent.mkdir(parents=True)
    python_bin.write_text("")
    bin_dir = bundle / "bin"
    bin_dir.mkdir()
    (bin_dir / "officecli").write_text("")

    monkeypatch.setattr(officecli.sys, "executable", str(python_bin))
    monkeypatch.setattr(officecli.sys, "platform", "linux")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")

    assert officecli.officecli_bin_dir() == bin_dir


def test_officecli_bin_dir_override_env_var(monkeypatch, tmp_path):
    custom = tmp_path / "custom-officecli"
    custom.mkdir()
    (custom / "officecli").write_text("")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setenv("EVOFLUX_OFFICECLI_DIR", str(custom))

    assert officecli.officecli_bin_dir() == custom


def test_officecli_bin_dir_override_env_var_missing_binary(monkeypatch, tmp_path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setenv("EVOFLUX_OFFICECLI_DIR", str(empty_dir))

    assert officecli.officecli_bin_dir() is None


def test_ensure_officecli_on_path_prepends_dir(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "officecli").write_text("")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setenv("EVOFLUX_OFFICECLI_DIR", str(bin_dir))
    monkeypatch.setenv("PATH", f"/usr/bin{os.pathsep}/bin")

    officecli.ensure_officecli_on_path()

    entries = os.environ["PATH"].split(os.pathsep)
    assert entries[0] == str(bin_dir)
    assert "/usr/bin" in entries


def test_ensure_officecli_on_path_idempotent(monkeypatch, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "officecli").write_text("")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setenv("EVOFLUX_OFFICECLI_DIR", str(bin_dir))
    monkeypatch.setenv("PATH", "/usr/bin")

    officecli.ensure_officecli_on_path()
    officecli.ensure_officecli_on_path()

    assert os.environ["PATH"].split(os.pathsep).count(str(bin_dir)) == 1


def test_ensure_officecli_on_path_noop_when_not_found(monkeypatch, tmp_path):
    monkeypatch.delenv("EVOFLUX_OFFICECLI_DIR", raising=False)
    fake_exe = tmp_path / "python" / "python.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("")
    monkeypatch.setattr(officecli.sys, "executable", str(fake_exe))
    monkeypatch.setattr(officecli.sys, "platform", "win32")
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli.exe")
    monkeypatch.setenv("PATH", "/usr/bin")

    officecli.ensure_officecli_on_path()

    assert os.environ["PATH"] == "/usr/bin"


# ── warm_up_officecli ──────────────────────────────────────────────────────────


class _SyncThread:
    """Test double for threading.Thread that runs the target inline."""

    def __init__(self, target=None, args=(), **_kwargs):
        self._target = target
        self._args = args

    def start(self):
        self._target(*self._args)


def _fake_binary(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "officecli").write_text("")
    return bin_dir


def test_warm_up_noop_when_no_binary(monkeypatch):
    monkeypatch.setattr(officecli, "officecli_bin_dir", lambda: None)
    spawned = []

    class _RecordingThread:
        def __init__(self, *args, **kwargs):
            spawned.append((args, kwargs))

        def start(self):  # pragma: no cover — must never run
            raise AssertionError("no thread should start without a binary")

    monkeypatch.setattr(officecli.threading, "Thread", _RecordingThread)

    officecli.warm_up_officecli()

    assert spawned == []


def test_warm_up_invokes_version_when_binary_present(monkeypatch, tmp_path):
    bin_dir = _fake_binary(tmp_path)
    monkeypatch.setattr(officecli, "officecli_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setattr(officecli.threading, "Thread", _SyncThread)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return officecli.subprocess.CompletedProcess(
            argv, 0, stdout="officecli 0.9.1\n", stderr=""
        )

    monkeypatch.setattr(officecli.subprocess, "run", fake_run)

    officecli.warm_up_officecli()

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [str(bin_dir / "officecli"), "--version"]
    assert kwargs["timeout"] == 180
    assert kwargs["capture_output"] is True
    assert kwargs["creationflags"] == 0  # no-op default off Windows


def test_warm_up_uses_create_no_window_on_windows(monkeypatch, tmp_path):
    bin_dir = _fake_binary(tmp_path)
    monkeypatch.setattr(officecli, "officecli_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setattr(officecli.threading, "Thread", _SyncThread)
    monkeypatch.setattr(officecli.sys, "platform", "win32")
    monkeypatch.setattr(
        officecli.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return officecli.subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(officecli.subprocess, "run", fake_run)

    officecli.warm_up_officecli()

    assert calls[0][1]["creationflags"] == 0x08000000


def test_warm_up_swallows_failures(monkeypatch, tmp_path):
    bin_dir = _fake_binary(tmp_path)
    monkeypatch.setattr(officecli, "officecli_bin_dir", lambda: bin_dir)
    monkeypatch.setattr(officecli, "_BIN_NAME", "officecli")
    monkeypatch.setattr(officecli.threading, "Thread", _SyncThread)

    def boom(argv, **kwargs):
        raise OSError("cannot execute binary file")

    monkeypatch.setattr(officecli.subprocess, "run", boom)

    officecli.warm_up_officecli()  # must not raise
