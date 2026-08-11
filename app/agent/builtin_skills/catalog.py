"""Mode scope for bundled skills.

Skill frontmatter remains portable (name + description only). EvoFlux-specific
runtime scope lives here so it cannot leak into generic skill bundles or their
loaded instruction bodies.
"""

from __future__ import annotations

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode

BUNDLED_SKILL_MODES: dict[str, tuple[SkillMode, ...]] = {
    "aim-business-rule-extraction": ("aim",),
    "aim-diff-triage": ("aim",),
    "aim-equivalence-testing": ("aim",),
    "aim-kb-conventions": ("aim",),
    "aim-legacy-comprehension": ("aim",),
    "aim-ui-conventions": ("aim",),
    "algorithmic-art": ("work",),
    "canvas-design": ("work",),
    "coding-debugging": ("coding", "aim"),
    "coding-implementation": ("coding", "aim"),
    "coding-investigation": ("coding", "aim"),
    "coding-migration": ("coding", "aim"),
    "coding-performance": ("coding",),
    "coding-review": ("coding", "aim"),
    "coding-security": ("coding",),
    "coding-testing": ("coding", "aim"),
    "frontend-design": ALL_SKILL_MODES,
    "mcp-installer": ALL_SKILL_MODES,
    "plugin-development": ALL_SKILL_MODES,
    "plugin-installer": ALL_SKILL_MODES,
    "review-pull-requests": ("coding",),
    "self-healing": ALL_SKILL_MODES,
    "skill-installer": ALL_SKILL_MODES,
    "theme-factory": ("work",),
    "work-decision": ("work", "aim"),
    "work-data-analysis": ("work",),
    "work-planning": ("work", "aim"),
    "work-research": ("work",),
    "work-writing": ("work", "aim"),
}


def bundled_skill_modes(name: str) -> tuple[SkillMode, ...]:
    """Return the explicit scope for a bundled skill."""

    return BUNDLED_SKILL_MODES.get(name, ALL_SKILL_MODES)
