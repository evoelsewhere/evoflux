"""Skills contributed by enabled Agent Plugins.

A plugin contributes the direct children of its ``skills/`` directory. The
directory is exposed as one skills root between the user and built-in roots.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.skills.registry import SkillRoot
from app.plugin_platform.registry import list_effective_installations, plugin_data_root
from app.plugin_platform.validator import inspect_plugin


def plugin_skill_roots() -> list[SkillRoot]:
    """Return the ``skills/`` roots of enabled, valid plugin installations."""

    roots: list[SkillRoot] = []
    for installation in list_effective_installations(enabled_only=True):
        root = Path(installation.root).resolve()
        skills_root = root / "skills"
        if not skills_root.is_dir():
            continue
        inspection = inspect_plugin(root, data_root=plugin_data_root(installation.id))
        if not inspection.valid:
            continue
        roots.append(SkillRoot(skills_root, "plugin", plugin_id=installation.id))
    return roots


__all__ = ["plugin_skill_roots"]
