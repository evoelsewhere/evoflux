"""Fixtures for the ``git-coding`` contract (temp repositories only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gc_helpers import Scrub, git, init_repo


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit holding ``a.txt`` and ``sub/b.txt``."""
    root = tmp_path / "repo"
    init_repo(root, **{"a.txt": "one\n"})
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("b\n", encoding="utf-8", newline="")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "second")
    # the backend runs with a temp HOME, so routes that commit need a local identity
    git(root, "config", "--local", "user.name", "t")
    git(root, "config", "--local", "user.email", "t@example.test")
    git(root, "config", "--local", "commit.gpgsign", "false")
    return root


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A plain folder that is not a repository."""
    root = tmp_path / "plain"
    root.mkdir()
    return root
