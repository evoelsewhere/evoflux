from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest
import yaml

from app.agent.skills.discovery import (
    discover_skill_records,
    select_skill_records_for_mode,
)
from app.easd_skills import (
    EASD_LEGACY_SKILL_SHA256,
    EASD_LEGACY_OPTIONAL_SKELETON_FILES,
    EASD_SKILL_NAMES,
    EASD_SKELETON_FILES,
    EASD_TEMPLATE_NAMES,
    read_easd_skill,
    read_easd_skeleton,
    read_easd_template,
)
from app.services.easd_setup_service import (
    EASD_RUNTIME_DIRECTORY,
    EASD_TEMPLATES_DIRECTORY,
    EasdRepositoryTarget,
    EasdSetupConflict,
    initialize_repositories,
    inspect_repositories,
    inspect_repository,
    localize_legacy_runs,
    preview_runtime_migration,
)
from app.services.easd_repository_store import EasdRepositoryStore


def test_specify_skill_documents_non_shell_verification_command_grammar():
    skill = read_easd_skill("easd-specify")

    assert "Verification command grammar" in skill
    assert "python -m pytest tests/test_simple.py" in skill
    assert 'python -c "...; ..."' in skill
    assert "`&&`, `||`, `;`, `|`, `>`, or `<`" in skill


@pytest.mark.parametrize("name", EASD_SKILL_NAMES)
def test_phase_skills_use_runtime_context_not_tracked_data_directory(name):
    skill = read_easd_skill(name)

    assert "`runtime_directory`" in skill
    assert "injected EASD context" in skill
    assert "current run under\n`data_directory`" not in skill


def test_initialize_repository_creates_stable_easd_contract(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    existing_document = tmp_path / "documents" / "architecture" / "system.md"
    existing_document.parent.mkdir(parents=True)
    existing_document.write_text("existing project knowledge\n", encoding="utf-8")

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
        "templates_directory": ".evoflux/easd/.local/templates",
        "runtime_storage": "local",
        "runtime_directory": ".evoflux/easd/.local/runs",
        "publish_converged_runs": "manual",
    }
    assert (tmp_path / ".evoflux" / "easd" / "RULES.md").is_file()
    data_readme = (tmp_path / "documents" / "easd" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "## Structure" in data_readme
    assert "specs/" in data_readme
    assert "features/" in data_readme
    assert "architecture/" in data_readme
    assert "reference/" in data_readme
    assert "<slug>--<run-uuid>" in data_readme
    assert "Draft Specs stay Run-local" in data_readme
    assert "explicitly adopt or link it" in data_readme
    assert not (tmp_path / "documents" / "easd" / "runs").exists()
    assert (tmp_path / EASD_RUNTIME_DIRECTORY).is_dir()
    assert all(
        (tmp_path / "documents" / "easd" / path).is_file()
        for path in EASD_SKELETON_FILES
    )
    assert {
        item.name for item in (tmp_path / EASD_TEMPLATES_DIRECTORY).iterdir()
    } == set(EASD_TEMPLATE_NAMES)
    assert existing_document.read_text(encoding="utf-8") == (
        "existing project knowledge\n"
    )
    assert not (tmp_path / "documents" / "easd" / "architecture" / "system.md").exists()
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
    initialize_repositories([target], overwrite=True)
    assert existing_document.read_text(encoding="utf-8") == (
        "existing project knowledge\n"
    )


def test_missing_ignored_runtime_is_upgradeable_without_repair(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    shutil.rmtree(tmp_path / ".evoflux" / "easd" / ".local")

    before = inspect_repository(target)
    assert before["state"] == "upgrade_required"
    assert "Initialize local EASD" in before["issue"]

    after = initialize_repositories([target])[0]
    assert after["state"] == "ready"
    assert (tmp_path / EASD_RUNTIME_DIRECTORY).is_dir()


def test_linked_worktree_reuses_source_runtime_and_templates(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    target = EasdRepositoryTarget(path=str(source), name="source")
    initialize_repositories([target])
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=EASD Test",
            "-c",
            "user.email=easd@example.invalid",
            "commit",
            "-qm",
            "init",
        ],
        check=True,
    )
    worktree = tmp_path / "worktree"
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "worktree",
            "add",
            "-q",
            str(worktree),
            "-b",
            "easd-test",
        ],
        check=True,
    )

    inspected = inspect_repository(
        EasdRepositoryTarget(path=str(worktree), name="worktree")
    )

    assert inspected["state"] == "ready"
    assert inspected["runtime_owner_path"] == str(source.resolve())
    assert inspected["runtime_shared_across_worktrees"] is True
    assert inspected["runtime_path"] == str(source / EASD_RUNTIME_DIRECTORY)

    shutil.rmtree(source / ".evoflux" / "easd" / ".local")
    worktree_target = EasdRepositoryTarget(path=str(worktree), name="worktree")
    assert inspect_repository(worktree_target)["state"] == "upgrade_required"
    assert initialize_repositories([worktree_target])[0]["state"] == "ready"
    assert (source / EASD_RUNTIME_DIRECTORY).is_dir()
    assert (source / EASD_TEMPLATES_DIRECTORY / "run.yaml").is_file()

    prior_run_id = uuid4()
    prior_checkout_run = (
        worktree / EASD_RUNTIME_DIRECTORY / f"prior-worktree--{prior_run_id}"
    )
    prior_checkout_run.mkdir(parents=True)
    (prior_checkout_run / "run.yaml").write_text(
        f"id: {prior_run_id}\ntitle: Prior worktree\nstatus: active\n",
        encoding="utf-8",
    )
    assert EasdRepositoryStore(worktree).load_run(prior_run_id).directory == (
        prior_checkout_run
    )
    new_run_id = uuid4()
    new_run = EasdRepositoryStore(worktree).create_run(
        run={"id": str(new_run_id), "title": "Shared runtime", "status": "intent"},
        intent={"title": "Shared runtime", "problem": "Avoid split ledgers"},
    )
    assert new_run.directory.parent == source / EASD_RUNTIME_DIRECTORY


