"""Settings-facing management of Agent Skills.

Backs ``/api/skills``. Discovery, precedence and validation belong to
``app.agent.skills``; this module projects the discovered catalog into API
records and performs the only writes EvoFlux makes to Skill bundles:

* create a bundle in the user skills root (``settings.SKILLS_DIR``);
* edit or delete an *editable* bundle — a project or user Skill that is not
  symlinked and not owned by Conductor;
* toggle any discovered Skill on or off (``skill-settings.json``).

Every authored ``SKILL.md`` is validated strictly (see
``documents/architecture/agent-skills.md``), and every bundle write is staged
in a sibling directory and swapped in atomically.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

from loguru import logger

from app.agent.skills.models import Skill
from app.agent.skills.registry import (
    SkillCatalog,
    SkillRoot,
    discover_skills,
    user_skills_dir,
)
from app.agent.skills.spec import (
    MAX_SKILL_FILE_BYTES,
    SkillDiagnostic,
    name_problems,
    validate_skill_text,
)
from app.api.schemas.skills import (
    SkillBundleFile,
    SkillBundleFileWrite,
    SkillDetail,
    SkillDiagnosticModel,
    SkillSummary,
)
from app.conductor.models import ManagedResourceProvider
from app.conductor.provenance import managed_resource_providers
from app.core.skill_settings import SkillSettingsError, set_skill_enabled
from app.services import agent_fs, team_manager
from app.services.agent_fs import (
    AgentFsConflictError,
    AgentFsNotFoundError,
    AgentFsPathError,
)


# ── Errors ──────────────────────────────────────────────────────────────────


class SkillServiceError(Exception):
    """Base class; ``message`` is safe to show to the user."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SkillNotFoundError(SkillServiceError):
    pass


class SkillReadOnlyError(SkillServiceError):
    pass


class SkillConflictError(SkillServiceError):
    pass


class SkillInvalidError(SkillServiceError):
    """Authored ``SKILL.md`` or name fails strict validation."""

    def __init__(self, diagnostics: Sequence[SkillDiagnostic]) -> None:
        self.diagnostics = list(diagnostics)
        super().__init__("; ".join(item.message for item in self.diagnostics))


class SkillBundleError(SkillServiceError):
    """A bundle file operation was rejected (bad path, encoding, limits)."""


class SkillTooLargeError(SkillServiceError):
    pass


# ── Catalog projection ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillView:
    """One discovered Skill plus the management facts the API reports."""

    skill: Skill
    provider: ManagedResourceProvider | None
    editable: bool


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(
            str(right.resolve())
        )
    except OSError:
        return False


def _managed_provider(
    skill: Skill,
    providers: dict[tuple[str, str], ManagedResourceProvider],
) -> ManagedResourceProvider | None:
    """Conductor provenance, only when discovery selected the managed bundle.

    Conductor writes Skills into the user skills root under their slug. A
    same-named project Skill that shadows it is user-owned, not managed.
    """

    provider = providers.get(("skill", skill.name))
    if provider is None:
        return None
    managed_location = agent_fs.skills_dir() / skill.name / "SKILL.md"
    return provider if _same_path(skill.location, managed_location) else None


def _inside_real_root(skill: Skill) -> bool:
    """Whether ``SKILL.md`` sits in a real (non-symlinked) editable root.

    Discovery follows symlinked bundles and roots, but Settings must never
    turn such a link into an arbitrary host-file write or delete.
    """

    root = skill.root
    try:
        if root.is_symlink():
            return False
        relative = skill.location.relative_to(root)
    except (OSError, ValueError):
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        skill.location.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _view(
    skill: Skill,
    providers: dict[tuple[str, str], ManagedResourceProvider],
) -> SkillView:
    provider = _managed_provider(skill, providers)
    editable = (
        provider is None
        and skill.editable
        and not skill.symlinked
        and skill.source in {"project", "user"}
        and _inside_real_root(skill)
    )
    return SkillView(skill=skill, provider=provider, editable=editable)


def _catalog(workspaces: Iterable[Path]) -> SkillCatalog:
    return discover_skills(list(workspaces))


def _require(catalog: SkillCatalog, name: str) -> Skill:
    skill = catalog.get(name)
    if skill is None:
        raise SkillNotFoundError(f"Skill '{name}' not found.")
    return skill


def _summary_fields(view: SkillView) -> dict:
    skill = view.skill
    return {
        "name": skill.name,
        "description": skill.description,
        "location": str(skill.location),
        "source": skill.source,
        "plugin_id": skill.plugin_id,
        "enabled": skill.enabled,
        "model_invocable": not skill.disable_model_invocation,
        "user_invocable": skill.user_invocable,
        "license": skill.license,
        "compatibility": skill.compatibility,
        "allowed_tools": skill.allowed_tools,
        "metadata": dict(skill.metadata),
        "valid": skill.valid,
        "diagnostics": [
            SkillDiagnosticModel(
                code=item.code, message=item.message, severity=item.severity
            )
            for item in skill.diagnostics
        ],
        "shadowed_paths": [str(path) for path in skill.shadowed],
        "editable": view.editable,
        "symlinked": skill.symlinked,
        "resource_count": agent_fs.count_skill_bundle_files(skill.directory),
        "provider": view.provider,
    }


