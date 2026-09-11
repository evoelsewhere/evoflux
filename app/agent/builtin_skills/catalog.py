"""Mode scope for bundled skills.

Skill frontmatter remains portable (name + description only). EvoFlux-specific
runtime scope lives here so it cannot leak into generic skill bundles or their
loaded instruction bodies.
"""

from __future__ import annotations

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode

BUNDLED_SKILL_MODES: dict[str, tuple[SkillMode, ...]] = {
    "coding-api-design": ("coding",),
    "coding-browser-verify": ("coding",),
    "coding-debugging": ("coding",),
    "coding-git-workflow": ("coding",),
    "coding-implementation": ("coding",),
    "coding-investigation": ("coding",),
    "coding-migration": ("coding",),
    "coding-observability": ("coding",),
    "coding-performance": ("coding",),
    "coding-review": ("coding",),
    "coding-security": ("coding",),
    "coding-simplification": ("coding",),
    "coding-testing": ("coding",),
    "compose-next": ("coding",),
    "data-analytics": ("work",),
    "deep-research": ("work",),
    "design-blueprint": ALL_SKILL_MODES,
    "docx-official": ALL_SKILL_MODES,
    "evolve": ALL_SKILL_MODES,
    "frontend-design": ALL_SKILL_MODES,
    "html-to-video-pipeline": ALL_SKILL_MODES,
    "learn-everything": ("work",),
    "mcp-installer": ALL_SKILL_MODES,
    "memory-search": ALL_SKILL_MODES,
    "modern-python-toolchain": ("coding",),
    "pdf-official": ALL_SKILL_MODES,
    "playwright": ("coding",),
    "plugin-development": ALL_SKILL_MODES,
    "plugin-installer": ALL_SKILL_MODES,
    "pptx-official": ALL_SKILL_MODES,
    "product-design": ALL_SKILL_MODES,
    "research-paper-writing": ("work",),
    "review-pull-requests": ("coding",),
    "sales": ("work",),
    "self-healing": ALL_SKILL_MODES,
    "skill-creator": ALL_SKILL_MODES,
    "skill-installer": ALL_SKILL_MODES,
    "super-research": ALL_SKILL_MODES,
    "xlsx-official": ALL_SKILL_MODES,
}


def bundled_skill_modes(name: str) -> tuple[SkillMode, ...]:
    """Return the explicit scope for a bundled skill."""

    return BUNDLED_SKILL_MODES.get(name, ALL_SKILL_MODES)
