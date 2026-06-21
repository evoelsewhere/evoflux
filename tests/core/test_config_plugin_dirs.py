"""Regression tests for ``Settings.plugin_dirs``.

The historic implementation split ``EVOFLUX_PLUGINS_DIRS`` on a literal
``":"``.  On Windows that turns paths like ``C:\\Users\\me\\plugins`` into
``["C", "\\Users\\me\\plugins"]``, and the first entry — the bare string
``"C"`` — crashes ``ensure_workspace_initialized`` at backend startup with
``PermissionError: [WinError 5] Access is denied: 'C'``.  We now split on
:data:`os.pathsep` instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import settings


def test_plugin_dirs_uses_os_pathsep(monkeypatch: pytest.MonkeyPatch) -> None:
    a = "/tmp/plugins-a"
    b = "/tmp/plugins-b"
    monkeypatch.setattr(settings, "EVOFLUX_PLUGINS_DIRS", os.pathsep.join([a, b]))

    assert settings.plugin_dirs() == [Path(a), Path(b)]


def test_plugin_dirs_uses_semicolon_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.core.config.os.pathsep", ";")
    monkeypatch.setattr(
        settings,
        "EVOFLUX_PLUGINS_DIRS",
        r"C:\a;D:\b",
    )

    dirs = settings.plugin_dirs()

    assert [str(p) for p in dirs] == [r"C:\a", r"D:\b"]


def test_plugin_dirs_preserves_windows_drive_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, ``os.pathsep`` is ``;``.  Splitting on ``:`` would corrupt
    a drive-lettered path and make the first entry the bare string ``"C"``,
    which crashes :func:`ensure_workspace_initialized` at startup.

    Force ``os.pathsep = ";"`` so this test catches the Windows regression on
    POSIX CI runners too.
    """
    monkeypatch.setattr("app.core.config.os.pathsep", ";")
    monkeypatch.setattr(
        settings,
        "EVOFLUX_PLUGINS_DIRS",
        r"C:\Users\me\.config\EvoFlux\plugins",
    )

    dirs = settings.plugin_dirs()

    assert len(dirs) == 1
    # The entry must keep the drive letter and must NOT be the lone string "C".
    assert str(dirs[0]) != "C"
    assert "Users" in str(dirs[0])


def test_plugin_dirs_drops_empty_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "EVOFLUX_PLUGINS_DIRS",
        os.pathsep.join(["", "/tmp/plugins", "   "]),
    )

    assert settings.plugin_dirs() == [Path("/tmp/plugins")]
