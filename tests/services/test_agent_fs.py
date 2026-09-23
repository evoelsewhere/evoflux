"""Tests for the ``agent_fs`` filesystem service."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import agent_fs
from app.services.agent_fs import (
    AgentFsConflictError,
    AgentFsNotFoundError,
    AgentFsPathError,
)


@pytest.fixture
def fs_dirs(tmp_path: Path, monkeypatch):
    """Redirect AGENTS_DIR and SKILLS_DIR to a temp directory per test."""
    from app.core.config import settings

    agents = tmp_path / "agents"
    skills = tmp_path / "skills"
    agents.mkdir()
    skills.mkdir()
    monkeypatch.setattr(settings, "AGENTS_DIR", str(agents))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills))
    return agents, skills


# ── Agents ───────────────────────────────────────────────────────────────────


def test_list_agents_empty(fs_dirs):
    assert agent_fs.list_agents() == []


def test_write_and_read_agent(fs_dirs):
    agents_dir, _ = fs_dirs
    record = agent_fs.write_agent("alpha", "---\nname: alpha\n---\nhi\n", create=True)
    assert Path(record.path) == agents_dir / "alpha.md"
    assert (agents_dir / "alpha.md").read_text() == "---\nname: alpha\n---\nhi\n"

    read = agent_fs.read_agent("alpha")
    assert read.name == "alpha"
    assert "hi" in read.content


def test_write_agent_strips_temperature_from_frontmatter_only(fs_dirs):
    agents_dir, _ = fs_dirs
    content = (
        "---\n"
        "name: alpha\n"
        "temperature: 0.4\n"
        "thinking_level: high\n"
        "---\n"
        "Keep this prompt example:\n"
        "temperature: 0.9\n"
    )

    agent_fs.write_agent("alpha", content, create=True)

    saved = (agents_dir / "alpha.md").read_text(encoding="utf-8")
    assert saved == (
        "---\n"
        "name: alpha\n"
        "thinking_level: high\n"
        "---\n"
        "Keep this prompt example:\n"
        "temperature: 0.9\n"
    )


def test_migrate_agent_temperature_settings_recursively(tmp_path):
    agents_dir = tmp_path / "agents"
    nested = agents_dir / "coding" / "agent.md"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "---\nname: agent\ntemperature: 0.2\n---\nPrompt.\n",
        encoding="utf-8",
    )

    assert agent_fs.migrate_agent_temperature_settings(agents_dir) == 1
    assert nested.read_text(encoding="utf-8") == ("---\nname: agent\n---\nPrompt.\n")
    assert agent_fs.migrate_agent_temperature_settings(agents_dir) == 0


def test_write_and_read_nested_agent(fs_dirs):
    agents_dir, _ = fs_dirs
    record = agent_fs.write_agent(
        "coding/evoflux", "---\nname: evoflux\n---\nhi\n", create=True
    )
    assert Path(record.path) == agents_dir / "coding" / "evoflux.md"
    assert agent_fs.read_agent("coding/evoflux").name == "coding/evoflux"


def test_write_agent_create_conflict(fs_dirs):
    agent_fs.write_agent("alpha", "x", create=True)
    with pytest.raises(AgentFsConflictError):
        agent_fs.write_agent("alpha", "y", create=True)


def test_write_agent_update_allows_overwrite(fs_dirs):
    agent_fs.write_agent("alpha", "v1", create=True)
    agent_fs.write_agent("alpha", "v2", create=False)
    assert agent_fs.read_agent("alpha").content == "v2"


def test_delete_agent(fs_dirs):
    agent_fs.write_agent("alpha", "x", create=True)
    agent_fs.delete_agent("alpha")
    assert agent_fs.list_agents() == []
    with pytest.raises(AgentFsNotFoundError):
        agent_fs.read_agent("alpha")


def test_read_agent_not_found(fs_dirs):
    with pytest.raises(AgentFsNotFoundError):
        agent_fs.read_agent("missing")


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "../evil",
        "a\\b",
        ".hidden",
        "a/.hidden",
        "x y",
        "a" * 70,
    ],
)
def test_invalid_name_rejected(fs_dirs, bad_name):
    with pytest.raises(AgentFsPathError):
        agent_fs.read_agent(bad_name)


def test_list_agents_sorted(fs_dirs):
    agent_fs.write_agent("beta", "x", create=True)
    agent_fs.write_agent("alpha", "x", create=True)
    agent_fs.write_agent("gamma", "x", create=True)
    assert agent_fs.list_agents() == ["alpha", "beta", "gamma"]


def test_list_agents_includes_nested_files(fs_dirs):
    agent_fs.write_agent("evoflux", "x", create=True)
    agent_fs.write_agent("coding/evoflux", "x", create=True)
    assert agent_fs.list_agents() == ["coding/evoflux", "evoflux"]


def test_list_agents_is_read_only_when_coding_lead_exists(fs_dirs):
    agents_dir, _ = fs_dirs
    agent_fs.write_agent(
        "coding/evoflux",
        "---\nname: evoflux\nrole: lead\nmodel: codex:gpt-5.4\n---\n",
        create=True,
    )

    assert agent_fs.list_agents() == ["coding/evoflux"]
    assert sorted(p.name for p in (agents_dir / "coding").glob("*.md")) == [
        "evoflux.md"
    ]


def test_list_agents_does_not_special_case_user_owned_coding_names(fs_dirs):
    agent_fs.write_agent("coding/evoflux", "x", create=True)
    agent_fs.write_agent("coding/executor", "x", create=True)

    assert "coding/executor" in agent_fs.list_agents()


# ── Skills ───────────────────────────────────────────────────────────────────


def test_write_and_read_skill(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill(
        "research", "---\nname: research\n---\nbody\n", create=True
    )
    assert Path(record.path) == skills_dir / "research" / "SKILL.md"
    assert (skills_dir / "research" / "SKILL.md").read_text() == (
        "---\nname: research\n---\nbody\n"
    )


def test_list_skills_only_dirs_with_skill_md(fs_dirs):
    _, skills_dir = fs_dirs
    agent_fs.write_skill("a", "x", create=True)
    # Empty dir should not show up.
    (skills_dir / "empty").mkdir()
    # Dir with a non-SKILL.md file should also not show up.
    (skills_dir / "other").mkdir()
    (skills_dir / "other" / "notes.md").write_text("x")
    assert agent_fs.list_skills() == ["a"]


def test_delete_skill_removes_empty_dir(fs_dirs):
    _, skills_dir = fs_dirs
    agent_fs.write_skill("a", "x", create=True)
    agent_fs.delete_skill("a")
    assert not (skills_dir / "a").exists()


def test_delete_skill_preserves_dir_with_siblings(fs_dirs):
    _, skills_dir = fs_dirs
    agent_fs.write_skill("a", "x", create=True)
    (skills_dir / "a" / "notes.md").write_text("extra")
    agent_fs.delete_skill("a")
    assert (skills_dir / "a").exists()
    assert not (skills_dir / "a" / "SKILL.md").exists()


def test_skill_bundle_files_round_trip(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("research", "body", create=True)
    agent_fs.apply_skill_bundle_files(
        Path(record.path).parent,
        [
            ("references/guide.md", "# Guide\n", "utf-8"),
            ("assets/icon.bin", "AAEC", "base64"),
        ],
        [],
    )

    files = {
        file.path: file
        for file in agent_fs.list_skill_bundle_files(skills_dir / "research")
    }
    assert files["references/guide.md"].content == "# Guide\n"
    assert files["references/guide.md"].editable is True
    assert files["assets/icon.bin"].content is None
    assert files["assets/icon.bin"].editable is False


def test_skill_bundle_listing_has_item_and_aggregate_content_budgets(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("research", "body", create=True)
    skill_dir = Path(record.path).parent
    resources = skill_dir / "references"
    resources.mkdir()
    payload = "x" * (450 * 1024)
    for index in range(205):
        (resources / f"{index:03}.md").write_text(payload if index < 5 else "x")

    files = agent_fs.list_skill_bundle_files(skill_dir)

    assert len(files) == 200
    assert sum(len(file.content or "") for file in files) <= 2 * 1024 * 1024
    assert sum(file.content is not None for file in files[:5]) == 4


def test_skill_bundle_listing_caps_scandir_before_materializing_wide_directory(
    fs_dirs, monkeypatch
):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("research", "body", create=True)
    skill_dir = Path(record.path).parent
    for index in range(10):
        (skill_dir / f"{index:02}.md").write_text(str(index))

    real_scandir = agent_fs.os.scandir
    consumed = 0

    class GuardedScandir:
        def __init__(self, path):
            self._iterator = real_scandir(path)

        def __enter__(self):
            self._iterator.__enter__()
            return self

        def __exit__(self, *args):
            return self._iterator.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal consumed
            consumed += 1
            if consumed > 4:
                raise AssertionError("bundle listing consumed beyond its hard cap")
            return next(self._iterator)

    monkeypatch.setattr(agent_fs, "_MAX_SKILL_BUNDLE_ENTRIES", 3)
    monkeypatch.setattr(agent_fs.os, "scandir", GuardedScandir)

    files = agent_fs.list_skill_bundle_files(skill_dir)

    assert consumed <= 4
    assert len(files) <= 3
    assert [file.path for file in files] == sorted(file.path for file in files)


def test_updating_skill_resource_preserves_executable_mode(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("research", "body", create=True)
    skill_dir = Path(record.path).parent
    script = skill_dir / "scripts" / "run.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\necho old\n")
    script.chmod(0o755)

    agent_fs.apply_skill_bundle_files(
        skill_dir,
        [("scripts/run.sh", "#!/bin/sh\necho new\n", "utf-8")],
        [],
    )

    assert script.stat().st_mode & 0o777 == 0o755
    assert "echo new" in script.read_text()


@pytest.mark.parametrize(
    "path",
    [
        "",
        "../secret",
        "nested/SKILL.md",
        "SKILL.md",
        "/absolute.md",
        "bad\\path.md",
    ],
)
def test_skill_bundle_rejects_unsafe_resource_paths(fs_dirs, path):
    _, skills_dir = fs_dirs
    agent_fs.write_skill("research", "body", create=True)
    with pytest.raises(AgentFsPathError):
        agent_fs.apply_skill_bundle_files(
            skills_dir / "research",
            [(path, "bad", "utf-8")],
            [],
        )


def test_delete_skill_not_found(fs_dirs):
    with pytest.raises(AgentFsNotFoundError):
        agent_fs.delete_skill("missing")


# ── Direct-child layout ──────────────────────────────────────────────────────


def test_list_skills_returns_direct_children_only(fs_dirs):
    _, skills_dir = fs_dirs
    agent_fs.write_skill("search", "x", create=True)
    nested = skills_dir / "git" / "commit"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("x")
    hidden = skills_dir / ".staging"
    hidden.mkdir()
    (hidden / "SKILL.md").write_text("x")

    assert agent_fs.list_skills() == ["search"]


def test_nested_skill_file_is_a_read_only_bundle_file(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("suite", "body", create=True)
    nested = Path(record.path).parent / "references" / "inner"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("inner")

    files = agent_fs.list_skill_bundle_files(skills_dir / "suite")

    assert [(file.path, file.editable) for file in files] == [
        ("references/inner/SKILL.md", False)
    ]
    assert agent_fs.count_skill_bundle_files(skills_dir / "suite") == 1


def test_count_skill_bundle_files_excludes_root_skill_md(fs_dirs):
    _, skills_dir = fs_dirs
    record = agent_fs.write_skill("research", "body", create=True)
    skill_dir = Path(record.path).parent
    (skill_dir / "a.md").write_text("a")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print()")

    assert agent_fs.count_skill_bundle_files(skill_dir) == 2
    assert agent_fs.count_skill_bundle_files(skills_dir / "missing") == 0


def test_skill_conflict_on_create(fs_dirs):
    agent_fs.write_skill("research", "x", create=True)
    with pytest.raises(AgentFsConflictError):
        agent_fs.write_skill("research", "y", create=True)


def test_skill_create_rejects_non_empty_directory(fs_dirs):
    _, skills_dir = fs_dirs
    (skills_dir / "research").mkdir()
    (skills_dir / "research" / "stray.txt").write_text("x")
    with pytest.raises(AgentFsConflictError):
        agent_fs.write_skill("research", "y", create=True)


def test_skill_update_allows_overwrite(fs_dirs):
    agent_fs.write_skill("research", "v1", create=True)
    agent_fs.write_skill("research", "v2", create=False)
    assert agent_fs.read_skill("research").content == "v2"


@pytest.mark.parametrize(
    "bad_name",
    ["", "git/commit", "a/b/c", "../evil", "a\\b", ".hidden"],
)
def test_invalid_skill_name_rejected(fs_dirs, bad_name):
    with pytest.raises(AgentFsPathError):
        agent_fs.read_skill(bad_name)
