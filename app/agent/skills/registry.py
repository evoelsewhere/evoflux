"""Skill discovery: roots, precedence, and the per-run catalog.

A Skill is a direct child directory of a skills root that contains a file
named exactly ``SKILL.md``. Deeper ``SKILL.md`` files are ordinary bundle
files. Roots are scanned in precedence order — project, user, plugin,
built-in — and the first valid Skill for a name wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from loguru import logger

from app.agent.skills.models import Skill, SkillSource
from app.agent.skills.spec import (
    MAX_SKILL_FILE_BYTES,
    SkillDiagnostic,
    SkillFormatError,
    parse_skill,
)
from app.core.skill_settings import disabled_skill_names, skill_settings_signature


# Bounds the scan of one root. Real roots hold tens of Skills; the cap only
# stops a misconfigured root (for example a home directory) from stalling
# every model call.
MAX_ROOT_ENTRIES = 2_000
PROJECT_SKILL_DIRS = (".evoflux/skills", ".agents/skills", ".claude/skills")
HOME_SKILL_DIRS = (".agents/skills", ".claude/skills")


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    source: SkillSource
    editable: bool = False
    plugin_id: str | None = None


def builtin_skills_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "builtin_skills"


def user_skills_dir() -> Path:
    from app.core.config import settings

    return Path(settings.SKILLS_DIR)


def home_dir() -> Path:
    """The home directory holding cross-client ``.agents``/``.claude`` roots."""

    return Path.home()


def _repo_ancestors(start: Path) -> list[Path]:
    """Return *start* up to its Git root, deepest first.

    Outside a repository only *start* is scanned: the authorized workspace is
    the trust boundary, not its arbitrary parents.
    """

    resolved = start.resolve()
    chain: list[Path] = []
    current = resolved
    while True:
        chain.append(current)
        if (current / ".git").exists():
            return chain
        if current.parent == current:
            return [resolved]
        current = current.parent


def skill_roots(
    workspace_roots: Sequence[Path] = (),
    *,
    include_plugins: bool = True,
) -> list[SkillRoot]:
    """Return every skills root in precedence order."""

    roots: list[SkillRoot] = []
    seen: set[str] = set()

    def add(root: SkillRoot) -> None:
        key = os.path.normcase(str(root.path.absolute()))
        if key not in seen:
            seen.add(key)
            roots.append(root)

    for workspace in workspace_roots:
        for ancestor in _repo_ancestors(workspace):
            for relative in PROJECT_SKILL_DIRS:
                add(SkillRoot(ancestor / relative, "project", editable=True))
    add(SkillRoot(user_skills_dir(), "user", editable=True))
    home = home_dir()
    for relative in HOME_SKILL_DIRS:
        add(SkillRoot(home / relative, "user", editable=True))
    if include_plugins:
        from app.plugin_platform.skills import plugin_skill_roots

        for root in plugin_skill_roots():
            add(root)
    add(SkillRoot(builtin_skills_dir(), "builtin"))
    return roots


def _skill_directories(root: Path) -> list[Path]:
    """Return candidate Skill directories directly under *root*, sorted."""

    found: list[Path] = []
    try:
        with os.scandir(root) as iterator:
            for index, entry in enumerate(iterator):
                if index >= MAX_ROOT_ENTRIES:
                    logger.warning(
                        "skill_root_entry_limit root={} limit={}",
                        root,
                        MAX_ROOT_ENTRIES,
                    )
                    break
                if entry.name.startswith("."):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        found.append(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return []
    found.sort(key=lambda path: path.name)
    return [path for path in found if (path / "SKILL.md").is_file()]


def _root_signature(root: SkillRoot) -> tuple:
    entries: list[tuple[str, int, int]] = []
    for directory in _skill_directories(root.path):
        try:
            stat = (directory / "SKILL.md").stat()
        except OSError:
            continue
        entries.append((directory.name, stat.st_mtime_ns, stat.st_size))
    return (str(root.path), root.source, root.plugin_id, tuple(entries))


def _read_skill(root: SkillRoot, directory: Path) -> Skill:
    location = (directory / "SKILL.md").absolute()
    symlinked = directory.is_symlink() or location.is_symlink()
    skill = Skill(
        name=directory.name,
        description="",
        location=location,
        root=root.path.absolute(),
        source=root.source,
        plugin_id=root.plugin_id,
        editable=root.editable and not symlinked,
        symlinked=symlinked,
    )
    try:
        with location.open("rb") as handle:
            payload = handle.read(MAX_SKILL_FILE_BYTES + 1)
        if len(payload) > MAX_SKILL_FILE_BYTES:
            raise ValueError(f"SKILL.md exceeds {MAX_SKILL_FILE_BYTES} bytes.")
        definition = parse_skill(payload.decode("utf-8"), directory_name=directory.name)
    except (OSError, UnicodeError, ValueError, SkillFormatError) as exc:
        skill.diagnostics.append(SkillDiagnostic("unreadable-skill", str(exc), "error"))
        return skill
    if definition.name:
        skill.name = definition.name
    skill.description = definition.description
    skill.license = definition.license
    skill.compatibility = definition.compatibility
    skill.metadata = definition.metadata
    skill.allowed_tools = definition.allowed_tools
    skill.disable_model_invocation = definition.disable_model_invocation
    skill.user_invocable = definition.user_invocable
    skill.diagnostics.extend(definition.diagnostics)
    return skill


@dataclass(frozen=True)
class SkillCatalog:
    """The Skills visible to one run, keyed by name."""

    skills: dict[str, Skill]

    def get(self, name: str) -> Skill | None:
        return self.skills.get(name)

    def all(self) -> list[Skill]:
        return [self.skills[name] for name in sorted(self.skills)]

    def model_visible(self) -> list[Skill]:
        return [skill for skill in self.all() if skill.model_visible]

    def user_visible(self) -> list[Skill]:
        return [skill for skill in self.all() if skill.user_visible]

    def active(self) -> list[Skill]:
        """Valid, enabled Skills: those whose files the model may read."""

        return [skill for skill in self.all() if skill.valid and skill.enabled]

    def for_location(self, path: str | Path) -> Skill | None:
        """Return the active Skill whose ``SKILL.md`` is *path*."""

        try:
            key = os.path.normcase(str(Path(path).resolve()))
        except (OSError, ValueError):
            return None
        for skill in self.active():
            try:
                if os.path.normcase(str(skill.location.resolve())) == key:
                    return skill
            except OSError:
                continue
        return None


@lru_cache(maxsize=32)
def _discover_cached(
    roots: tuple[SkillRoot, ...],
    signature: tuple,
) -> dict[str, Skill]:
    del signature  # cache key only
    disabled = disabled_skill_names()
    candidates: dict[str, list[Skill]] = {}
    for root in roots:
        for directory in _skill_directories(root.path):
            skill = _read_skill(root, directory)
            skill.enabled = skill.name not in disabled
            candidates.setdefault(skill.name, []).append(skill)

    selected: dict[str, Skill] = {}
    for name, found in candidates.items():
        winner = next((skill for skill in found if skill.valid), found[0])
        winner.shadowed = [skill.location for skill in found if skill is not winner]
        if winner.shadowed:
            logger.info(
                "skill_shadowed name={} winner={} shadowed={}",
                name,
                winner.location,
                [str(path) for path in winner.shadowed],
            )
        selected[name] = winner
    return selected


def discover_skills(
    workspace_roots: Iterable[Path] = (),
    *,
    roots: Sequence[SkillRoot] | None = None,
) -> SkillCatalog:
    """Discover the Skill catalog for *workspace_roots* (or explicit *roots*)."""

    resolved_roots = tuple(
        root
        for root in (roots if roots is not None else skill_roots(list(workspace_roots)))
        if root.path.is_dir()
    )
    signature = (
        tuple(_root_signature(root) for root in resolved_roots),
        skill_settings_signature(),
    )
    return SkillCatalog(dict(_discover_cached(resolved_roots, signature)))


def sandbox_workspace_roots() -> list[Path]:
    """Authorized workspaces of the current run's sandbox."""

    from app.agent.sandbox import get_sandbox

    try:
        return list(get_sandbox().allowed_workspace_roots)
    except Exception:  # noqa: BLE001 - no sandbox outside a run
        return []


def invalidate_skill_cache() -> None:
    _discover_cached.cache_clear()


__all__ = [
    "HOME_SKILL_DIRS",
    "MAX_ROOT_ENTRIES",
    "PROJECT_SKILL_DIRS",
    "SkillCatalog",
    "SkillRoot",
    "builtin_skills_dir",
    "discover_skills",
    "home_dir",
    "invalidate_skill_cache",
    "sandbox_workspace_roots",
    "skill_roots",
    "user_skills_dir",
]
