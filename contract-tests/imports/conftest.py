"""Fixtures for the ``/api/import`` contract; builders live in ``import_sources``."""

from __future__ import annotations

from pathlib import Path

import pytest

from import_sources import Scrub


@pytest.fixture
def scrub(tmp_path: Path) -> Scrub:
    return Scrub(tmp_path)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """The backend's ``HOME``/``USERPROFILE`` (see ``backends.start_backend``)."""
    return tmp_path / "home"


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    return tmp_path / "wiki"
