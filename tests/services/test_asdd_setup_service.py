from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.asdd_skills import ASDD_SKELETON_FILES, ASDD_SKILL_NAMES
from app.services.asdd_setup_service import (
    ASDD_GITIGNORE,
    ASDD_MANIFEST,
    ASDD_RULES,
    ASDD_SKILLS_DIRECTORY,
    DEFAULT_ASDD_DATA_DIRECTORY,
    METHODOLOGY,
    METHODOLOGY_NAME,
    PRODUCT_NAME,
    AsddRepositoryTarget,
    AsddSetupConflict,
    initialize_repositories,
    inspect_repository,
    resolve_data_directory,
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def target(root: Path) -> AsddRepositoryTarget:
    return AsddRepositoryTarget(path=str(root), name="repo", display_name="Repo")


def initialize(root: Path, **kwargs: object) -> dict:
    return initialize_repositories([target(root)], **kwargs)[0]  # type: ignore[arg-type]


def test_a_fresh_repository_is_not_initialized(repository: Path) -> None:
    report = inspect_repository(target(repository))

    assert report["state"] == "not_initialized"
    assert report["installed"] is False
    assert report["data_directory"] == DEFAULT_ASDD_DATA_DIRECTORY.as_posix()
    assert report["missing_skills"] == list(ASDD_SKILL_NAMES)


def test_initialize_writes_every_tracked_file(repository: Path) -> None:
    report = initialize(repository)

    assert report["state"] == "ready"
    assert report["installed"] is True
    assert (repository / ASDD_MANIFEST).is_file()
    assert (repository / ASDD_RULES).is_file()
    for name in ASDD_SKILL_NAMES:
        assert (repository / ASDD_SKILLS_DIRECTORY / name / "SKILL.md").is_file()
        assert (
            repository
            / ASDD_SKILLS_DIRECTORY
            / name
            / "references"
            / "code-context-contract.md"
        ).is_file()
    for name in ASDD_SKELETON_FILES:
        assert (repository / DEFAULT_ASDD_DATA_DIRECTORY / name).is_file()
    assert (repository / DEFAULT_ASDD_DATA_DIRECTORY / "changes" / "archive").is_dir()


def test_the_manifest_names_the_method_and_nothing_operational(
    repository: Path,
) -> None:
    initialize(repository)

    payload = json.loads((repository / ASDD_MANIFEST).read_text(encoding="utf-8"))

    assert payload == {
        "product": PRODUCT_NAME,
        "methodology": METHODOLOGY,
        "methodology_name": METHODOLOGY_NAME,
        "data_directory": DEFAULT_ASDD_DATA_DIRECTORY.as_posix(),
        "skills_directory": ASDD_SKILLS_DIRECTORY.as_posix(),
        "skills": list(ASDD_SKILL_NAMES),
    }
    assert "Evo" not in METHODOLOGY_NAME


def test_the_write_lock_is_the_only_thing_setup_asks_git_to_ignore(
    repository: Path,
) -> None:
    """Everything else setup writes is meant to be committed."""

    initialize(repository)

    ignore = (repository / ASDD_GITIGNORE).read_text(encoding="utf-8")

    assert ignore == "locks/\n"


def test_manifest_paths_stay_posix_for_collaborators_on_other_platforms(
    repository: Path,
) -> None:
    initialize(repository)

    text = (repository / ASDD_MANIFEST).read_text(encoding="utf-8")

    assert "\\\\" not in text
    assert "documents/asdd" in text


def test_initializing_twice_changes_nothing(repository: Path) -> None:
    initialize(repository)
    before = (repository / ASDD_RULES).read_text(encoding="utf-8")
    (repository / DEFAULT_ASDD_DATA_DIRECTORY / "project.md").write_text(
        "# Local edits\n", encoding="utf-8"
    )

    report = initialize(repository)

    assert report["state"] == "ready"
    assert (repository / ASDD_RULES).read_text(encoding="utf-8") == before
    assert (repository / DEFAULT_ASDD_DATA_DIRECTORY / "project.md").read_text(
        encoding="utf-8"
    ) == "# Local edits\n"


def test_overwrite_restores_the_bundled_files_but_keeps_the_catalogue(
    repository: Path,
) -> None:
    initialize(repository)
    catalogue = repository / DEFAULT_ASDD_DATA_DIRECTORY
    (catalogue / "changes" / "add-user-auth").mkdir(parents=True)
    (catalogue / "changes" / "add-user-auth" / "proposal.md").write_text(
        "---\nchange: add-user-auth\n---\n\n## Why\n", encoding="utf-8"
    )
    (repository / ASDD_RULES).write_text("tampered\n", encoding="utf-8")

    initialize(repository, overwrite=True)

    assert "ASDD Core Rules" in (repository / ASDD_RULES).read_text(encoding="utf-8")
    assert (catalogue / "changes" / "add-user-auth" / "proposal.md").is_file()


def test_a_missing_skill_asks_for_repair_rather_than_reporting_ready(
    repository: Path,
) -> None:
    initialize(repository)
    (repository / ASDD_SKILLS_DIRECTORY / "asdd-verify" / "SKILL.md").unlink()

    report = inspect_repository(target(repository))

    assert report["state"] == "upgrade_required"
    assert report["missing_skills"] == ["asdd-verify"]


def test_a_missing_catalogue_file_asks_for_repair(repository: Path) -> None:
    initialize(repository)
    (repository / DEFAULT_ASDD_DATA_DIRECTORY / "specs" / "README.md").unlink()

    report = inspect_repository(target(repository))

    assert report["state"] == "upgrade_required"
    assert report["missing_catalogue_files"] == ["specs/README.md"]


def test_a_manifest_from_an_older_build_asks_for_repair(repository: Path) -> None:
    initialize(repository)
    (repository / ASDD_MANIFEST).write_text(
        json.dumps({"methodology": METHODOLOGY, "data_directory": "documents/asdd"}),
        encoding="utf-8",
    )

    report = inspect_repository(target(repository))

    assert report["state"] == "upgrade_required"


def test_a_foreign_manifest_is_invalid_rather_than_upgradable(
    repository: Path,
) -> None:
    initialize(repository)
    (repository / ASDD_MANIFEST).write_text(
        json.dumps({"methodology": "SOMETHING-ELSE"}), encoding="utf-8"
    )

    report = inspect_repository(target(repository))

    assert report["state"] == "invalid"
    assert "methodology must be ASDD" in report["issue"]


def test_a_skill_that_is_not_a_regular_file_is_invalid(repository: Path) -> None:
    initialize(repository)
    skill = repository / ASDD_SKILLS_DIRECTORY / "asdd-plan" / "SKILL.md"
    skill.unlink()
    skill.mkdir()

    report = inspect_repository(target(repository))

    assert report["state"] == "invalid"


def test_a_skill_out_of_coding_scope_is_invalid(repository: Path) -> None:
    initialize(repository)
    scope = repository / ASDD_SKILLS_DIRECTORY / "asdd-propose"
    next(scope.glob(".evoflux.json")).write_text(
        json.dumps({"modes": ["work"]}), encoding="utf-8"
    )

    report = inspect_repository(target(repository))

    assert report["state"] == "invalid"


@pytest.mark.parametrize("value", ["/etc", "../outside", ".git/hooks", ".evoflux/asdd"])
def test_a_catalogue_outside_the_repository_is_refused(
    repository: Path, value: str
) -> None:
    with pytest.raises(ValueError):
        initialize(repository, data_directory=value)


def test_moving_the_catalogue_needs_an_explicit_overwrite(repository: Path) -> None:
    initialize(repository)

    with pytest.raises(AsddSetupConflict, match="overwrite=true"):
        initialize(repository, data_directory="docs/specs")

    report = initialize(repository, data_directory="docs/specs", overwrite=True)
    assert report["data_directory"] == "docs/specs"


def test_the_catalogue_location_is_resolved_from_the_manifest(
    repository: Path,
) -> None:
    initialize(repository, data_directory="docs/specs")

    assert resolve_data_directory(repository) == Path("docs/specs")


def test_an_unreadable_manifest_falls_back_to_the_default_location(
    repository: Path,
) -> None:
    assert resolve_data_directory(repository) == DEFAULT_ASDD_DATA_DIRECTORY


def test_every_skill_installs_its_output_template(repository: Path) -> None:
    # Three of the four shipped templates were never read by anything and never
    # reached a repository, so an agent writing `design.md` had only prose to
    # work from. Each phase's contract now lives beside the Skill that uses it.
    initialize(repository)

    for name in ASDD_SKILL_NAMES:
        template = repository / ".evoflux" / "skills" / name / "TEMPLATE.md"
        assert template.is_file(), name
        assert template.read_text(encoding="utf-8").startswith("# Output template")


def test_a_repository_missing_a_template_needs_an_upgrade(repository: Path) -> None:
    initialize(repository)
    (repository / ".evoflux" / "skills" / "asdd-plan" / "TEMPLATE.md").unlink()

    report = inspect_repository(target(repository))

    assert report["state"] == "upgrade_required"
    assert "asdd-plan" in report["missing_skills"]


def test_a_repository_installed_under_the_old_product_name_upgrades(
    repository: Path,
) -> None:
    # Renaming the product surface must not present every existing install as
    # damaged. The manifest is not broken — it was written by an older build.
    initialize(repository)
    manifest = repository / ".evoflux" / "asdd" / "config.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(PRODUCT_NAME, "Agent Specs"),
        encoding="utf-8",
    )

    report = inspect_repository(target(repository))

    assert report["state"] == "upgrade_required"
    assert PRODUCT_NAME in report["issue"]


