"""Tests for app/agent/tools/builtin/shell_runtime.py."""

from __future__ import annotations

import sys

import pytest

from app.agent.tools.builtin import shell_runtime

_IS_WINDOWS = sys.platform == "win32"


@pytest.fixture(autouse=True)
def _reset_cache():
    shell_runtime.reset_cache()
    yield
    shell_runtime.reset_cache()


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
def test_build_argv_zsh_uses_login_and_sources_rc_files():
    """zsh argv passes -l, sources ~/.zshenv and ~/.zshrc, and evals the command."""
    argv = shell_runtime.build_argv("/bin/zsh", "echo hi")

    assert argv[0] == "-l"
    assert argv[1] == "-c"
    wrapper = argv[2]
    assert "~/.zshenv" in wrapper
    assert ".zshrc" in wrapper
    assert 'eval "$1"' in wrapper
    # argv[3] is $0, argv[4] is $1 — the user's command
    assert argv[3] == "EvoFlux"
    assert argv[4] == "echo hi"


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
def test_build_argv_bash_uses_login_and_sources_bashrc():
    """bash argv passes -l, enables alias expansion, sources ~/.bashrc."""
    argv = shell_runtime.build_argv("/bin/bash", "ls -la")

    assert argv[0] == "-l"
    assert argv[1] == "-c"
    wrapper = argv[2]
    assert "shopt -s expand_aliases" in wrapper
    assert "~/.bashrc" in wrapper
    assert 'eval "$1"' in wrapper
    assert argv[3] == "EvoFlux"
    assert argv[4] == "ls -la"


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
@pytest.mark.parametrize("shell", ["/bin/zsh", "/bin/bash"])
def test_build_argv_can_disable_user_profiles(shell: str):
    argv = shell_runtime.build_argv(shell, "echo safe", load_profile=False)

    assert argv == ["-c", "echo safe"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
def test_build_argv_sh_uses_bare_c():
    """Plain POSIX sh has no rc file convention — bare -c is correct."""
    argv = shell_runtime.build_argv("/bin/sh", "echo hi")
    assert argv == ["-c", "echo hi"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
def test_build_argv_dash_uses_bare_c():
    argv = shell_runtime.build_argv("/usr/bin/dash", "echo hi")
    assert argv == ["-c", "echo hi"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX-only")
def test_build_argv_preserves_command_quoting_unchanged():
    """The command is passed as a single argv element — quoting is the shell's job via eval."""
    cmd = """echo 'hello world' && echo "$HOME" """
    argv = shell_runtime.build_argv("/bin/zsh", cmd)
    assert argv[-1] == cmd


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only")
def test_build_argv_cmd_uses_slash_c():
    """cmd.exe uses /c to run a command."""
    argv = shell_runtime.build_argv("cmd.exe", "echo hi")
    assert argv == ["/c", "echo hi"]


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only")
def test_build_argv_powershell_uses_command_flag():
    """PowerShell uses -NoProfile -NonInteractive -Command."""
    argv = shell_runtime.build_argv("powershell.exe", "echo hi")
    assert argv[0] == "-NoProfile"
    assert argv[1] == "-NonInteractive"
    assert argv[2] == "-Command"
    assert argv[3] == "echo hi"


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only")
def test_windows_acceptable_returns_valid_shell():
    """On Windows, acceptable() should return a valid shell path."""
    result = shell_runtime.acceptable()
    assert isinstance(result, str)
    assert len(result) > 0
    name = shell_runtime.name(result)
    assert name in {"cmd", "powershell", "pwsh"}


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only")
def test_windows_is_windows_true():
    assert shell_runtime.is_windows("cmd.exe")
    assert shell_runtime.is_windows("powershell.exe")
    assert not shell_runtime.is_windows("/bin/sh")


@pytest.mark.skipif(not _IS_WINDOWS, reason="Windows-only")
def test_windows_is_posix_false():
    assert not shell_runtime.is_posix("cmd.exe")
    assert not shell_runtime.is_posix("powershell.exe")
