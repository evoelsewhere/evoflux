"""Desktop user-shell and PATH discovery."""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services import user_shell


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_resolve_login_shell_uses_account_record_when_shell_env_missing(monkeypatch):
    import pwd

    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(
        pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_shell="/bin/zsh"),
    )

    assert user_shell.resolve_login_shell() == "/bin/zsh"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_interactive_terminal_uses_login_shell_flags():
    assert user_shell.interactive_login_argv("/bin/zsh") == ["/bin/zsh", "-il"]
    assert user_shell.interactive_login_argv("/bin/bash") == ["/bin/bash", "-il"]
    assert user_shell.interactive_login_argv("/bin/sh") == ["/bin/sh", "-i"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only")
def test_discover_login_path_extracts_marker_only(monkeypatch):
    user_shell._discover_login_path_cached.cache_clear()
    monkeypatch.setenv("HOME", "/Users/test")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="profile noise\n__EVOFLUX_LOGIN_PATH__=/opt/homebrew/bin:/usr/bin\n"
        ),
    )

    assert user_shell.discover_login_path("/bin/zsh") == ("/opt/homebrew/bin:/usr/bin")
    user_shell._discover_login_path_cached.cache_clear()


def test_terminal_environment_scrubs_internal_and_python_runtime(monkeypatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/bundled/site-packages")
    monkeypatch.setenv("VIRTUAL_ENV", "/bundled/venv")
    monkeypatch.setenv("PATH", os.defpath)

    env = user_shell.user_terminal_environment()

    assert env["PATH"] == os.defpath
    assert "EVOFLUX_DESKTOP_TOKEN" not in env
    assert "PYTHONPATH" not in env
    assert "VIRTUAL_ENV" not in env


def test_windows_uses_comspec_and_existing_user_path(monkeypatch):
    monkeypatch.setattr(user_shell.sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("PATH", r"C:\Program Files\nodejs;C:\Windows\System32")
    monkeypatch.setattr(
        user_shell.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Windows PATH must not spawn a profile"),
    )

    assert user_shell.resolve_login_shell() == r"C:\Windows\System32\cmd.exe"
    assert user_shell.discover_login_path() == (
        r"C:\Program Files\nodejs;C:\Windows\System32"
    )


def test_windows_terminal_environment_scrubs_keys_case_insensitively(monkeypatch):
    monkeypatch.setattr(user_shell.sys, "platform", "win32")
    monkeypatch.setenv("evoflux_desktop_token", "secret")
    monkeypatch.setenv("pythonpath", r"C:\bundled\site-packages")
    monkeypatch.setenv("Path", r"C:\Program Files\nodejs;C:\Windows\System32")

    env = user_shell.user_terminal_environment()

    assert env["Path"] == r"C:\Program Files\nodejs;C:\Windows\System32"
    assert "evoflux_desktop_token" not in env
    assert "pythonpath" not in env