def test_a_manifest_naming_an_unknown_product_is_still_refused(
    repository: Path,
) -> None:
    initialize(repository)
    manifest = repository / ".evoflux" / "asdd" / "config.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(PRODUCT_NAME, "Something Else"),
        encoding="utf-8",
    )

    report = inspect_repository(target(repository))

    assert report["state"] == "invalid"


def test_reinstalling_rewrites_the_manifest_to_the_current_name(
    repository: Path,
) -> None:
    initialize(repository)
    manifest = repository / ".evoflux" / "asdd" / "config.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(PRODUCT_NAME, "Agent Specs"),
        encoding="utf-8",
    )

    report = initialize(repository, overwrite=True)

    assert report["state"] == "ready"
    assert PRODUCT_NAME in manifest.read_text(encoding="utf-8")


def test_setup_lays_out_the_whole_catalogue(repository: Path) -> None:
    """Every durable kind of page has a home, and the home explains itself.

    A directory with no README is a directory an agent has to guess the rules
    of — and an empty one does not survive a checkout at all.
    """
    initialize(repository)
    data = repository / DEFAULT_ASDD_DATA_DIRECTORY

    assert (data / "project.md").is_file()
    assert (data / "architecture" / "README.md").is_file()
    assert (data / "architecture" / "decisions" / "README.md").is_file()
    assert (data / "specs" / "README.md").is_file()
    assert (data / "reference" / "README.md").is_file()
    assert (data / "analysis" / "README.md").is_file()
    assert (data / "changes" / "README.md").is_file()
    assert (data / "changes" / "archive").is_dir()


