"""Mode scope for bundled skills.

Skill frontmatter remains portable (name + description only). EvoFlux-specific
runtime scope lives here so it cannot leak into generic skill bundles or their
loaded instruction bodies.
"""

from __future__ import annotations

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode

BUNDLED_SKILL_MODES: dict[str, tuple[SkillMode, ...]] = {
    "algorithmic-art": ("work",),
    "canvas-design": ("work",),
    "coding-debugging": ("coding",),
    "code-graph-navigation": ("coding",),
    "coding-implementation": ("coding",),
    "coding-investigation": ("coding",),
    "coding-migration": ("coding",),
    "coding-performance": ("coding",),
    "coding-review": ("coding",),
    "coding-router": ("coding",),
    "coding-security": ("coding",),
    "coding-testing": ("coding",),
    "docx": ("work",),
    "frontend-design": ALL_SKILL_MODES,
    "mcp-installer": ALL_SKILL_MODES,
    "pdf": ("work",),
    "plugin-installer": ALL_SKILL_MODES,
    "pptx": ("work",),
    "review-pull-requests": ("coding",),
    "self-healing": ALL_SKILL_MODES,
    "skill-installer": ALL_SKILL_MODES,
    "theme-factory": ("work",),
    "work-decision": ("work",),
    "work-data-analysis": ("work",),
    "work-planning": ("work",),
    "work-research": ("work",),
    "work-router": ("work",),
    "work-writing": ("work",),
    "xlsx": ("work",),
}


def bundled_skill_modes(name: str) -> tuple[SkillMode, ...]:
    """Return the explicit scope for a bundled skill."""

    return BUNDLED_SKILL_MODES.get(name, ALL_SKILL_MODES)
