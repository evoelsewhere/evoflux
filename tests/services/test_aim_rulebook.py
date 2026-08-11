from pathlib import Path

import pytest

from app.services.aim.models import AimManifest, AimRulebookRef
from app.services.aim.rulebook import (
    read_rulebook_manifest,
    resolve_rulebook_dir,
    resolve_rulebook_path,
    validate_unit_kind,
    validate_rulebook_identity,
)


def _write_rulebook(
    kb_root: Path, *, rulebook_id: str = "sample", version: str = "0.1"
):
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


def test_rulebook_manifest_rejects_unknown_fields(tmp_path: Path):
    _write_rulebook(tmp_path)
    path = tmp_path / "rulebook/rulebook.yaml"
    path.write_text("id: sample\nversion: '0.1'\nunknown_policy: true\n")

    with pytest.raises(ValueError, match="unknown_policy"):
        read_rulebook_manifest(tmp_path)


def test_rulebook_manifest_validates_stack_extensions(tmp_path: Path):
    _write_rulebook(tmp_path)
    path = tmp_path / "rulebook/rulebook.yaml"
    path.write_text(
        "id: sample\nversion: '0.1'\nsource:\n  stack: legacy\n  file_extensions: [c]\n"
    )

    with pytest.raises(ValueError, match="must start with"):
        read_rulebook_manifest(tmp_path)


def test_rulebook_unit_kinds_are_enforced(tmp_path: Path):
    _write_rulebook(tmp_path)
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: sample\nversion: '0.1'\nunit_kinds: [subsystem, component]\n"
    )
    manifest = AimManifest(rulebook=AimRulebookRef(id="sample", version="0.1"))
    from app.services.aim import kb_store

    kb_store.create_manifest(
        tmp_path,
        rulebook_id=manifest.rulebook.id,
        rulebook_version=manifest.rulebook.version,
        source_identities=[],
        target_identities=[],
    )

    validate_unit_kind(tmp_path, "subsystem")
    with pytest.raises(ValueError, match="not allowed"):
        validate_unit_kind(tmp_path, "program")


def test_rulebook_manifest_parses_assets_and_workspace_activation(tmp_path: Path):
    _write_rulebook(tmp_path)
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: sample\nversion: '0.1'\n"
        "assets: {abi: abi/c-api.md}\n"
        "workspace_activation:\n"
        "  skills: [.evoflux/skills/sqlite/SKILL.md]\n"
        "  workflows: [.evoflux/workflows/preflight.yaml]\n"
        "  commands: [.evoflux/commands/preflight.md]\n"
    )

    manifest = read_rulebook_manifest(tmp_path)

    assert manifest.assets == {"abi": "abi/c-api.md"}
    assert manifest.workspace_activation.workflows == [
        ".evoflux/workflows/preflight.yaml"
    ]


def test_rulebook_manifest_rejects_uppercase_workspace_activation(tmp_path: Path):
    _write_rulebook(tmp_path)
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: sample\nversion: '0.1'\n"
        "workspace_activation:\n"
        "  workflows: [.EvoFlux/workflows/preflight.yaml]\n"
    )

    with pytest.raises(ValueError, match=r"must be under \.evoflux/workflows/"):
        read_rulebook_manifest(tmp_path)


def test_rulebook_manifest_rejects_workspace_activation_traversal(tmp_path: Path):
    _write_rulebook(tmp_path)
    (tmp_path / "rulebook/rulebook.yaml").write_text(
        "id: sample\nversion: '0.1'\n"
        "workspace_activation:\n"
        "  workflows: [.evoflux/workflows/../../outside.yaml]\n"
    )

    with pytest.raises(ValueError, match=r"must be under \.evoflux/workflows/"):
        read_rulebook_manifest(tmp_path)
