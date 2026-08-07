"""Portable skill discovery, catalog rendering, and activation.

The package follows the Agent Skills progressive-disclosure contract:

* discovery exposes only routing metadata;
* the model-visible catalog is bounded by the active model context window;
* ``SKILL.md`` and bundled resources are read only after activation.

The legacy ``app.agent.tools.builtin.skill`` module remains the public tool
facade so saved agent configurations and third-party imports keep working.
"""

from app.agent.skills.catalog import SkillCatalogRender, render_skill_catalog
from app.agent.skills.discovery import (
    SkillDiagnostic,
    SkillRecord,
    discover_skill_records,
)

__all__ = [
    "SkillCatalogRender",
    "SkillDiagnostic",
    "SkillRecord",
    "discover_skill_records",
    "render_skill_catalog",
]
