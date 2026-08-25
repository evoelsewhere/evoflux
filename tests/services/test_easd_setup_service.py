from __future__ import annotations

import json

import pytest

from app.agent.skills.discovery import (
    discover_skill_records,
    select_skill_records_for_mode,
)
from app.easd_skills import EASD_SKILL_NAMES, read_easd_skill
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    EasdSetupConflict,
    initialize_repositories,
    inspect_repositories,
    inspect_repository,
)


def test_initialize_repository_creates_stable_easd_contract(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")

    before = inspect_repository(target)
    assert before["state"] == "not_initialized"

    after = initialize_repositories([target])[0]
    assert after["state"] == "ready"
    assert after["installed"] is True
    manifest = json.loads(
        (tmp_path / ".evoflux" / "easd" / "config.json").read_text(encoding="utf-8")
    )
    assert manifest == {
        "data_directory": "documents/easd",
        "methodology": "EASD",
        "methodology_name": "Evo Agent Specification-Driven Development",
        "product": "Evo Agent Specs",
        "rules_file": ".evoflux/easd/RULES.md",
        "skills": list(EASD_SKILL_NAMES),
        "skills_directory": ".evoflux/skills",
        "templates_directory": "documents/easd/templates",
    }
    assert (tmp_path / ".evoflux" / "easd" / "RULES.md").is_file()
    data_readme = (tmp_path / "documents" / "easd" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "## Document skeleton" in data_readme
    assert ".evoflux/easd/config.json" in data_readme
    assert "<slug>--<run-uuid>" in data_readme
    assert "specifications/0001.yaml" in data_readme
    assert "events/<sequence>-<event-uuid>.yaml" in data_readme
    assert "Direct flow leaves `plans/` empty" in data_readme
    assert "Accepted Spec/Plan revisions" in data_readme
    assert (tmp_path / "documents" / "easd" / "runs").is_dir()
    assert {
        item.name for item in (tmp_path / "documents" / "easd" / "templates").iterdir()
    } == {
        "intent.yaml",
        "specification.yaml",
        "plan.yaml",
        "mission.yaml",
        "review.yaml",
        "verification.yaml",
        "evidence.yaml",
        "deviation.yaml",
        "event.yaml",
        "run.yaml",
    }
    records = discover_skill_records([tmp_path / ".evoflux" / "skills"])
    assert set(records) == set(EASD_SKILL_NAMES)
    assert all(record.source == "project-EvoFlux" for record in records.values())
    assert all(record.modes == ("coding",) for record in records.values())
    assert set(select_skill_records_for_mode(records, "coding")) == set(
        EASD_SKILL_NAMES
    )
    assert select_skill_records_for_mode(records, "work") == {}

    first_manifest = (tmp_path / ".evoflux" / "easd" / "config.json").read_bytes()
    initialize_repositories([target])
    assert (tmp_path / ".evoflux" / "easd" / "config.json").read_bytes() == (
        first_manifest
    )


def test_legacy_upgrade_preserves_existing_valid_edited_skill(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    easd = tmp_path / ".evoflux" / "easd"
    (easd / "specs").mkdir(parents=True)
    (easd / "config.json").write_text(
        json.dumps(
            {
                "methodology": "EASD",
                "product": "Evo Agent Specs",
                "schema_version": 1,
                "specs_directory": ".evoflux/easd/specs",
            }
        ),
        encoding="utf-8",
    )
    skill = tmp_path / ".evoflux" / "skills" / "easd-plan"
    skill.mkdir(parents=True)
    edited = (
        "---\nname: easd-plan\n"
        "description: Project-specific EASD planning guidance.\n---\n"
        "Preserve this repository-owned extension.\n"
    )
    (skill / "SKILL.md").write_text(edited, encoding="utf-8")
    (skill / ".evoflux.json").write_text('{"modes":["coding"]}\n', encoding="utf-8")

    before = inspect_repository(target)
    assert before["state"] == "upgrade_required"
    assert before["installed"] is False

    after = initialize_repositories([target])[0]

    assert after["state"] == "ready"
    assert "schema_version" not in after
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == edited
    assert all(
        (tmp_path / ".evoflux" / "skills" / name / "SKILL.md").is_file()
        for name in EASD_SKILL_NAMES
    )


def test_legacy_setup_upgrade_adds_current_store_without_replacing_skills(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    easd = tmp_path / ".evoflux" / "easd"
    (easd / "specs").mkdir(parents=True)
    old_names = EASD_SKILL_NAMES
    (easd / "config.json").write_text(
        json.dumps(
            {
                "methodology": "EASD",
                "methodology_name": "Evo Agent Specification-Driven Development",
                "product": "Evo Agent Specs",
                "store_format": "easd-repository-v1",
                "schema_version": 2,
                "skill_bundle_version": 2,
                "skills": list(old_names),
                "skills_directory": ".evoflux/skills",
                "specs_directory": ".evoflux/easd/specs",
            }
        ),
        encoding="utf-8",
    )
    for name in old_names:
        skill = tmp_path / ".evoflux" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(read_easd_skill(name), encoding="utf-8")
        (skill / ".evoflux.json").write_text('{"modes":["coding"]}\n', encoding="utf-8")
    plan_skill = tmp_path / ".evoflux" / "skills" / "easd-plan" / "SKILL.md"
    edited = plan_skill.read_text(encoding="utf-8") + "\nProject extension.\n"
    plan_skill.write_text(edited, encoding="utf-8")

    before = inspect_repository(target)
    assert before["state"] == "upgrade_required"

    after = initialize_repositories([target])[0]

    assert after["state"] == "ready"
    assert "schema_version" not in after
    assert "skill_bundle_version" not in after
    assert "store_format" not in after
    upgraded_manifest = json.loads((easd / "config.json").read_text(encoding="utf-8"))
    assert "store_format" not in upgraded_manifest
    assert after["data_directory"] == "documents/easd"
    assert plan_skill.read_text(encoding="utf-8") == edited
    assert (tmp_path / ".evoflux" / "skills" / "easd-review" / "SKILL.md").is_file()


def test_initialize_uses_custom_repository_data_directory(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")

    result = initialize_repositories([target], data_directory="documents/agent-specs")[
        0
    ]

    assert result["data_directory"] == "documents/agent-specs"
    assert result["data_path"] == str(tmp_path / "documents" / "agent-specs")
    assert (tmp_path / "documents" / "agent-specs" / "runs").is_dir()
    manifest = json.loads((tmp_path / ".evoflux" / "easd" / "config.json").read_text())
    assert manifest["data_directory"] == "documents/agent-specs"


@pytest.mark.parametrize("value", ["../outside", "/tmp/easd", ".git/easd"])
def test_initialize_rejects_unsafe_data_directory(tmp_path, value):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")

    with pytest.raises(ValueError, match="data_directory"):
        initialize_repositories([target], data_directory=value)


def test_initialized_project_skill_precedes_same_named_global_skill(tmp_path):
    repository = tmp_path / "repository"
    global_root = tmp_path / "global-skills"
    repository.mkdir()
    initialize_repositories(
        [EasdRepositoryTarget(path=str(repository), name="repository")]
    )
    global_skill = global_root / "easd-specify"
    global_skill.mkdir(parents=True)
    (global_skill / "SKILL.md").write_text(
        "---\nname: easd-specify\n"
        "description: Global fallback with the same portable identity.\n---\n"
        "This lower-precedence Skill must not replace the project bundle.\n",
        encoding="utf-8",
    )
    (global_skill / ".evoflux.json").write_text(
        '{"modes":["coding"]}\n', encoding="utf-8"
    )

    records = discover_skill_records([repository / ".evoflux" / "skills", global_root])

    selected = records["easd-specify"]
    assert selected.source == "project-EvoFlux"
    assert selected.skill_file == (
        repository / ".evoflux" / "skills" / "easd-specify" / "SKILL.md"
    )
    assert selected.shadowed_paths == [str(global_skill / "SKILL.md")]


def test_invalid_setup_requires_explicit_repair(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="frontend")
    manifest = tmp_path / ".evoflux" / "easd" / "config.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"methodology":"wrong"}\n', encoding="utf-8")

    assert inspect_repository(target)["state"] == "invalid"
    with pytest.raises(EasdSetupConflict, match="overwrite=true"):
        initialize_repositories([target])

    repaired = initialize_repositories([target], overwrite=True)[0]
    assert repaired["state"] == "ready"


def test_inspect_repositories_preserves_project_order_and_display_names(tmp_path):
    first = tmp_path / "api"
    second = tmp_path / "web"
    first.mkdir()
    second.mkdir()
    targets = [
        EasdRepositoryTarget(path=str(first), name="api"),
        EasdRepositoryTarget(path=str(second), name="web", display_name="Frontend"),
    ]
    initialize_repositories([targets[0]])

    result = inspect_repositories(targets)

    assert [item["name"] for item in result] == ["api", "web"]
    assert [item["state"] for item in result] == ["ready", "not_initialized"]
    assert result[1]["display_name"] == "Frontend"


def test_setup_rejects_data_directory_symlink_escape(tmp_path):
    repository = tmp_path / "repository"
    outside = tmp_path / "outside"
    repository.mkdir()
    outside.mkdir()
    data = repository / "documents" / "easd"
    data.parent.mkdir(parents=True)
    data.symlink_to(outside, target_is_directory=True)
    target = EasdRepositoryTarget(path=str(repository), name="repository")

    with pytest.raises(ValueError, match="escapes repository|symlink"):
        initialize_repositories(
            [target], data_directory="documents/easd", overwrite=True
        )
    assert list(outside.iterdir()) == []


def test_setup_rejects_symlinked_easd_skill_directory(tmp_path):
    repository = tmp_path / "repository"
    outside = tmp_path / "outside-skill"
    repository.mkdir()
    outside.mkdir()
    skills = repository / ".evoflux" / "skills"
    skills.mkdir(parents=True)
    (skills / "easd-specify").symlink_to(outside, target_is_directory=True)
    target = EasdRepositoryTarget(path=str(repository), name="repository")

    inspected = inspect_repository(target)

    assert inspected["state"] == "invalid"
    assert "escapes repository" in inspected["issue"]
    with pytest.raises(EasdSetupConflict):
        initialize_repositories([target])
    with pytest.raises(ValueError, match="escapes repository"):
        initialize_repositories([target], overwrite=True)
    assert list(outside.iterdir()) == []
