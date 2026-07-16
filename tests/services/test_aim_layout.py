"""AIM folder-layout convention detection (app/services/aim/layout.py).

Convention: <project_name>/{aim_source_base/<repos...>,
aim_<project_name>_document, aim_target_source} — picking the root folder
auto-detects every role.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.aim.layout import (
    detect_aim_layout,
    document_repo_name,
)


def _make_layout(
    tmp_path: Path,
    *,
    root_name: str = "core-batch",
    project_name: str | None = None,
    sources: tuple[str, ...] = ("repo-a", "repo-b"),
) -> Path:
    project_name = project_name or root_name
    root = tmp_path / root_name
    for source in sources:
        (root / "aim_source_base" / source).mkdir(parents=True)
    (root / document_repo_name(project_name)).mkdir(parents=True)
    (root / "aim_target_source").mkdir(parents=True)
    return root


def test_detects_conventional_layout(tmp_path):
    root = _make_layout(tmp_path)

    detection = detect_aim_layout(root)

    assert detection.project_name == "core-batch"
    assert detection.kb_path == str(root / "aim_core-batch_document")
    assert detection.target_path == str(root / "aim_target_source")
    assert [Path(p).name for p in detection.source_paths] == ["repo-a", "repo-b"]
    assert detection.has_manifest is False
    assert detection.warnings == []


def test_project_name_comes_from_document_repo_with_warning_on_mismatch(tmp_path):
    root = _make_layout(tmp_path, root_name="checkout-dir", project_name="core-batch")

    detection = detect_aim_layout(root)

    assert detection.project_name == "core-batch"
    assert any("checkout-dir" in warning for warning in detection.warnings)


def test_hidden_dirs_in_source_base_are_ignored(tmp_path):
    root = _make_layout(tmp_path)
    (root / "aim_source_base" / ".git").mkdir()
    (root / "aim_source_base" / "notes.txt").write_text("x", encoding="utf-8")

    detection = detect_aim_layout(root)

    assert [Path(p).name for p in detection.source_paths] == ["repo-a", "repo-b"]


def test_missing_source_base_rejected(tmp_path):
    root = tmp_path / "core-batch"
    (root / document_repo_name("core-batch")).mkdir(parents=True)
    (root / "aim_target_source").mkdir(parents=True)

    with pytest.raises(ValueError, match="aim_source_base"):
        detect_aim_layout(root)


def test_empty_source_base_rejected(tmp_path):
    root = _make_layout(tmp_path, sources=())
    (root / "aim_source_base").mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="no child repositories"):
        detect_aim_layout(root)


def test_missing_document_repo_rejected(tmp_path):
    root = tmp_path / "core-batch"
    (root / "aim_source_base" / "repo-a").mkdir(parents=True)
    (root / "aim_target_source").mkdir(parents=True)

    with pytest.raises(ValueError, match="document"):
        detect_aim_layout(root)


def test_multiple_document_repos_rejected(tmp_path):
    root = _make_layout(tmp_path)
    (root / "aim_other_document").mkdir()

    with pytest.raises(ValueError, match="exactly one"):
        detect_aim_layout(root)


def test_missing_target_rejected(tmp_path):
    root = tmp_path / "core-batch"
    (root / "aim_source_base" / "repo-a").mkdir(parents=True)
    (root / document_repo_name("core-batch")).mkdir(parents=True)

    with pytest.raises(ValueError, match="aim_target_source"):
        detect_aim_layout(root)


def test_non_directory_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a directory"):
        detect_aim_layout(tmp_path / "does-not-exist")


def test_manifest_detection_and_identity_auto_map(tmp_path):
    from app.services.aim.kb_store import create_manifest, scaffold_kb_from_template

    root = _make_layout(tmp_path, sources=("repo-a",))
    kb = root / document_repo_name("core-batch")
    scaffold_kb_from_template(kb)
    # Identities for non-git dirs are directory basenames — matching the
    # detected repo names exactly, so the auto-map fills itself in. One
    # extra identity has no local counterpart and must map to None.
    create_manifest(
        kb,
        rulebook_id="cobol-java21",
        rulebook_version="0.1",
        source_identities=["repo-a", "repo-elsewhere"],
        target_identities=["aim_target_source"],
    )

    detection = detect_aim_layout(root)

    assert detection.has_manifest is True
    assert detection.source_identity_map == {
        "repo-a": str(root / "aim_source_base" / "repo-a"),
        "repo-elsewhere": None,
    }
    assert detection.target_identity_map == {
        "aim_target_source": str(root / "aim_target_source")
    }
    assert any("repo-elsewhere" in warning for warning in detection.warnings)
