"""Tests for app/agent/tools/builtin/shell_runtime.py."""

from __future__ import annotations

import pytest

from app.agent.tools.builtin import shell_runtime


@pytest.fixture(autouse=True)
def _reset_cache():
    shell_runtime.reset_cache()
    yield
    shell_runtime.reset_cache()


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


def test_build_argv_sh_uses_bare_c():
    """Plain POSIX sh has no rc file convention — bare -c is correct."""
    argv = shell_runtime.build_argv("/bin/sh", "echo hi")
    assert argv == ["-c", "echo hi"]


def test_build_argv_dash_uses_bare_c():
    argv = shell_runtime.build_argv("/usr/bin/dash", "echo hi")
    assert argv == ["-c", "echo hi"]


def test_build_argv_preserves_command_quoting_unchanged():
    """The command is passed as a single argv element — quoting is the shell's job via eval."""
    cmd = """echo 'hello world' && echo "$HOME" """
    argv = shell_runtime.build_argv("/bin/zsh", cmd)
    assert argv[-1] == cmd
