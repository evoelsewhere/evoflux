"""Bundled Skills follow the Agent Skills specification and best practices.

See the "Authoring rules for bundled Skills" section of
documents/architecture/agent-skills.md.
"""

from __future__ import annotations

import re

import pytest

from app.agent.skills.registry import SkillRoot, builtin_skills_dir, discover_skills
from scripts import validate_skills

BUILTIN = builtin_skills_dir()
SKILL_DIRS = validate_skills.skill_directories(BUILTIN)
_FIRST_OR_SECOND_PERSON = re.compile(r"^(use this|use when|i |you |we )", re.IGNORECASE)
_TIME_SENSITIVE = re.compile(
    r"\b(as of (?:early |mid-|late )?20\d\d|before 20\d\d|after 20\d\d|gpt-\d)",
    re.IGNORECASE,
)


def test_bundle_contains_only_skill_directories():
    entries = sorted(
        entry.name
        for entry in BUILTIN.iterdir()
        if entry.name not in {"__init__.py", "__pycache__"}
    )
    assert entries == sorted(directory.name for directory in SKILL_DIRS)


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_bundled_skill_passes_the_validator_without_warnings(skill_dir):
    result = validate_skills.validate_skill(skill_dir)

    assert result.findings == []


def test_every_bundled_skill_is_discovered_valid_and_enabled():
    catalog = discover_skills(roots=[SkillRoot(BUILTIN, "builtin")])

    assert [skill.name for skill in catalog.all()] == [path.name for path in SKILL_DIRS]
    assert all(skill.valid and not skill.diagnostics for skill in catalog.all())


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_description_is_third_person_and_says_when(skill_dir):
    skill = discover_skills(roots=[SkillRoot(BUILTIN, "builtin")]).get(skill_dir.name)

    assert skill is not None
    assert not _FIRST_OR_SECOND_PERSON.match(skill.description)
    assert "Use when" in skill.description or "use when" in skill.description


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda path: path.name)
def test_skill_md_has_no_time_sensitive_statements(skill_dir):
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    assert _TIME_SENSITIVE.search(text) is None
