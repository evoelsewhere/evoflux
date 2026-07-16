"""Install a rulebook pack's shareable content into discovery roots
(aim-framework.md §4.1 AIM-4: ``aim_rulebook_service``).

A pack may ship pack-specific ``workflows/*.yaml`` and ``skills/<name>/``
directories. Creating or joining an AIM project installs them — gap-fill
only, never overwriting user-edited files — into the global discovery
roots so `/workflow` and the skill loader see them immediately. The
builtin AIM pipeline library needs no installation (it is itself a
discovery root); this covers per-stack additions like a pack's
``java-modernization-idioms`` skill.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from app.core.config import settings


def _pack_dir(rulebook_id: str) -> Path:
    from app.agent.tools.builtin.aim import _builtin_rulebooks_dir

    return _builtin_rulebooks_dir() / rulebook_id


def install_rulebook_content(rulebook_id: str) -> dict[str, list[str]]:
    """Copy the pack's workflows + skills into the editable discovery
    roots. Returns what was installed (paths relative to their roots)."""
    installed: dict[str, list[str]] = {"workflows": [], "skills": []}
    pack = _pack_dir(rulebook_id)
    if not pack.is_dir():
        return installed

    workflows_src = pack / "workflows"
    if workflows_src.is_dir():
        from app.services.workflows_fs import global_workflows_dir

        target_dir = global_workflows_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(workflows_src.glob("*.yaml")):
            target = target_dir / path.name
            if target.exists():
                continue
            shutil.copy2(path, target)
            installed["workflows"].append(path.name)

    skills_src = pack / "skills"
    if skills_src.is_dir():
        skills_root = Path(settings.SKILLS_DIR)
        skills_root.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(skills_src.iterdir()):
            if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
                continue
            target = skills_root / skill_dir.name
            if target.exists():
                continue
            shutil.copytree(skill_dir, target)
            installed["skills"].append(skill_dir.name)

    if installed["workflows"] or installed["skills"]:
        logger.info(
            "aim_rulebook_content_installed rulebook={} workflows={} skills={}",
            rulebook_id,
            installed["workflows"],
            installed["skills"],
        )
    return installed
