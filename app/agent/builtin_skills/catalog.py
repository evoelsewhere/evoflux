"""Mode scope for bundled skills.

Skill frontmatter remains portable (name + description only). EvoFlux-specific
runtime scope lives here so it cannot leak into generic skill bundles or their
loaded instruction bodies.
"""

from __future__ import annotations

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode

BUNDLED_SKILL_MODES: dict[str, tuple[SkillMode, ...]] = {
    "coding-change": ("coding",),
    "coding-investigate": ("coding",),
    "coding-operate": ("coding",),
    "coding-verify": ("coding",),
    "data-analytics": ("work",),
    "design-blueprint": ALL_SKILL_MODES,
    "docx-official": ALL_SKILL_MODES,
    "frontend-design": ALL_SKILL_MODES,
    "learn-everything": ("work",),
    "mcp-installer": ALL_SKILL_MODES,
    "memory-search": ALL_SKILL_MODES,
    "pdf-official": ALL_SKILL_MODES,
    "plugin-development": ALL_SKILL_MODES,
    "plugin-installer": ALL_SKILL_MODES,
    "pptx-official": ALL_SKILL_MODES,
    "review-pull-requests": ("coding",),
    "self-healing": ALL_SKILL_MODES,
    "skill-creator": ALL_SKILL_MODES,
    "skill-installer": ALL_SKILL_MODES,
    "super-research": ALL_SKILL_MODES,
    "xlsx-official": ALL_SKILL_MODES,
}


def bundled_skill_modes(name: str) -> tuple[SkillMode, ...]:
    """Return the explicit scope for a bundled skill."""

    return BUNDLED_SKILL_MODES.get(name, ALL_SKILL_MODES)
