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
