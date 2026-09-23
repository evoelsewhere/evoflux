"""Skill discovery: roots, direct-child layout, precedence and switches."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.skills.registry import (
    SkillRoot,
    discover_skills,
    invalidate_skill_cache,
    skill_roots,
)
from app.core.skill_settings import set_skill_enabled


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "Does a thing. Use when testing.",
    extra: str = "",
    body: str = "Follow these steps.",
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n{body}\n",
        encoding="utf-8",
    )
    return directory


@pytest.fixture(autouse=True)
def _fresh_cache():
    invalidate_skill_cache()
    yield
    invalidate_skill_cache()


def test_only_direct_children_with_skill_md_are_skills(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "alpha")
    nested = write_skill(root, "hub")
    write_skill(nested / "references", "inner")
    (root / "notes").mkdir()
    (root / ".hidden").mkdir()
    (root / ".hidden" / "SKILL.md").write_text(
        "---\nname: hidden\ndescription: d\n---\nx"
    )

    catalog = discover_skills(roots=[SkillRoot(root, "user", editable=True)])

    assert [skill.name for skill in catalog.all()] == ["alpha", "hub"]
    alpha = catalog.get("alpha")
    assert alpha is not None
    assert alpha.location == (root / "alpha" / "SKILL.md").absolute()
    assert alpha.directory == (root / "alpha").absolute()
    assert alpha.editable and alpha.source == "user"


def test_first_root_wins_and_records_shadowed(tmp_path):
    project = tmp_path / "project"
    builtin = tmp_path / "builtin"
    write_skill(project, "pdf", description="Project PDF.")
    write_skill(builtin, "pdf", description="Built-in PDF.")

    catalog = discover_skills(
        roots=[
            SkillRoot(project, "project", editable=True),
            SkillRoot(builtin, "builtin"),
        ]
    )

    winner = catalog.get("pdf")
    assert winner is not None
    assert winner.description == "Project PDF."
    assert winner.shadowed == [(builtin / "pdf" / "SKILL.md").absolute()]


def test_invalid_higher_precedence_skill_does_not_hide_a_valid_one(tmp_path):
    project = tmp_path / "project"
    builtin = tmp_path / "builtin"
    (project / "pdf").mkdir(parents=True)
    (project / "pdf" / "SKILL.md").write_text("---\nname: pdf\n---\n", encoding="utf-8")
    write_skill(builtin, "pdf", description="Built-in PDF.")

    catalog = discover_skills(
        roots=[
            SkillRoot(project, "project", editable=True),
            SkillRoot(builtin, "builtin"),
        ]
    )

    winner = catalog.get("pdf")
    assert winner is not None and winner.valid
    assert winner.source == "builtin"


def test_unparseable_skill_is_listed_invalid_under_its_directory_name(tmp_path):
    root = tmp_path / "skills"
    (root / "broken").mkdir(parents=True)
    (root / "broken" / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

    catalog = discover_skills(roots=[SkillRoot(root, "user")])

    broken = catalog.get("broken")
    assert broken is not None and not broken.valid
    assert catalog.model_visible() == [] and catalog.active() == []


def test_visibility_follows_frontmatter_and_disabled_switch(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "auto")
    write_skill(root, "manual", extra="disable-model-invocation: true\n")
    write_skill(root, "model-only", extra="user-invocable: false\n")
    write_skill(root, "switched-off")
    set_skill_enabled("switched-off", False)
    try:
        catalog = discover_skills(roots=[SkillRoot(root, "user")])

        assert [skill.name for skill in catalog.model_visible()] == [
            "auto",
            "model-only",
        ]
        assert [skill.name for skill in catalog.user_visible()] == ["auto", "manual"]
        assert [skill.name for skill in catalog.active()] == [
            "auto",
            "manual",
            "model-only",
        ]
        off = catalog.get("switched-off")
        assert off is not None and off.valid and not off.enabled
    finally:
        set_skill_enabled("switched-off", True)


def test_edits_are_picked_up_without_explicit_invalidation(tmp_path):
    root = tmp_path / "skills"
    directory = write_skill(root, "alpha", description="First.")
    roots = [SkillRoot(root, "user")]
    assert discover_skills(roots=roots).get("alpha").description == "First."

    (directory / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Second, longer description.\n---\nBody\n",
        encoding="utf-8",
    )

    assert discover_skills(roots=roots).get("alpha").description == (
        "Second, longer description."
    )


def test_for_location_matches_active_skills_only(tmp_path):
    root = tmp_path / "skills"
    write_skill(root, "alpha")
    write_skill(root, "beta")
    set_skill_enabled("beta", False)
    try:
        catalog = discover_skills(roots=[SkillRoot(root, "user")])

        assert catalog.for_location(root / "alpha" / "SKILL.md").name == "alpha"
        assert catalog.for_location(str(root / "beta" / "SKILL.md")) is None
        assert catalog.for_location(root / "alpha" / "other.md") is None
    finally:
        set_skill_enabled("beta", True)


def test_skill_roots_precedence(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    workspace = repo / "packages" / "app"
    workspace.mkdir(parents=True)
    user_dir = tmp_path / "config" / "skills"
    monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", str(user_dir))
    monkeypatch.setattr("app.plugin_platform.skills.plugin_skill_roots", lambda: [])

    roots = skill_roots([workspace])

    paths = [(root.source, root.path) for root in roots]
    workspace = workspace.resolve()
    repo = repo.resolve()
    # Deepest directory first, up to and including the Git root.
    assert paths[:6] == [
        ("project", workspace / ".evoflux" / "skills"),
        ("project", workspace / ".agents" / "skills"),
        ("project", workspace / ".claude" / "skills"),
        ("project", workspace.parent / ".evoflux" / "skills"),
        ("project", workspace.parent / ".agents" / "skills"),
        ("project", workspace.parent / ".claude" / "skills"),
    ]
    assert ("project", repo / ".claude" / "skills") in paths
    sources = [root.source for root in roots]
    assert sources.index("user") > max(
        index for index, source in enumerate(sources) if source == "project"
    )
    assert sources[-1] == "builtin"
    assert roots[sources.index("user")].path == user_dir


def test_workspace_outside_a_repository_scans_only_itself(tmp_path, monkeypatch):
    workspace = tmp_path / "loose"
    workspace.mkdir()
    monkeypatch.setattr("app.plugin_platform.skills.plugin_skill_roots", lambda: [])

    project_roots = [
        root.path for root in skill_roots([workspace]) if root.source == "project"
    ]

    assert project_roots == [
        workspace.resolve() / ".evoflux" / "skills",
        workspace.resolve() / ".agents" / "skills",
        workspace.resolve() / ".claude" / "skills",
    ]


def test_builtin_skills_are_read_only(tmp_path):
    root = tmp_path / "builtin"
    write_skill(root, "alpha")

    skill = discover_skills(roots=[SkillRoot(root, "builtin")]).get("alpha")

    assert skill is not None and not skill.editable
