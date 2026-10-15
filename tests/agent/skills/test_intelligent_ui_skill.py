from __future__ import annotations

from pathlib import Path

from app.agent.skills.spec import split_frontmatter


SKILL = (
    Path(__file__).parents[3]
    / "app"
    / "agent"
    / "builtin_skills"
    / "intelligent-ui"
    / "SKILL.md"
)


def test_visual_mode_preload_keeps_intelligent_ui_policy_compact() -> None:
    _metadata, body = split_frontmatter(SKILL.read_text(encoding="utf-8"))

    assert len(body.split()) <= 900
