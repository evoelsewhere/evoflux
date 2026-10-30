"""Committed fixture data for the contract suite."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

UPGRADE_DIR = Path(__file__).resolve().parent / "upgrade"
TAGS = [f"v3.0.{n}" for n in range(11)] + ["v3.1.0", "v3.1.1"]


def upgrade_manifest(tag: str) -> dict:
    return json.loads((UPGRADE_DIR / tag / "MANIFEST.json").read_text(encoding="utf-8"))


def upgrade_fixture(tag: str) -> Path:
    """Copy ``<tag>``'s database into a fresh temp dir and return the copy's path."""
    source = UPGRADE_DIR / tag / "evoflux.db"
    if not source.is_file():
        raise FileNotFoundError(
            f"{source} is missing; run contract-tests/fixtures/build_upgrade_fixtures.py"
        )
    target = Path(tempfile.mkdtemp(prefix=f"evoflux-upgrade-{tag}-")) / "evoflux.db"
    shutil.copyfile(source, target)
    return target
