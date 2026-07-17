"""Install a rulebook pack's shareable content into discovery roots
(aim-framework.md §4.1 AIM-4: ``aim_rulebook_service``).

A pack may ship pack-specific ``workflows/*.yaml``, ``skills/<name>/``
directories, and ``agents/<name>.md`` overlays. Creating or joining an
AIM project installs them — gap-fill only for workflows/skills (never
overwriting user-edited files), marker-guarded merge for agent overlays
— so `/workflow`, the skill loader, and the AIM roster see them
immediately. The builtin AIM pipeline library needs no installation (it
is itself a discovery root); this covers per-stack additions like a
pack's ``java-modernization-idioms`` skill or its ``aim-converter``
prompt overlay.

Pack resolution is KB-first (:func:`resolve_rulebook_dir`): a project
whose KB repo carries its own ``rulebook/`` directory uses that content
instead of a builtin pack — the same "KB is system of record" principle
already applied to ``aim.yaml``, unit frontmatter, and business rules,
extended to the rulebook itself so a bespoke migration's rules travel
with the engagement's KB repo rather than requiring an EvoFlux code
change. The three shipped packs (java8-java21, vb6-dotnet, cobol-java21)
remain available as reusable starting points for projects that don't
need to customize anything.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from loguru import logger

from app.core.config import settings

#: Convention: a KB-local override lives at ``<kb_root>/rulebook/`` —
#: exactly one directory, since a KB belongs to exactly one AIM project
#: with exactly one active rulebook_id (no need to nest by id).
_PROJECT_RULEBOOK_DIRNAME = "rulebook"


def _pack_dir(rulebook_id: str) -> Path:
    from app.agent.tools.builtin.aim import _builtin_rulebooks_dir

    return _builtin_rulebooks_dir() / rulebook_id


def resolve_rulebook_dir(kb_root: Path, rulebook_id: str) -> Path | None:
    """The project's rulebook pack directory: ``<kb_root>/rulebook/`` if
    the KB carries a local override, else the matching builtin pack.
    ``None`` if neither exists (a real 404/no-op case for callers, not an
    error — an unrecognized ``rulebook_id`` with no KB override)."""
    project_dir = kb_root / _PROJECT_RULEBOOK_DIRNAME
    if project_dir.is_dir():
        return project_dir
    builtin_dir = _pack_dir(rulebook_id)
    return builtin_dir if builtin_dir.is_dir() else None


def is_project_rulebook(kb_root: Path) -> bool:
    """Whether *kb_root* carries a KB-local rulebook override — the
    Rulebook screen uses this to label the source (project vs. shared
    pack) without re-deriving the resolution logic."""
    return (kb_root / _PROJECT_RULEBOOK_DIRNAME).is_dir()


def _overlay_marker(rulebook_id: str, overlay_name: str) -> str:
    return f"<!-- rulebook-overlay: {rulebook_id}/{overlay_name} -->"


def _merge_agent_overlay(
    base_path: Path, overlay_path: Path, rulebook_id: str
) -> bool:
    """Merge one pack agent overlay onto the installed blueprint.

    Overlay semantics (documented in the packs themselves): frontmatter
    ``skills`` are appended (deduped), everything else in the overlay
    frontmatter is ignored, and the overlay body is appended to the base
    system prompt. A marker comment keeps the merge idempotent across
    repeated create/join calls. Returns True when the file changed.
    """
    from app.agent.tools.builtin.skill import _parse_frontmatter

    marker = _overlay_marker(rulebook_id, overlay_path.name)
    base_text = base_path.read_text(encoding="utf-8")
    if marker in base_text:
        return False

    overlay_meta, overlay_body = _parse_frontmatter(
        overlay_path.read_text(encoding="utf-8")
    )
    base_meta, base_body = _parse_frontmatter(base_text)

    overlay_skills = overlay_meta.get("skills") or []
    if overlay_skills:
        merged_skills = list(base_meta.get("skills") or [])
        for skill in overlay_skills:
            if skill not in merged_skills:
                merged_skills.append(skill)
        base_meta["skills"] = merged_skills

    frontmatter_yaml = yaml.safe_dump(
        base_meta, sort_keys=False, allow_unicode=True
    ).strip()
    appended = f"\n\n{marker}\n\n{overlay_body.strip()}\n" if overlay_body.strip() else f"\n\n{marker}\n"
    content = f"---\n{frontmatter_yaml}\n---\n\n{base_body.strip()}{appended}"
    base_path.write_text(content, encoding="utf-8")
    return True


def install_rulebook_content(kb_root: Path, rulebook_id: str) -> dict[str, list[str]]:
    """Copy the pack's workflows + skills into the editable discovery
    roots and merge its agent overlays onto the AIM roster. Resolves the
    pack KB-first (see :func:`resolve_rulebook_dir`). Returns what was
    installed (paths relative to their roots)."""
    installed: dict[str, list[str]] = {"workflows": [], "skills": [], "agents": []}
    pack = resolve_rulebook_dir(kb_root, rulebook_id)
    if pack is None:
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

    # Agent overlays — merged onto the installed AIM roster, not copied.
    # The roster must exist first (an old config dir may predate AIM);
    # the same self-heal the team loader uses backfills it from seed.
    agents_src = pack / "agents"
    if agents_src.is_dir():
        from app.services.team_manager import (
            _ensure_aim_agents_installed,
            _resolve_aim_agents_dir,
        )

        agents_dir = _resolve_aim_agents_dir()
        _ensure_aim_agents_installed(agents_dir)
        for overlay in sorted(agents_src.glob("*.md")):
            base = agents_dir / overlay.name
            if not base.is_file():
                logger.warning(
                    "aim_rulebook_agent_overlay_skipped rulebook={} agent={} "
                    "reason=no-base-blueprint",
                    rulebook_id,
                    overlay.name,
                )
                continue
            try:
                if _merge_agent_overlay(base, overlay, rulebook_id):
                    installed["agents"].append(overlay.name)
            except Exception as exc:  # noqa: BLE001 — best-effort, never block create/join
                logger.warning(
                    "aim_rulebook_agent_overlay_failed rulebook={} agent={} error={}",
                    rulebook_id,
                    overlay.name,
                    exc,
                )

    if installed["workflows"] or installed["skills"] or installed["agents"]:
        logger.info(
            "aim_rulebook_content_installed rulebook={} workflows={} skills={} agents={}",
            rulebook_id,
            installed["workflows"],
            installed["skills"],
            installed["agents"],
        )
    return installed