def test_exact_legacy_bundled_skill_refreshes_but_project_edit_survives(
    tmp_path, monkeypatch
):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    skill = tmp_path / ".evoflux" / "skills" / "easd-plan" / "SKILL.md"
    old_generated = skill.read_text(encoding="utf-8").replace(
        "`runtime_directory`", "`legacy_runtime_directory`", 1
    )
    skill.write_text(old_generated, encoding="utf-8")
    monkeypatch.setitem(
        EASD_LEGACY_SKILL_SHA256,
        "easd-plan",
        __import__("hashlib").sha256(old_generated.encode("utf-8")).hexdigest(),
    )

    assert inspect_repository(target)["state"] == "upgrade_required"
    initialize_repositories([target])
    assert skill.read_text(encoding="utf-8") == read_easd_skill("easd-plan")

    edited = skill.read_text(encoding="utf-8") + "\nProject extension.\n"
    skill.write_text(edited, encoding="utf-8")
    initialize_repositories([target])
    assert skill.read_text(encoding="utf-8") == edited


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
    assert not (tmp_path / "documents" / "agent-specs" / "runs").exists()
    assert (tmp_path / EASD_RUNTIME_DIRECTORY).is_dir()
    manifest = json.loads((tmp_path / ".evoflux" / "easd" / "config.json").read_text())
    assert manifest["data_directory"] == "documents/agent-specs"