def test_project_md_maps_every_directory_it_creates(repository: Path) -> None:
    """The map an agent reads first has to name what setup actually wrote."""
    initialize(repository)
    project = (repository / DEFAULT_ASDD_DATA_DIRECTORY / "project.md").read_text(
        encoding="utf-8"
    )

    for directory in (
        "architecture/",
        "architecture/decisions/",
        "specs/",
        "reference/",
        "analysis/",
        "changes/",
    ):
        assert directory in project, f"project.md does not name {directory}"


def test_a_repository_installed_before_the_catalogue_grew_upgrades(
    repository: Path,
) -> None:
    """An existing install is offered the new directories, not left behind."""
    initialize(repository)
    data = repository / DEFAULT_ASDD_DATA_DIRECTORY
    for name in ("architecture", "reference", "analysis"):
        for path in sorted((data / name).rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (data / name).rmdir()
    (data / "specs" / "README.md").write_text("# kept by hand\n", encoding="utf-8")

    report = inspect_repository(target(repository))
    assert report["state"] == "upgrade_required"
    assert report["missing_catalogue_files"] == [
        "architecture/README.md",
        "architecture/decisions/README.md",
        "reference/README.md",
        "analysis/README.md",
    ]

    repaired = initialize(repository)

    assert repaired["state"] == "ready"
    assert (data / "architecture" / "decisions" / "README.md").is_file()
    # An upgrade fills gaps; it does not overwrite what the repository edited.
    assert (data / "specs" / "README.md").read_text(encoding="utf-8") == (
        "# kept by hand\n"
    )
