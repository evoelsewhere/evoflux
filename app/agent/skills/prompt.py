"""System-prompt text for Level 1 metadata and agent-preloaded Skills."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Sequence

from app.agent.skills.models import Skill
from app.agent.skills.spec import SkillFormatError, split_frontmatter


_INSTRUCTIONS = """The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, use the `read` tool to load the
SKILL.md at the listed location before proceeding. Resolve relative paths in a
skill against its directory (the parent of SKILL.md) and pass absolute paths to
tools. Read a skill's other files only when its instructions call for them, and
run its scripts with `shell` instead of reading them unless told otherwise.
A skill already read in this conversation does not need to be read again."""


def _paths_line() -> str:
    from app.core.config import settings

    return (
        f"EvoFlux configuration directory: {Path(settings.EVOFLUX_CONFIG_DIR).absolute()}\n"
        f"User skills directory: {Path(settings.SKILLS_DIR).absolute()}"
    )


def render_available_skills(skills: Sequence[Skill]) -> str:
    """Render the ``<available_skills>`` catalog, sorted and XML-escaped."""

    entries = [
        "  <skill>\n"
        f"    <name>{_text(skill.name)}</name>\n"
        f"    <description>{_text(' '.join(skill.description.split()))}</description>\n"
        f"    <location>{_text(skill.location.as_posix())}</location>\n"
        "  </skill>"
        for skill in sorted(skills, key=lambda item: item.name)
    ]
    return "<available_skills>\n" + "\n".join(entries) + "\n</available_skills>"


def _text(value: str) -> str:
    """Escape element text; quotes need no escaping outside attributes."""

    return escape(value, quote=False)


def read_skill_body(skill: Skill) -> str:
    """Return the current ``SKILL.md`` body without frontmatter."""

    text = skill.location.read_text(encoding="utf-8")
    try:
        _meta, body = split_frontmatter(text)
    except SkillFormatError:
        return text.strip()
    return body


def render_skill_content(skill: Skill, body: str) -> str:
    return (
        f'<skill_content name="{escape(skill.name)}" '
        f'location="{escape(skill.location.as_posix())}">\n'
        f"{body}\n\n"
        f"Skill directory: {skill.directory.as_posix()}\n"
        "Relative paths in this skill resolve against the skill directory.\n"
        "</skill_content>"
    )


def render_skills_section(
    catalog_skills: Sequence[Skill],
    preloaded: Sequence[tuple[Skill, str]] = (),
) -> str:
    """Return the complete ``## Skills`` system-prompt section, or ``""``."""

    if not catalog_skills and not preloaded:
        return ""
    parts = ["## Skills"]
    if catalog_skills:
        parts += [_INSTRUCTIONS, render_available_skills(catalog_skills)]
    if preloaded:
        parts.append(
            "The following skills are preloaded for this agent. Apply them "
            "whenever they are relevant; their files are at the stated locations."
        )
        parts += [render_skill_content(skill, body) for skill, body in preloaded]
    parts.append(_paths_line())
    return "\n\n".join(parts)


__all__ = [
    "read_skill_body",
    "render_available_skills",
    "render_skill_content",
    "render_skills_section",
]
