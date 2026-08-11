"""Portable Skill definition validation shared by CRUD and Conductor sync."""

from __future__ import annotations

import re

from app.agent.skills.discovery import MAX_DESCRIPTION_CHARS, MAX_SKILL_FILE_BYTES
from app.agent.tools.builtin.skill import _parse_frontmatter

PORTABLE_SKILL_NAME_MAX_CHARS = 64
_PORTABLE_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def portable_skill_name_error(name: str) -> str | None:
    if (
        len(name) > PORTABLE_SKILL_NAME_MAX_CHARS
        or _PORTABLE_SKILL_NAME_RE.fullmatch(name) is None
    ):
        return (
            "New skill names must be 1-64 lowercase letters, digits, and "
            "single hyphens (for example 'release-audit')."
        )
    return None


def parse_skill_definition(name: str, content: str) -> tuple[str, str | None]:
    """Return ``(description, error)`` using runtime Skill constraints."""

    try:
        encoded_size = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        return "", f"SKILL.md is not valid UTF-8 text: {exc}"
    if encoded_size > MAX_SKILL_FILE_BYTES:
        return "", f"SKILL.md exceeds the {MAX_SKILL_FILE_BYTES}-byte runtime limit."

    try:
        meta, instructions = _parse_frontmatter(content)
    except Exception as exc:
        return "", f"Invalid frontmatter: {exc}"

    if not isinstance(meta, dict):
        return "", "Frontmatter must be a YAML mapping."

    frontmatter_name = meta.get("name")
    if not isinstance(frontmatter_name, str) or not frontmatter_name.strip():
        return "", "Frontmatter field 'name' is required and must be a string."
    description = meta.get("description")
    if not isinstance(description, str):
        return "", ("Frontmatter field 'description' is required and must be a string.")
    description = description.strip()
    if not description:
        return "", "Frontmatter field 'description' must not be empty."
    if len(description) > MAX_DESCRIPTION_CHARS:
        return "", (
            "Frontmatter field 'description' exceeds "
            f"{MAX_DESCRIPTION_CHARS} characters."
        )
    if frontmatter_name != name:
        return description, (
            f"Frontmatter name '{frontmatter_name}' does not match directory "
            f"name '{name}'."
        )
    if not instructions.strip():
        return description, "SKILL.md instructions must not be empty."
    return description, None


__all__ = ["parse_skill_definition", "portable_skill_name_error"]
