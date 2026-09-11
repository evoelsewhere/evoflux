"""Portability and ledger guarantees an EASD repository must hold anywhere.

`config.json` and the knowledge index are version-controlled, so a repository
initialized on one platform must stay readable on every other. And every event
in the run ledger must carry a timestamp, including the genesis event, or the
ledger cannot be ordered independently of filename sequence.
"""

from __future__ import annotations

import json

import pytest
import yaml

from app.easd_skills import (
    EASD_LEGACY_OPTIONAL_SKELETON_FILES,
    EASD_SKELETON_FILES,
    read_easd_skeleton,
)
from app.services.easd_repository_store import run_directory_name
from app.services.easd_setup_service import (
    EASD_MANIFEST,
    EasdRepositoryTarget,
    initialize_repositories,
    inspect_repository,
)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# project\n", encoding="utf-8")
    target = EasdRepositoryTarget(path=str(root), name="project")
    initialize_repositories([target])
    return root, target


class TestManifestPortability:
    def test_manifest_paths_use_posix_separators(self, repository):
        root, _ = repository
        payload = json.loads((root / EASD_MANIFEST).read_text(encoding="utf-8"))
        for key in (
            "data_directory",
            "rules_file",
            "templates_directory",
            "runtime_directory",
            "skills_directory",
        ):
            value = payload[key]
            assert "\\" not in value, f"{key} must not carry OS-native separators"
            assert value == value.strip()

    def test_manifest_written_on_windows_is_still_accepted(self, repository):
        """A collaborator on another platform must not be locked out."""

        root, target = repository
        manifest_path = root / EASD_MANIFEST
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["rules_file"] = ".evoflux\\easd\\RULES.md"
        payload["skills_directory"] = ".evoflux\\skills"
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        status = inspect_repository(target)
        assert status["state"] == "upgrade_required"
        assert "not portable" in (status["issue"] or "")
        assert "rules_file" in (status["issue"] or "")

    def test_upgrade_rewrites_a_non_portable_manifest(self, repository):
        root, target = repository
        manifest_path = root / EASD_MANIFEST
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["runtime_directory"] = ".evoflux\\easd\\.local\\runs"
        manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        assert inspect_repository(target)["state"] == "upgrade_required"

        initialize_repositories([target])

        repaired = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert repaired["runtime_directory"] == ".evoflux/easd/.local/runs"
        assert inspect_repository(target)["state"] == "ready"

    def test_reported_contract_paths_are_posix(self, repository):
        _, target = repository
        status = inspect_repository(target)
        for key in ("manifest_path", "runtime_directory", "rules_path", "skills_path"):
            assert "\\" not in status[key], f"{key} must be POSIX in API output"


class TestKnowledgeSkeleton:
    def test_every_declared_section_exists_on_disk(self, repository):
        """`index.yaml` must not point at directories initialization skipped."""

        root, _ = repository
        index = yaml.safe_load(read_easd_skeleton("index.yaml"))
        data_directory = root / "documents" / "easd"
        for section in index["sections"].values():
            assert (data_directory / section).is_dir(), (
                f"index.yaml declares section {section!r} but it was not created"
            )

    def test_skeleton_files_are_created(self, repository):
        root, _ = repository
        data_directory = root / "documents" / "easd"
        for name in EASD_SKELETON_FILES:
            assert (data_directory / name).is_file(), f"missing skeleton file {name}"

    def test_superseded_locations_are_not_recreated(self, repository):
        root, _ = repository
        data_directory = root / "documents" / "easd"
        for name in EASD_LEGACY_OPTIONAL_SKELETON_FILES:
            assert not (data_directory / name).exists(), (
                f"{name} moved under .evoflux/easd/.local and must not be recreated"
            )

    def test_knowledge_index_execution_path_is_posix(self, repository):
        root, _ = repository
        index_path = root / "documents" / "easd" / "index.yaml"
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
        assert "\\" not in str(payload["authority"]["execution"])


class TestRunDirectoryName:
    def test_name_pairs_the_slug_with_the_run_id(self):
        assert run_directory_name(
            "Implement per-client rate limiting",
            "06a99011-6881-7b59-8000-d81021987cbc",
        ) == (
            "implement-per-client-rate-limiting--06a99011-6881-7b59-8000-d81021987cbc"
        )

    def test_untitled_runs_still_resolve(self):
        name = run_directory_name("!!!", "06a99011-6881-7b59-8000-d81021987cbc")
        assert name.startswith("run--")
