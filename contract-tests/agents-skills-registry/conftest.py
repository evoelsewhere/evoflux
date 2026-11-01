"""Fixtures for the ``/api/agents`` and ``/api/skills`` contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from registry_helpers import Scrub


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """The backend's ``EVOFLUX_CONFIG_DIR`` (see ``backends.start_backend``)."""
    return tmp_path / "config"


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The backend's ``HOME``/``USERPROFILE``; ``~/.claude/skills`` is a skills root."""
    return tmp_path / "home"


@pytest.fixture
def agents_dir(config_dir: Path) -> Path:
    return config_dir / "agents"


@pytest.fixture
def skills_dir(config_dir: Path) -> Path:
    return config_dir / "skills"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A Git workspace with one project skill, passed as ``?workspace=``."""
    root = tmp_path / "ws"
    (root / ".git").mkdir(parents=True)
    return root
