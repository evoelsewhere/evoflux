"""Agent Skills: filesystem-based, progressively disclosed instructions.

See ``documents/architecture/agent-skills.md``. The model sees only Skill
metadata in the system prompt, reads ``SKILL.md`` with its ``read`` tool, and
reads or runs bundled files with its ordinary file and shell tools.
"""

from app.agent.skills.models import Skill, SkillSource
from app.agent.skills.registry import (
    SkillCatalog,
    SkillRoot,
    discover_skills,
    invalidate_skill_cache,
    skill_roots,
)
from app.agent.skills.spec import SkillDiagnostic, parse_skill, validate_skill_text

__all__ = [
    "Skill",
    "SkillCatalog",
    "SkillDiagnostic",
    "SkillRoot",
    "SkillSource",
    "discover_skills",
    "invalidate_skill_cache",
    "parse_skill",
    "skill_roots",
    "validate_skill_text",
]
