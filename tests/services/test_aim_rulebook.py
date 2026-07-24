from pathlib import Path

import pytest

from app.services.aim.models import AimManifest, AimRulebookRef
from app.services.aim.rulebook import (
    read_rulebook_manifest,
    resolve_rulebook_dir,
    resolve_rulebook_path,
    validate_rulebook_identity,
)


def _write_rulebook(kb_root: Path, *, rulebook_id: str = "sample", version: str = "0.1"):
    directory = kb_root / "rulebook"
    directory.mkdir(parents=True)
    (directory / "rulebook.yaml").write_text(
        f"id: {rulebook_id}\nversion: '{version}'\ncapabilities: {{}}\n",
        encoding="utf-8",
    )


def test_rulebook_resolves_only_from_kb(tmp_path: Path):
    _write_rulebook(tmp_path)

    resolved = resolve_rulebook_dir(tmp_path)

    assert resolved == tmp_path / "rulebook"
    assert read_rulebook_manifest(tmp_path).id == "sample"


def test_rulebook_manifest_is_required(tmp_path: Path):
    (tmp_path / "rulebook").mkdir()

    with pytest.raises(FileNotFoundError, match="rulebook manifest is missing"):
        resolve_rulebook_dir(tmp_path)


def test_rulebook_identity_must_match_aim_manifest(tmp_path: Path):
    _write_rulebook(tmp_path, rulebook_id="local", version="1")
    manifest = AimManifest(rulebook=AimRulebookRef(id="other", version="1"))

    with pytest.raises(ValueError, match="identity mismatch"):
        validate_rulebook_identity(tmp_path, manifest)


def test_rulebook_declared_paths_cannot_escape_kb_rulebook(tmp_path: Path):
    _write_rulebook(tmp_path)

    with pytest.raises(ValueError, match="escapes rulebook directory"):
        resolve_rulebook_path(tmp_path, "../outside.sh")