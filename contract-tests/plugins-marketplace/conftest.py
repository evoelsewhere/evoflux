"""Fixtures for the ``/api/plugins`` contract."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from plugin_helpers import PYTHON_NAME, Scrub


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def platform_dir(tmp_path: Path) -> Path:
    """``<EVOFLUX_DATA_DIR>/agent-plugins``: registry, installs, data, marketplaces."""
    return tmp_path / "data" / "agent-plugins"


@pytest.fixture
def staging_dir(tmp_path: Path) -> Path:
    """``<EVOFLUX_CACHE_DIR>/agent-plugins/staging``."""
    return tmp_path / "cache" / "agent-plugins" / "staging"


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """Where tests build plugin source folders (outside every backend directory)."""
    root = tmp_path / "src"
    root.mkdir()
    return root


@pytest.fixture
def needs_python_on_path() -> None:
    if shutil.which(PYTHON_NAME) is None:
        pytest.skip(f"{PYTHON_NAME} is not on PATH for the backend")