def _summary(view: SkillView) -> SkillSummary:
    return SkillSummary(**_summary_fields(view))


def _read_skill_text(path: Path) -> str:
    """Read one ``SKILL.md`` under the runtime size limit."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SkillNotFoundError(f"SKILL.md not found: {exc}") from exc
    if size > MAX_SKILL_FILE_BYTES:
        raise SkillTooLargeError(
            f"SKILL.md exceeds the {MAX_SKILL_FILE_BYTES}-byte limit."
        )
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_SKILL_FILE_BYTES + 1)
    except OSError as exc:
        raise SkillNotFoundError(f"SKILL.md could not be read: {exc}") from exc
    if len(payload) > MAX_SKILL_FILE_BYTES:
        raise SkillTooLargeError(
            f"SKILL.md exceeds the {MAX_SKILL_FILE_BYTES}-byte limit."
        )
    # A non-UTF-8 file is still shown (and is invalid in the catalog) so the
    # user can see what is wrong and repair or delete it. Newlines are
    # normalized like ``Path.read_text`` so the editor sees one convention.
    text = payload.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _detail(view: SkillView) -> SkillDetail:
    fields = _summary_fields(view)
    content = _read_skill_text(view.skill.location)
    try:
        records = agent_fs.list_skill_bundle_files(view.skill.directory)
    except AgentFsNotFoundError as exc:
        raise SkillNotFoundError(str(exc)) from exc
    files = [
        SkillBundleFile(
            path=record.path,
            size=record.size,
            media_type=record.media_type,
            content=record.content,
            encoding=record.encoding,
            editable=view.editable and record.editable,
        )
        for record in records
    ]
    return SkillDetail(
        **fields,
        content=content,
        files=files,
        bundle_truncated=int(fields["resource_count"]) > len(files),
    )


def _view_after_write(
    name: str, location: Path, workspaces: Sequence[Path]
) -> SkillView:
    """Return the view of the bundle just written, even when it is shadowed."""

    providers = managed_resource_providers()
    skill = _catalog(workspaces).get(name)
    if skill is None or not _same_path(skill.location, location):
        root = location.parent.parent
        skill = discover_skills(roots=[SkillRoot(root, "user", editable=True)]).get(
            name
        )
    if skill is None:
        raise SkillNotFoundError(f"Skill '{name}' not found after writing it.")
    return _view(skill, providers)


# ── Reads ───────────────────────────────────────────────────────────────────


def list_skills(workspaces: Sequence[Path]) -> list[SkillSummary]:
    """Every discovered Skill winner, valid or not, sorted by name."""

    providers = managed_resource_providers()
    return [_summary(_view(skill, providers)) for skill in _catalog(workspaces).all()]


def get_skill(name: str, workspaces: Sequence[Path]) -> SkillDetail:
    skill = _require(_catalog(workspaces), name)
    return _detail(_view(skill, managed_resource_providers()))


# ── Writes ──────────────────────────────────────────────────────────────────


def _validate_content(content: str, *, directory_name: str, name: str) -> None:
    definition, errors = validate_skill_text(content, directory_name=directory_name)
    if errors:
        raise SkillInvalidError(errors)
    if definition is not None and definition.name != name:
        raise SkillInvalidError(
            [
                SkillDiagnostic(
                    "name-mismatch",
                    f"Frontmatter name '{definition.name}' must be '{name}'.",
                    "error",
                )
            ]
        )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        existing_mode = 0o644
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.chmod(existing_mode)
    temporary.replace(path)


def _assert_create_target_available(name: str, target: Path) -> None:
    if target.is_symlink():
        raise SkillConflictError(f"Skill bundle path for '{name}' is a symlink.")
    if (target / "SKILL.md").exists():
        raise SkillConflictError(f"Skill '{name}' already exists.")
    if not target.exists():
        return
    if not target.is_dir():
        raise SkillConflictError(
            f"Skill bundle path for '{name}' is not an editable directory."
        )
    if any(target.iterdir()):
        raise SkillConflictError(
            f"Skill bundle directory for '{name}' already contains files."
        )


def _stage_bundle(
    target: Path,
    *,
    content: str,
    files: Sequence[SkillBundleFileWrite],
    deleted_files: Sequence[str],
    directory_name: str,
    name: str,
) -> None:
    """Build the complete bundle in a sibling directory, then swap it in.

    All decoding, path validation and writes happen in the staging directory,
    so a bad resource cannot leave a half-written bundle behind.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
    )
    backup: Path | None = None
    try:
        if target.is_dir():
            shutil.copytree(
                target,
                staging,
                dirs_exist_ok=True,
                symlinks=True,
                copy_function=shutil.copy2,
            )
        staged_skill = staging / "SKILL.md"
        _atomic_write(staged_skill, content)
        agent_fs.apply_skill_bundle_files(
            staging,
            [(item.path, item.content, item.encoding) for item in files],
            list(deleted_files),
        )
        agent_fs.assert_skill_bundle_limits(staging)
        # Re-validate the staged bytes so the published bundle is exactly
        # what strict validation accepted.
        staged_content = _read_skill_text(staged_skill)
        _validate_content(staged_content, directory_name=directory_name, name=name)

        if target.exists():
            backup = target.parent / f".{target.name}.backup-{uuid4().hex}"
            target.replace(backup)
        try:
            staging.replace(target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup is not None:
            # The new bundle is already visible; a cleanup failure must not
            # report a committed write as failed.
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
    except (AgentFsPathError, AgentFsConflictError, AgentFsNotFoundError) as exc:
        raise SkillBundleError(str(exc)) from exc
    except OSError as exc:
        raise SkillBundleError(f"Could not write Skill bundle: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists() and not target.exists():
            backup.replace(target)


def _require_editable(view: SkillView) -> None:
    skill = view.skill
    if view.provider is not None:
        raise SkillReadOnlyError(
            f"Skill '{skill.name}' is managed by Conductor project "
            f"'{view.provider.project_name}' and cannot be changed locally."
        )
    if not view.editable:
        reason = (
            "it is symlinked" if skill.symlinked else f"it is a {skill.source} Skill"
        )
        raise SkillReadOnlyError(f"Skill '{skill.name}' is read-only because {reason}.")


def create_skill(
    name: str,
    content: str,
    files: Sequence[SkillBundleFileWrite],
    workspaces: Sequence[Path],
) -> SkillDetail:
    """Create a new Skill in the user skills root."""

    problems = name_problems(name)
    if problems:
        raise SkillInvalidError(problems)
    _validate_content(content, directory_name=name, name=name)
    target = user_skills_dir().absolute() / name
    _assert_create_target_available(name, target)
    _stage_bundle(
        target,
        content=content,
        files=files,
        deleted_files=(),
        directory_name=name,
        name=name,
    )
    team_manager.invalidate_skill_cache()
    logger.info("skill_created name={} location={}", name, target / "SKILL.md")
    return _detail(_view_after_write(name, target / "SKILL.md", workspaces))


def update_skill(
    name: str,
    content: str,
    files: Sequence[SkillBundleFileWrite],
    deleted_files: Sequence[str],
    workspaces: Sequence[Path],
) -> SkillDetail:
    """Replace ``SKILL.md`` and apply bundle file changes of an editable Skill."""

    skill = _require(_catalog(workspaces), name)
    view = _view(skill, managed_resource_providers())
    _require_editable(view)
    directory = skill.directory
    _validate_content(content, directory_name=directory.name, name=name)
    _stage_bundle(
        directory,
        content=content,
        files=files,
        deleted_files=deleted_files,
        directory_name=directory.name,
        name=name,
    )
    team_manager.invalidate_skill_cache()
    logger.info("skill_updated name={} location={}", name, skill.location)
    return _detail(_view_after_write(name, skill.location, workspaces))


def set_enabled(name: str, enabled: bool, workspaces: Sequence[Path]) -> SkillDetail:
    """Turn any discovered Skill on or off, including read-only ones."""

    _require(_catalog(workspaces), name)
    try:
        set_skill_enabled(name, enabled)
    except (SkillSettingsError, OSError) as exc:
        raise SkillConflictError(
            f"Could not save the enabled state of Skill '{name}': {exc}"
        ) from exc
    team_manager.invalidate_skill_cache()
    logger.info("skill_enabled_changed name={} enabled={}", name, enabled)
    skill = _require(_catalog(workspaces), name)
    return _detail(_view(skill, managed_resource_providers()))


def delete_skill(name: str, workspaces: Sequence[Path]) -> None:
    """Delete an editable Skill bundle and forget its disabled switch."""

    skill = _require(_catalog(workspaces), name)
    view = _view(skill, managed_resource_providers())
    _require_editable(view)
    directory = skill.directory
    if directory.is_symlink() or not directory.is_dir():
        raise SkillReadOnlyError(f"Skill '{name}' is not a deletable directory.")
    try:
        shutil.rmtree(directory)
    except OSError as exc:
        raise SkillBundleError(f"Could not delete Skill '{name}': {exc}") from exc
    try:
        set_skill_enabled(name, True)
    except (SkillSettingsError, OSError) as exc:
        logger.warning(
            "skill_delete_settings_cleanup_failed name={} error={}", name, exc
        )
    team_manager.invalidate_skill_cache()
    logger.info("skill_deleted name={} location={}", name, skill.location)


__all__ = [
    "SkillBundleError",
    "SkillConflictError",
    "SkillInvalidError",
    "SkillNotFoundError",
    "SkillReadOnlyError",
    "SkillServiceError",
    "SkillTooLargeError",
    "SkillView",
    "create_skill",
    "delete_skill",
    "get_skill",
    "list_skills",
    "set_enabled",
    "update_skill",
]