def test_runtime_migration_removes_only_unchanged_generated_legacy_files(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    templates = tmp_path / "documents" / "easd" / "templates"
    templates.mkdir(parents=True)
    unchanged = templates / "run.yaml"
    customized = templates / "plan.yaml"
    unchanged.write_text(read_easd_template("run.yaml"), encoding="utf-8")
    customized.write_text("project-specific template\n", encoding="utf-8")
    placeholder_name = EASD_LEGACY_OPTIONAL_SKELETON_FILES[0]
    placeholder = tmp_path / "documents" / "easd" / placeholder_name
    placeholder.parent.mkdir(parents=True, exist_ok=True)
    placeholder.write_text(read_easd_skeleton(placeholder_name), encoding="utf-8")

    preview = preview_runtime_migration([target])[0]
    assert preview["legacy_generated_file_count"] == 2

    migrated = localize_legacy_runs([target])[0]

    assert migrated["removed_generated_file_count"] == 2
    assert not unchanged.exists()
    assert not placeholder.exists()
    assert customized.read_text(encoding="utf-8") == "project-specific template\n"


def test_runtime_migration_rolls_back_completed_moves_on_failure(tmp_path, monkeypatch):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    legacy = tmp_path / "documents" / "easd" / "runs"
    legacy.mkdir(parents=True)
    sources = []
    for title in ("first", "second"):
        source = legacy / f"{title}--{uuid4()}"
        source.mkdir()
        (source / "run.yaml").write_text(f"title: {title}\n", encoding="utf-8")
        sources.append(source)
    real_replace = os.replace
    move_calls = 0

    def fail_second_directory_move(source, destination):
        nonlocal move_calls
        if Path(source).is_dir():
            move_calls += 1
            if move_calls == 2:
                raise OSError("simulated move failure")
        return real_replace(source, destination)

    monkeypatch.setattr(
        "app.services.easd_setup_service.os.replace", fail_second_directory_move
    )

    with pytest.raises(OSError, match="simulated move failure"):
        localize_legacy_runs([target])

    assert all(source.is_dir() for source in sources)
    assert list((tmp_path / EASD_RUNTIME_DIRECTORY).iterdir()) == []


def test_runtime_migration_revalidates_generated_content_before_delete(
    tmp_path, monkeypatch
):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    generated = tmp_path / "documents" / "easd" / "templates" / "run.yaml"
    generated.parent.mkdir(parents=True)
    generated.write_text(read_easd_template("run.yaml"), encoding="utf-8")
    real_preview = preview_runtime_migration

    def preview_then_customize(targets):
        result = real_preview(targets)
        generated.write_text("project custom content\n", encoding="utf-8")
        return result

    monkeypatch.setattr(
        "app.services.easd_setup_service.preview_runtime_migration",
        preview_then_customize,
    )

    with pytest.raises(EasdSetupConflict, match="changed"):
        localize_legacy_runs([target])

    assert generated.read_text(encoding="utf-8") == "project custom content\n"


def test_setup_normalizes_only_legacy_run_and_template_index_entries(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    index = tmp_path / "documents" / "easd" / "index.yaml"
    payload = json.loads(json.dumps(yaml.safe_load(index.read_text())))
    payload["sections"]["runs"] = "runs"
    payload["sections"]["templates"] = "templates"
    payload["sections"]["custom"] = "project-docs"
    payload["authority"]["execution"] = "runs"
    index.write_text(yaml.safe_dump(payload, sort_keys=False))

    initialize_repositories([target])
    normalized = yaml.safe_load(index.read_text())

    assert "runs" not in normalized["sections"]
    assert "templates" not in normalized["sections"]
    assert normalized["sections"]["custom"] == "project-docs"
    assert normalized["authority"]["execution"] == ".evoflux/easd/.local/runs"


def test_run_only_setup_upgrades_skeleton_without_migrating_existing_docs(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    missing = tmp_path / "documents" / "easd" / "specs" / "README.md"
    missing.unlink()
    existing = tmp_path / "documents" / "features" / "billing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing feature contract\n", encoding="utf-8")

    before = inspect_repository(target)

    assert before["state"] == "upgrade_required"
    assert "knowledge skeleton" in before["issue"]
    after = initialize_repositories([target])[0]
    assert after["state"] == "ready"
    assert missing.is_file()
    assert existing.read_text(encoding="utf-8") == "existing feature contract\n"
    assert not (tmp_path / "documents" / "easd" / "features" / "billing.md").exists()


def test_setup_rejects_nested_knowledge_symlink(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    specs = tmp_path / "documents" / "easd" / "specs"
    (specs / "README.md").unlink()
    specs.rmdir()
    target_directory = tmp_path / "documents" / "easd" / "linked-specs"
    target_directory.mkdir()
    specs.symlink_to(target_directory, target_is_directory=True)

    inspected = inspect_repository(target)

    assert inspected["state"] == "invalid"
    assert "must not traverse a symlink" in inspected["issue"]
    with pytest.raises(EasdSetupConflict):
        initialize_repositories([target])
    with pytest.raises(ValueError, match="must not traverse a symlink"):
        initialize_repositories([target], overwrite=True)


def test_setup_rejects_malformed_or_oversized_knowledge_index(tmp_path):
    target = EasdRepositoryTarget(path=str(tmp_path), name="backend")
    initialize_repositories([target])
    index = tmp_path / "documents" / "easd" / "index.yaml"
    index.write_text("[not-a-mapping]\n", encoding="utf-8")

    malformed = inspect_repository(target)

    assert malformed["state"] == "invalid"
    assert "must contain a mapping" in malformed["issue"]

    index.write_text(
        "methodology: EASD\nsections:\n  specs: another-directory\n",
        encoding="utf-8",
    )
    wrong_sections = inspect_repository(target)
    assert wrong_sections["state"] == "invalid"
    assert "invalid sections" in wrong_sections["issue"]

    index.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    oversized = inspect_repository(target)
    assert oversized["state"] == "invalid"
    assert "exceeds 262144 bytes" in oversized["issue"]


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
