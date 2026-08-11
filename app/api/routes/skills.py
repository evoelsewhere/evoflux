"""Skill CRUD + runtime-visible catalog for Settings.

The runtime skill loader sees multiple roots (project/global EvoFlux,
opencode, bundled). The Settings list mirrors that full catalog. Non-bundled
skills are edited/deleted in place; bundled skills remain read-only.
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.skill_scope import (
    ALL_SKILL_MODES,
    SKILL_SCOPE_FILENAME,
    SkillMode,
    normalize_skill_modes,
    serialize_skill_modes,
)
from app.core.skill_settings import (
    SkillSettingsError,
    delete_skill_runtime_settings,
    write_skill_runtime_settings,
)

from app.api.schemas.skills import (
    SkillDeleteResponse,
    SkillBundleFile,
    SkillDetail,
    SkillListResponse,
    SkillRuntimeSettingsRequest,
    SkillSummary,
    SkillUpdateRequest,
    SkillWriteRequest,
)
from app.services import agent_fs, team_manager
from app.services.agent_fs import (
    AgentFsConflictError,
    AgentFsNotFoundError,
    AgentFsPathError,
)

router = APIRouter()
_PORTABLE_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _builtin_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "agent" / "builtin_skills"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _skill_source(path: Path) -> str:
    """Return a user-facing source label for a discovered SKILL.md path."""
    from app.agent.tools.builtin import skill as skill_module

    resolved = path.resolve()
    config_skills = Path(settings.SKILLS_DIR).resolve()
    config_dir = Path(settings.EVOFLUX_CONFIG_DIR).resolve()
    opencode_global = Path.home() / ".config" / "opencode" / "skills"
    agents_global = Path.home() / ".agents" / "skills"
    claude_global = Path.home() / ".claude" / "skills"
    project_root = skill_module._project_root().resolve()
    if _is_relative_to(resolved, project_root / ".evoflux" / "skills"):
        return "project-EvoFlux"
    if _is_relative_to(resolved, project_root / ".opencode" / "skills"):
        return "project-opencode"
    if _is_relative_to(resolved, project_root / ".agents" / "skills"):
        return "project-agents"
    if _is_relative_to(resolved, project_root / ".claude" / "skills"):
        return "project-claude"
    if _is_relative_to(resolved, config_skills):
        return "global-EvoFlux"
    if _is_relative_to(resolved, opencode_global):
        return "global-opencode"
    if _is_relative_to(resolved, agents_global):
        return "global-agents"
    if _is_relative_to(resolved, claude_global):
        return "global-claude"
    if _is_relative_to(resolved, Path("/etc/codex/skills")):
        return "admin-codex"
    if _is_relative_to(resolved, _builtin_skills_root()):
        return "builtin"
    if _is_relative_to(resolved, config_dir):
        return "global-EvoFlux"
    return "unknown"


def _editable_skill_root(
    path: Path, *, roots: Sequence[Path] | None = None
) -> Path | None:
    """Return the writable discovery root containing *path*, if any.

    Discovery intentionally supports symlinked skill bundles, matching Codex,
    but Settings must never turn such a read-only discovery link into an
    arbitrary host-file write/delete primitive.
    """

    from app.agent.tools.builtin import skill as skill_module

    absolute = path.absolute()
    try:
        runtime_metadata = json.loads(
            (absolute.parent / ".evoflux.json").read_text(encoding="utf-8")
        )
        if runtime_metadata.get("managed_by") == "conductor":
            return None
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass
    for root in roots or skill_module._iter_skill_roots():
        if root.absolute() in {
            _builtin_skills_root().absolute(),
            Path("/etc/codex/skills").absolute(),
        }:
            continue
        try:
            if root.absolute().is_symlink():
                continue
        except OSError:
            continue
        try:
            relative = absolute.relative_to(root.absolute())
        except ValueError:
            continue
        current = root.absolute()
        unsafe = False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                unsafe = True
                break
        if unsafe:
            return None
        try:
            absolute.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        return root
    return None


def _is_editable_skill(path: Path, *, roots: Sequence[Path] | None = None) -> bool:
    return _editable_skill_root(path, roots=roots) is not None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        existing_mode = 0o644
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.chmod(existing_mode)
    tmp_path.replace(path)


def _write_skill_modes(skill_dir: Path, modes: object) -> None:
    """Persist non-default mode scope without changing portable SKILL.md."""

    normalized = normalize_skill_modes(modes)
    sidecar = skill_dir / SKILL_SCOPE_FILENAME
    if normalized == ALL_SKILL_MODES:
        sidecar.unlink(missing_ok=True)
        return
    _atomic_write(sidecar, serialize_skill_modes(normalized))


def _delete_skill_bundle(name: str, path: Path, *, root: Path | None = None) -> None:
    """Delete a complete skill bundle while preserving sibling sub-skills."""
    if not path.is_file():
        raise AgentFsNotFoundError(f"Skill '{name}' not found.")
    skill_dir = path.parent
    if "/" in name:
        shutil.rmtree(skill_dir)
    else:
        for child in skill_dir.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        try:
            skill_dir.rmdir()
        except OSError:
            pass

    parent = skill_dir.parent
    if root is not None:
        resolved_root = root.resolve()
        try:
            parent.resolve().relative_to(resolved_root)
        except ValueError:
            return
        while parent.resolve() != resolved_root:
            next_parent = parent.parent
            try:
                parent.rmdir()
            except OSError:
                break
            parent = next_parent


def _workspace_paths(workspaces: Sequence[str] | None) -> list[Path]:
    """Resolve explicit API workspace roots without guessing a repository."""

    resolved: list[Path] = []
    seen: set[str] = set()
    for workspace in workspaces or ():
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"Workspace does not exist or is not a directory: {path}",
            )
        key = str(path)
        if key not in seen:
            seen.add(key)
            resolved.append(path)
    return resolved


def _discovery_roots(workspaces: Sequence[Path] | None = None) -> list[Path]:
    """Return API discovery roots matching the runtime precedence contract."""

    from app.agent.skills.discovery import standard_skill_roots
    from app.agent.tools.builtin import skill as skill_module

    skill_module._SKILLS_DIR = Path(settings.SKILLS_DIR)
    if workspaces:
        return standard_skill_roots(
            workspace_roots=list(workspaces),
            evoflux_global=Path(settings.SKILLS_DIR),
        )
    # Preserve the active sandbox roots when this helper is called inside an
    # agent context, and the test/runtime compatibility hook otherwise.
    return skill_module._iter_skill_roots()


def _project_records_without_mode(records: dict) -> dict[str, dict]:
    """Project collision candidates into an honest all-mode API catalog.

    A higher-precedence Coding-only bundle must not hide a lower-precedence
    Work implementation (or vice versa). Without an explicit mode, expose the
    global winner's metadata but union the modes that have a valid effective
    implementation and surface a diagnostic when those implementations differ.
    """

    from app.agent.skills.discovery import select_skill_records_for_mode

    selected_by_mode = {
        mode: select_skill_records_for_mode(records, mode) for mode in ALL_SKILL_MODES
    }
    projected: dict[str, dict] = {}
    for name, winner in records.items():
        mode_records = [
            (mode, selected_by_mode[mode].get(name)) for mode in ALL_SKILL_MODES
        ]
        # Management always represents the actual precedence winner. Effective
        # Work/Coding/AIM availability is still projected below, but a broken
        # higher-precedence bundle must remain visible and repairable instead
        # of being disguised as a lower valid fallback.
        representative = winner
        info = representative.as_legacy_dict()
        effective_modes = [mode for mode, record in mode_records if record is not None]
        if effective_modes:
            info["modes"] = effective_modes
        variants = {
            str(record.skill_file)
            for _mode, record in mode_records
            if record is not None
        }
        if len(variants) > 1:
            diagnostics = list(info.get("diagnostics") or [])
            diagnostics.append(
                {
                    "code": "mode-specific-collision",
                    "message": (
                        "Different precedence candidates implement this skill in "
                        "different application modes; request the catalog with an explicit mode "
                        "to inspect the effective bundle."
                    ),
                    "severity": "warning",
                }
            )
            info["diagnostics"] = diagnostics
            info["shadowed_paths"] = sorted(variants - {str(representative.skill_file)})
        projected[name] = info
    return projected


def _discover_runtime_skills(
    workspaces: Sequence[Path] | None = None,
    *,
    mode: SkillMode | None = None,
) -> dict[str, dict]:
    """Discover skills using explicit workspace roots when provided.

    The skill tool stores the EvoFlux-global skills directory in a module
    binding for performance and historical monkeypatching tests. Settings API
    tests (and runtime config edits) may patch ``settings.SKILLS_DIR`` after
    import, so keep the binding in sync before discovery.
    """
    from app.agent.skills.discovery import select_skill_records_for_mode
    from app.plugin_platform.skills import discover_skill_records_with_plugins

    records = discover_skill_records_with_plugins(_discovery_roots(workspaces))
    if mode is not None:
        records = select_skill_records_for_mode(records, mode)
        return {name: record.as_legacy_dict() for name, record in records.items()}
    return _project_records_without_mode(records)


def _discover_management_skill(
    workspaces: Sequence[Path],
    name: str,
    *,
    mode: SkillMode | None,
) -> dict | None:
    """Resolve one Settings target without weakening agent runtime selection.

    Unscoped management returns the actual precedence winner, including an
    invalid one. Explicit modes retain runtime-valid collision selection and
    fall back to the winner only when that mode has no usable implementation.
    """

    from app.agent.skills.discovery import select_skill_records_for_mode
    from app.plugin_platform.skills import discover_skill_records_with_plugins

    records = discover_skill_records_with_plugins(_discovery_roots(workspaces))
    winner = records.get(name)
    if winner is None:
        return None
    if mode is None:
        return _project_records_without_mode(records).get(name)
    selected = select_skill_records_for_mode(records, mode).get(name)
    if selected is not None:
        return selected.as_legacy_dict()
    # No valid implementation exists in this mode. Fall back to the actual
    # precedence winner only when it is invalid, so an invalid-only bundle
    # remains repairable without making a valid out-of-mode skill reappear.
    return winner.as_legacy_dict() if not winner.valid else None


def _validate_skill_route_name(name: str) -> None:
    """Validate route syntax without following a discovered bundle symlink."""
    try:
        agent_fs.validate_skill_name(name)
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_new_skill_name(name: str) -> None:
    """Require new packages to use the portable Agent Skills identity form."""

    if len(name) > 64 or _PORTABLE_SKILL_NAME_RE.fullmatch(name) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "New skill names must be 1-64 lowercase letters, digits, and "
                "single hyphens (for example 'release-audit')."
            ),
        )


def _parse_skill(name: str, content: str) -> tuple[str, str | None]:
    """Return ``(description, error)`` from a SKILL.md body."""
    from app.agent.skills.discovery import (
        MAX_DESCRIPTION_CHARS,
        MAX_SKILL_FILE_BYTES,
    )
    from app.agent.tools.builtin.skill import _parse_frontmatter

    try:
        encoded_size = len(content.encode("utf-8"))
    except UnicodeEncodeError as exc:
        return "", f"SKILL.md is not valid UTF-8 text: {exc}"
    if encoded_size > MAX_SKILL_FILE_BYTES:
        return "", (f"SKILL.md exceeds the {MAX_SKILL_FILE_BYTES}-byte runtime limit.")

    try:
        meta, instructions = _parse_frontmatter(content)
    except Exception as exc:
        return "", f"Invalid frontmatter: {exc}"

    if not isinstance(meta, dict):
        return "", "Frontmatter must be a YAML mapping."

    frontmatter_name = meta.get("name")
    if not isinstance(frontmatter_name, str) or not frontmatter_name.strip():
        return "", "Frontmatter field 'name' is required and must be a string."
    desc = meta.get("description")
    if not isinstance(desc, str):
        return "", "Frontmatter field 'description' is required and must be a string."
    desc = desc.strip()
    if not desc:
        return "", "Frontmatter field 'description' must not be empty."
    if len(desc) > MAX_DESCRIPTION_CHARS:
        return "", (
            f"Frontmatter field 'description' exceeds {MAX_DESCRIPTION_CHARS} characters."
        )
    if frontmatter_name != name:
        return desc, (
            f"Frontmatter name '{frontmatter_name}' does not match directory "
            f"name '{name}'."
        )
    if not instructions.strip():
        return desc, "SKILL.md instructions must not be empty."
    return desc, None


def _bundle_files(path: Path, *, editable: bool) -> list[SkillBundleFile]:
    return [
        SkillBundleFile(
            path=file.path,
            size=file.size,
            media_type=file.media_type,
            content=file.content,
            encoding=file.encoding,
            editable=editable and file.editable,
        )
        for file in agent_fs.list_skill_bundle_files(path.parent)
    ]


def _runtime_metadata(info: dict) -> dict:
    """Project canonical registry metadata into API response fields."""

    return {
        "display_name": info.get("display_name"),
        "short_description": info.get("short_description"),
        "default_prompt": info.get("default_prompt"),
        "allow_implicit_invocation": bool(info.get("allow_implicit_invocation", True)),
        "user_invocable": bool(info.get("user_invocable", True)),
        "settings_id": str(info.get("settings_id") or ""),
        "settings_editable": bool(info.get("settings_editable", True)),
        "settings_overridden": bool(info.get("settings_overridden", False)),
        "resource_count": int(info.get("resource_count", 0) or 0),
        "dependencies": list(info.get("dependencies") or []),
        "symlinked": bool(info.get("symlinked", False)),
        "diagnostics": list(info.get("diagnostics") or []),
        "shadowed_paths": list(info.get("shadowed_paths") or []),
    }


def _apply_bundle_updates(
    path: Path, body: SkillWriteRequest | SkillUpdateRequest
) -> None:
    agent_fs.apply_skill_bundle_files(
        path.parent,
        [(file.path, file.content, file.encoding) for file in body.files],
        body.deleted_files,
    )


def _read_skill_text(path: Path) -> str:
    """Read one SKILL.md under the same hard limit as runtime activation."""

    from app.agent.skills.discovery import MAX_SKILL_FILE_BYTES

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AgentFsNotFoundError(str(exc)) from exc
    if size > MAX_SKILL_FILE_BYTES:
        raise AgentFsPathError(
            f"SKILL.md exceeds the {MAX_SKILL_FILE_BYTES}-byte runtime limit."
        )
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise AgentFsPathError(f"SKILL.md is not valid UTF-8 text: {exc}") from exc


def _skill_detail_from_info(
    name: str,
    info: dict,
    *,
    roots: Sequence[Path],
) -> SkillDetail:
    """Build a detail response for one exact, already-resolved variant."""

    path = Path(str(info.get("dir", ""))) / "SKILL.md"
    try:
        content = _read_skill_text(path)
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    description, parse_error = _parse_skill(name, content)
    registry_error = info.get("error")
    source = str(info.get("source") or _skill_source(path))
    editable = bool(info.get("editable", False)) and _is_editable_skill(
        path, roots=roots
    )
    files = _bundle_files(path, editable=editable)
    return SkillDetail(
        name=name,
        path=str(path),
        content=content,
        description=description,
        error=parse_error
        or (str(registry_error) if registry_error is not None else None),
        built_in=source == "builtin",
        editable=editable,
        source=source,
        modes=list(info.get("modes", ALL_SKILL_MODES)),
        files=files,
        bundle_truncated=int(info.get("resource_count", 0) or 0) > len(files),
        **_runtime_metadata(info),
    )


def _runtime_skill_variant_by_settings_id(
    workspaces: Sequence[Path], settings_id: str
) -> dict | None:
    """Return one exact variant without applying a post-mutation mode filter."""

    from app.plugin_platform.skills import discover_skill_records_with_plugins

    records = discover_skill_records_with_plugins(_discovery_roots(workspaces))
    for winner in records.values():
        for candidate in (winner, *winner.alternates):
            if candidate.settings_id == settings_id:
                return candidate.as_legacy_dict()
    return None


def _assert_runtime_settings_target(
    name: str,
    info: dict,
    *,
    settings_id: str,
    mode: SkillMode | None,
) -> None:
    """Reject stale/synthetic settings targets before writing user state."""

    if not bool(info.get("valid", True)):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Skill '{name}' is invalid. Fix its bundle diagnostics before "
                "editing runtime settings."
            ),
        )
    if not bool(info.get("settings_editable", True)):
        raise HTTPException(
            status_code=403,
            detail=f"Runtime settings for skill '{name}' are read-only.",
        )
    current_id = str(info.get("settings_id") or "")
    if current_id != settings_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Skill '{name}' changed source or precedence after it was opened. "
                "Reload the skill before saving runtime settings."
            ),
        )
    has_mode_collision = any(
        diagnostic.get("code") == "mode-specific-collision"
        for diagnostic in info.get("diagnostics") or []
        if isinstance(diagnostic, dict)
    )
    if mode is None and has_mode_collision:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Skill '{name}' has different mode-specific implementations. "
                "Choose an explicit mode before editing runtime settings."
            ),
        )


def _global_skill_dir(name: str) -> Path:
    """Resolve a create target below the configured EvoFlux skills root."""

    agent_fs.validate_skill_name(name)
    root = agent_fs.skills_dir()
    target = root.joinpath(*name.split("/"))
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise AgentFsPathError(
                f"Skill bundle path for '{name}' contains a symlink."
            )
    return target


def _assert_create_target_available(name: str, target: Path) -> None:
    skill_file = target / "SKILL.md"
    if skill_file.exists():
        raise AgentFsConflictError(f"Skill '{name}' already exists.")
    if not target.exists():
        return
    if not target.is_dir() or target.is_symlink():
        raise AgentFsConflictError(
            f"Skill bundle path for '{name}' is not an editable directory."
        )
    unrelated = [
        child
        for child in target.iterdir()
        if not (
            child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file()
        )
    ]
    if unrelated:
        raise AgentFsConflictError(
            f"Skill bundle directory for '{name}' already contains files."
        )


def _stage_skill_bundle(
    name: str,
    body: SkillWriteRequest | SkillUpdateRequest,
    *,
    target: Path,
    create: bool,
) -> Path:
    """Build and atomically publish a complete skill directory.

    All decoding, path validation, and writes occur in a sibling staging
    directory. The visible bundle is swapped only after every operation has
    succeeded, so a bad resource cannot leave a new SKILL.md behind.
    """

    if create:
        _assert_create_target_available(name, target)
    elif not (target / "SKILL.md").is_file():
        raise AgentFsNotFoundError(f"Skill '{name}' not found.")
    if target.is_symlink():
        raise AgentFsPathError(f"Skill bundle for '{name}' is a symlink.")

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
        _atomic_write(staged_skill, body.content)
        _apply_bundle_updates(staged_skill, body)
        if body.modes is not None:
            _write_skill_modes(staging, body.modes)
        agent_fs.assert_skill_bundle_limits(staging)

        # Re-parse staged bytes before publishing. This keeps CRUD and runtime
        # validity in lockstep even if a future write helper transforms text.
        staged_content = _read_skill_text(staged_skill)
        _description, error = _parse_skill(name, staged_content)
        if error is not None:
            raise AgentFsPathError(error)

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
            # The new bundle is already visible. A best-effort cleanup failure
            # must not report the transaction as failed after it committed.
            shutil.rmtree(backup, ignore_errors=True)
            backup = None
        return target / "SKILL.md"
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists() and not target.exists():
            backup.replace(target)


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("")
async def list_skills(
    workspace: list[str] | None = Query(
        None,
        description="Repeat for every repository in the active workspace/project.",
    ),
    mode: SkillMode | None = Query(None),
) -> SkillListResponse:
    workspaces = _workspace_paths(workspace)
    roots = _discovery_roots(workspaces)
    rows: list[SkillSummary] = []
    for name, info in _discover_runtime_skills(workspaces, mode=mode).items():
        path = Path(str(info.get("dir", ""))) / "SKILL.md"
        source = str(info.get("source") or _skill_source(path))
        editable = bool(info.get("editable", False)) and _is_editable_skill(
            path, roots=roots
        )
        registry_error = info.get("error")
        rows.append(
            SkillSummary(
                name=name,
                description=str(info.get("description") or ""),
                valid=bool(info.get("valid", True)),
                error=str(registry_error) if registry_error is not None else None,
                built_in=source == "builtin",
                editable=editable,
                source=source,
                modes=list(info.get("modes", ALL_SKILL_MODES)),
                **_runtime_metadata(info),
            )
        )
    rows.sort(key=lambda row: row.name)
    return SkillListResponse(skills=rows)


@router.get("/{name:path}")
async def get_skill(
    name: str,
    workspace: list[str] | None = Query(
        None,
        description="Repeat for every repository in the active workspace/project.",
    ),
    mode: SkillMode | None = Query(None),
) -> SkillDetail:
    _validate_skill_route_name(name)
    workspaces = _workspace_paths(workspace)
    roots = _discovery_roots(workspaces)
    info = _discover_management_skill(workspaces, name, mode=mode)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    return _skill_detail_from_info(name, info, roots=roots)


@router.post("", status_code=201)
async def create_skill(body: SkillWriteRequest) -> SkillDetail:
    _validate_new_skill_name(body.name)
    desc, err = _parse_skill(body.name, body.content)
    if err is not None:
        raise HTTPException(status_code=422, detail=err)
    if body.deleted_files:
        raise HTTPException(
            status_code=422,
            detail="deleted_files is only valid when updating an existing skill.",
        )

    try:
        target = _global_skill_dir(body.name)
        created_path = _stage_skill_bundle(
            body.name,
            body,
            target=target,
            create=True,
        )
    except AgentFsConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentFsPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_manager.invalidate_skill_cache()
    created_info = _discover_runtime_skills().get(body.name, {})
    created_source = str(created_info.get("source") or _skill_source(created_path))
    files = _bundle_files(created_path, editable=True)
    return SkillDetail(
        name=body.name,
        path=str(created_path),
        content=body.content,
        description=desc,
        built_in=False,
        editable=True,
        source=created_source,
        modes=body.modes,
        files=files,
        bundle_truncated=int(created_info.get("resource_count", 0) or 0) > len(files),
        **_runtime_metadata(created_info),
    )


@router.put("/{name:path}")
async def update_skill(
    name: str,
    body: SkillUpdateRequest,
    workspace: list[str] | None = Query(
        None,
        description="Repeat for every repository in the active workspace/project.",
    ),
    mode: SkillMode | None = Query(None),
) -> SkillDetail:
    _validate_skill_route_name(name)
    if body.name != name:
        raise HTTPException(
            status_code=422,
            detail=f"URL name '{name}' does not match body name '{body.name}'.",
        )
    workspaces = _workspace_paths(workspace)
    roots = _discovery_roots(workspaces)
    info = _discover_management_skill(workspaces, name, mode=mode)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    existing_path = Path(str(info.get("dir", ""))) / "SKILL.md"
    if not bool(info.get("editable", False)) or not _is_editable_skill(
        existing_path, roots=roots
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Skill '{name}' is read-only because it comes from "
                f"{info.get('source') or _skill_source(existing_path)}."
            ),
        )

    desc, err = _parse_skill(name, body.content)
    if err is not None:
        raise HTTPException(status_code=422, detail=err)

    try:
        existing_path = _stage_skill_bundle(
            name,
            body,
            target=existing_path.parent,
            create=False,
        )
    except (AgentFsPathError, AgentFsConflictError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_manager.invalidate_skill_cache()
    updated_info = _discover_management_skill(workspaces, name, mode=mode) or info
    source = str(updated_info.get("source") or _skill_source(existing_path))
    files = _bundle_files(existing_path, editable=True)
    return SkillDetail(
        name=name,
        path=str(existing_path),
        content=body.content,
        description=desc,
        editable=True,
        source=source,
        built_in=source == "builtin",
        modes=list(updated_info.get("modes", ALL_SKILL_MODES)),
        files=files,
        bundle_truncated=int(updated_info.get("resource_count", 0) or 0) > len(files),
        **_runtime_metadata(updated_info),
    )


@router.patch("/{name:path}")
async def update_skill_runtime_settings(
    name: str,
    body: SkillRuntimeSettingsRequest,
    workspace: list[str] | None = Query(
        None,
        description="Repeat for every repository in the active workspace/project.",
    ),
    mode: SkillMode | None = Query(None),
) -> SkillDetail:
    """Override runtime visibility without modifying the selected bundle."""

    _validate_skill_route_name(name)
    workspaces = _workspace_paths(workspace)
    roots = _discovery_roots(workspaces)
    info = _discover_management_skill(workspaces, name, mode=mode)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    _assert_runtime_settings_target(
        name,
        info,
        settings_id=body.settings_id,
        mode=mode,
    )
    try:
        write_skill_runtime_settings(
            body.settings_id,
            name=name,
            source=str(info.get("source") or "unknown"),
            modes=body.modes,
            allow_implicit_invocation=body.allow_implicit_invocation,
            user_invocable=body.user_invocable,
        )
    except SkillSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not persist runtime settings for skill '{name}': {exc}",
        ) from exc

    team_manager.invalidate_skill_cache()
    updated_info = _runtime_skill_variant_by_settings_id(workspaces, body.settings_id)
    if updated_info is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Skill '{name}' changed source while runtime settings were saved. "
                "Reload the skill catalog."
            ),
        )
    return _skill_detail_from_info(name, updated_info, roots=roots)


def _reset_skill_runtime_settings(
    name: str,
    settings_id: str,
    *,
    workspaces: Sequence[Path],
    roots: Sequence[Path],
    mode: SkillMode | None,
) -> SkillDetail:
    """Reset and return one exact variant without mode-projection ambiguity."""

    info = _runtime_skill_variant_by_settings_id(workspaces, settings_id)
    if info is None or info.get("name") != name:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    # Always resolve reset by opaque ID. An override can remove a high-
    # precedence variant from this mode and reveal a lower same-name bundle;
    # resolving the current mode winner would then reset the wrong target.
    _assert_runtime_settings_target(
        name,
        info,
        settings_id=settings_id,
        mode=mode,
    )
    try:
        delete_skill_runtime_settings(settings_id)
    except SkillSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not reset runtime settings for skill '{name}': {exc}",
        ) from exc

    team_manager.invalidate_skill_cache()
    updated_info = _runtime_skill_variant_by_settings_id(workspaces, settings_id)
    if updated_info is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Skill '{name}' changed source while runtime settings were reset. "
                "Reload the skill catalog."
            ),
        )
    return _skill_detail_from_info(name, updated_info, roots=roots)


@router.delete("/{name:path}")
async def delete_skill(
    name: str,
    settings_id: str | None = Query(
        None,
        min_length=38,
        max_length=38,
        pattern=r"^skill_[0-9a-f]{32}$",
        description=(
            "When present, reset this exact variant's runtime settings instead "
            "of deleting the bundle."
        ),
    ),
    workspace: list[str] | None = Query(
        None,
        description="Repeat for every repository in the active workspace/project.",
    ),
    mode: SkillMode | None = Query(None),
) -> SkillDeleteResponse | SkillDetail:
    _validate_skill_route_name(name)
    workspaces = _workspace_paths(workspace)
    roots = _discovery_roots(workspaces)
    if settings_id is not None:
        return _reset_skill_runtime_settings(
            name,
            settings_id,
            workspaces=workspaces,
            roots=roots,
            mode=mode,
        )
    info = _discover_management_skill(workspaces, name, mode=mode)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found.")
    path = Path(str(info.get("dir", ""))) / "SKILL.md"
    editable_root = _editable_skill_root(path, roots=roots)
    if not bool(info.get("editable", False)) or editable_root is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Skill '{name}' is read-only because it comes from "
                f"{info.get('source') or _skill_source(path)}."
            ),
        )
    # Remove the exact variant's user layer before deleting its bundle. The
    # ID is deterministic for a source/root/name tuple, so leaving this entry
    # behind would silently resurrect old settings if the skill is recreated.
    try:
        delete_skill_runtime_settings(str(info.get("settings_id") or ""))
    except SkillSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not remove runtime settings for skill '{name}': {exc}",
        ) from exc
    try:
        _delete_skill_bundle(name, path, root=editable_root)
    except AgentFsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    team_manager.invalidate_skill_cache()
    return SkillDeleteResponse(name=name)
