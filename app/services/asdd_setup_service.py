"""Repository-local installation state for Agent Spec-Driven (ASDD).

Setup writes four things into a repository and then gets out of the way: a
manifest naming where the catalogue lives, the normative rules, the catalogue
skeleton, and the six phase Skills. All of them are tracked files, so a
collaborator who clones the repository has the method without running anything.

There is no runtime directory and no template cache. Everything ASDD needs at
run time is either a tracked file or comes from the installed package, which is
what lets an isolated worktree work exactly like the checkout it came from.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.agent.skills.discovery import MAX_SKILL_FILE_BYTES
from app.agent.skills.validation import parse_skill_definition
from app.asdd_skills import (
    ASDD_SKELETON_FILES,
    ASDD_SKILL_NAMES,
    ASDD_SKILL_REFERENCE_FILES,
    ASDD_SKILL_TEMPLATE,
    read_asdd_rules,
    read_asdd_skeleton,
    read_asdd_skill,
    read_asdd_skill_reference,
    read_asdd_skill_template,
)
from app.core.skill_scope import (
    SKILL_SCOPE_FILENAME,
    read_skill_modes_with_diagnostic,
    serialize_skill_modes,
)
from app.services.asdd_store import AsddStoreError, normalize_data_directory

ASDD_DIRECTORY = Path(".evoflux/asdd")
ASDD_MANIFEST = ASDD_DIRECTORY / "config.json"
ASDD_RULES = ASDD_DIRECTORY / "RULES.md"
ASDD_GITIGNORE = ASDD_DIRECTORY / ".gitignore"
ASDD_SKILLS_DIRECTORY = Path(".evoflux/skills")
DEFAULT_ASDD_DATA_DIRECTORY = Path("documents/asdd")

#: The write lock is the one machine-local thing ASDD creates, so the installed
#: tree carries its own ignore rule rather than relying on the repository having
#: a suitable one.
_GITIGNORE_TEXT = "locks/\n"

METHODOLOGY = "ASDD"
METHODOLOGY_NAME = "Agent Specification-Driven Development"
PRODUCT_NAME = "Agent Spec-Driven"

#: Names this product shipped under before. A manifest carrying one is not
#: broken — it was written by an older build — so it reads as an upgrade rather
#: than as damage, and Reinstall rewrites it. Refusing outright would have put
#: "Needs repair" on every repository that had ASDD installed the day before.
RENAMED_PRODUCT_NAMES: frozenset[str] = frozenset({"Agent Specs"})

_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_SKELETON_FILE_BYTES = 256 * 1024
_SKILL_SCOPE_TEXT = serialize_skill_modes(("coding",))

#: Every key a current manifest carries. A manifest missing one of these was
#: written by an older build, so setup offers repair rather than pretending the
#: installation is current.
_MANIFEST_KEYS = (
    "product",
    "methodology",
    "methodology_name",
    "data_directory",
    "skills_directory",
    "skills",
)

AsddSetupState = Literal[
    "not_initialized",
    "upgrade_required",
    "ready",
    "invalid",
]


class AsddSetupConflict(ValueError):
    """Existing repository setup cannot be overwritten without explicit repair."""


@dataclass(frozen=True, slots=True)
class AsddRepositoryTarget:
    path: str
    name: str
    display_name: str | None = None


def _manifest_text(data_directory: Path) -> str:
    payload: dict[str, Any] = {
        "product": PRODUCT_NAME,
        "methodology": METHODOLOGY,
        "methodology_name": METHODOLOGY_NAME,
        "data_directory": data_directory.as_posix(),
        "skills_directory": ASDD_SKILLS_DIRECTORY.as_posix(),
        "skills": list(ASDD_SKILL_NAMES),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _root(target: AsddRepositoryTarget) -> Path:
    root = Path(target.path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository does not exist or is not a directory: {root}")
    return root


def _safe_path(root: Path, relative: Path) -> Path:
    candidate = root / relative
    resolved_parent = candidate.parent.resolve(strict=False)
    if resolved_parent != root and root not in resolved_parent.parents:
        raise ValueError(f"ASDD setup path escapes repository: {candidate}")
    return candidate


def _reject_symlink_ancestors(root: Path, path: Path, *, label: str) -> None:
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f"{label} must not traverse a symlink: {current}")
        current = current.parent


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _skill_paths(root: Path, name: str) -> tuple[Path, Path, Path]:
    directory = _safe_path(root, ASDD_SKILLS_DIRECTORY / name)
    skill_file = _safe_path(root, ASDD_SKILLS_DIRECTORY / name / "SKILL.md")
    scope_file = _safe_path(root, ASDD_SKILLS_DIRECTORY / name / SKILL_SCOPE_FILENAME)
    return directory, skill_file, scope_file


def _skill_reference_path(root: Path, name: str, reference: str) -> Path:
    return _safe_path(root, ASDD_SKILLS_DIRECTORY / name / "references" / reference)


def _skill_template_path(root: Path, name: str) -> Path:
    """Beside `SKILL.md`, not under `references/`.

    The template is the phase's output contract, so it sits where the Skill
    points at it rather than one directory further away with the discovery
    rules.
    """

    return _safe_path(root, ASDD_SKILLS_DIRECTORY / name / ASDD_SKILL_TEMPLATE)


def _read_bounded_text(path: Path, *, limit: int, label: str) -> str:
    if path.stat().st_size > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc


def _inspect_skill_bundle(root: Path) -> tuple[list[str], str | None]:
    """Return missing standard Skills and one fail-closed validation issue.

    Missing is recoverable — setup writes it. An issue is not: a Skill that is a
    symlink, is out of scope or does not parse would hand an agent instructions
    nobody in this repository reviewed, so the installation reads as invalid
    until a human repairs it.
    """

    skills_root = _safe_path(root, ASDD_SKILLS_DIRECTORY)
    if skills_root.exists() and (skills_root.is_symlink() or not skills_root.is_dir()):
        return [], f"{ASDD_SKILLS_DIRECTORY} must be a repository-local directory"

    missing: list[str] = []
    for name in ASDD_SKILL_NAMES:
        try:
            directory, skill_file, scope_file = _skill_paths(root, name)
        except ValueError as exc:
            return [], str(exc)
        if not directory.exists():
            missing.append(name)
            continue
        if directory.is_symlink() or not directory.is_dir():
            return [], f"ASDD skill directory must be local and regular: {name}"
        if not skill_file.exists() or not scope_file.exists():
            missing.append(name)
            continue
        if skill_file.is_symlink() or not skill_file.is_file():
            return [], f"ASDD SKILL.md must be a regular file: {name}"
        if scope_file.is_symlink() or not scope_file.is_file():
            return [], f"ASDD skill scope must be a regular file: {name}"
        template_file = _skill_template_path(root, name)
        if not template_file.exists():
            missing.append(name)
            continue
        if template_file.is_symlink() or not template_file.is_file():
            return [], (
                f"ASDD skill template must be a regular file: "
                f"{name}/{ASDD_SKILL_TEMPLATE}"
            )
        reference_missing = False
        for reference in ASDD_SKILL_REFERENCE_FILES:
            try:
                reference_file = _skill_reference_path(root, name, reference)
            except ValueError as exc:
                return [], str(exc)
            if not reference_file.exists():
                reference_missing = True
                break
            if reference_file.is_symlink() or not reference_file.is_file():
                return [], (
                    f"ASDD skill reference must be a regular file: "
                    f"{name}/references/{reference}"
                )
        if reference_missing:
            missing.append(name)
            continue
        try:
            content = _read_bounded_text(
                skill_file, limit=MAX_SKILL_FILE_BYTES, label=f"{name}/SKILL.md"
            )
            _description, definition_error = parse_skill_definition(name, content)
            if definition_error:
                raise ValueError(definition_error)
            modes, scope_error = read_skill_modes_with_diagnostic(directory)
            if scope_error:
                raise ValueError(scope_error)
            if modes != ("coding",):
                raise ValueError("scope must contain only Coding mode")
        except (OSError, ValueError) as exc:
            return [], f"Invalid ASDD skill {name}: {exc}"
    return missing, None


def _inspect_skeleton(root: Path, data_directory: Path) -> tuple[list[str], str | None]:
    """Return missing catalogue files and one fail-closed validation issue."""

    missing: list[str] = []
    for name in ASDD_SKELETON_FILES:
        try:
            path = _safe_path(root, data_directory / Path(name))
        except ValueError as exc:
            return [], str(exc)
        if not path.exists():
            missing.append(name)
            continue
        if path.is_symlink() or not path.is_file():
            return [], f"ASDD catalogue file must be a regular file: {name}"
        try:
            _read_bounded_text(
                path, limit=_MAX_SKELETON_FILE_BYTES, label=f"catalogue file {name}"
            )
        except (OSError, ValueError) as exc:
            return [], str(exc)
    return missing, None


def _base_report(
    root: Path,
    target: AsddRepositoryTarget,
    data_directory: Path,
    **overrides: Any,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(root),
        "name": target.name,
        "display_name": target.display_name,
        "state": "not_initialized",
        "installed": False,
        "manifest_path": ASDD_MANIFEST.as_posix(),
        "data_directory": data_directory.as_posix(),
        "data_path": str(root / data_directory),
        "rules_path": ASDD_RULES.as_posix(),
        "skills_path": ASDD_SKILLS_DIRECTORY.as_posix(),
        "skill_names": list(ASDD_SKILL_NAMES),
        "missing_skills": [],
        "missing_catalogue_files": [],
        "issue": None,
    }
    report.update(overrides)
    return report


def inspect_repository(target: AsddRepositoryTarget) -> dict[str, Any]:
    """Report whether one repository is ready to run ASDD."""

    root = _root(target)
    data_directory = DEFAULT_ASDD_DATA_DIRECTORY
    try:
        manifest_path = _safe_path(root, ASDD_MANIFEST)
        rules_path = _safe_path(root, ASDD_RULES)
        _safe_path(root, ASDD_SKILLS_DIRECTORY)
    except ValueError as exc:
        return _base_report(
            root, target, data_directory, state="invalid", issue=str(exc)
        )

    missing_skills, skill_issue = _inspect_skill_bundle(root)
    state: AsddSetupState = "not_initialized"
    issue: str | None = None

    if manifest_path.exists():
        try:
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise ValueError("config.json must be a regular file")
            if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise ValueError("config.json exceeds 64 KiB")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("config.json must contain an object")
            if payload.get("methodology") != METHODOLOGY:
                raise ValueError(f"config.json methodology must be {METHODOLOGY}")
            if skill_issue:
                raise ValueError(skill_issue)
            if any(key not in payload for key in _MANIFEST_KEYS):
                configured = payload.get("data_directory")
                if isinstance(configured, str):
                    data_directory = normalize_data_directory(configured)
                state = "upgrade_required"
                issue = "ASDD setup needs the current manifest"
            else:
                if payload.get("methodology_name") != METHODOLOGY_NAME:
                    raise ValueError(
                        f"config.json methodology_name must be {METHODOLOGY_NAME}"
                    )
                product = payload.get("product")
                renamed = product in RENAMED_PRODUCT_NAMES
                if product != PRODUCT_NAME and not renamed:
                    raise ValueError(f"config.json product must be {PRODUCT_NAME}")
                data_directory = normalize_data_directory(
                    str(payload.get("data_directory") or "")
                )
                if payload.get("skills_directory") != ASDD_SKILLS_DIRECTORY.as_posix():
                    raise ValueError("config.json skills_directory is not portable")
                if renamed:
                    state = "upgrade_required"
                    issue = f"ASDD setup predates the rename to {PRODUCT_NAME}"
                elif list(payload.get("skills") or []) != list(ASDD_SKILL_NAMES):
                    state = "upgrade_required"
                    issue = "ASDD setup needs the current Skill set"
                elif not rules_path.is_file() or rules_path.is_symlink():
                    state = "upgrade_required"
                    issue = "ASDD rules file is missing"
                else:
                    state = "ready"
        except (AsddStoreError, ValueError, OSError) as exc:
            return _base_report(
                root, target, data_directory, state="invalid", issue=str(exc)
            )
    elif skill_issue:
        return _base_report(
            root, target, data_directory, state="invalid", issue=skill_issue
        )

    missing_catalogue, catalogue_issue = _inspect_skeleton(root, data_directory)
    if catalogue_issue:
        return _base_report(
            root, target, data_directory, state="invalid", issue=catalogue_issue
        )

    if state == "ready" and (missing_skills or missing_catalogue):
        state = "upgrade_required"
        issue = "ASDD setup is missing installed files"

    return _base_report(
        root,
        target,
        data_directory,
        state=state,
        installed=state == "ready",
        missing_skills=missing_skills,
        missing_catalogue_files=missing_catalogue,
        issue=issue,
    )


def inspect_repositories(targets: list[AsddRepositoryTarget]) -> list[dict[str, Any]]:
    return [inspect_repository(target) for target in targets]


def initialize_repositories(
    targets: list[AsddRepositoryTarget],
    *,
    data_directory: str | Path | None = None,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    """Write what is missing, keep what is present, and report the result.

    Setup never migrates. A repository that wants the current bundle repairs with
    `overwrite`, which rewrites the installed files but never touches a change or
    a capability spec — those belong to the repository, not to the installer.
    """

    requested = (
        normalize_data_directory(data_directory) if data_directory is not None else None
    )
    inspected = inspect_repositories(targets)
    invalid = [item for item in inspected if item["state"] == "invalid"]
    if invalid and not overwrite:
        names = ", ".join(item["display_name"] or item["name"] for item in invalid)
        raise AsddSetupConflict(
            f"ASDD setup needs repair in: {names}. Retry with overwrite=true."
        )

    by_path = {item["path"]: item for item in inspected}
    for target in targets:
        root = _root(target)
        current = by_path[str(root)]
        selected = requested or normalize_data_directory(
            current.get("data_directory") or DEFAULT_ASDD_DATA_DIRECTORY
        )
        if (
            current["state"] == "ready"
            and requested is not None
            and current["data_directory"] != selected.as_posix()
            and not overwrite
        ):
            raise AsddSetupConflict(
                f"Changing the ASDD data_directory in {target.name} requires "
                "overwrite=true after reviewing the existing catalogue."
            )

        data_path = _safe_path(root, selected)
        resolved_data = data_path.resolve(strict=False)
        if resolved_data != root and root not in resolved_data.parents:
            raise ValueError(f"ASDD data_directory escapes repository: {data_path}")
        if data_path.is_symlink():
            raise ValueError("ASDD data_directory must not be a symlink")

        for name in ASDD_SKELETON_FILES:
            skeleton_file = _safe_path(root, selected / Path(name))
            _reject_symlink_ancestors(
                root, skeleton_file, label=f"ASDD catalogue file {name}"
            )
            skeleton_file.parent.mkdir(parents=True, exist_ok=True)
            if overwrite or not skeleton_file.exists():
                _atomic_write_text(skeleton_file, read_asdd_skeleton(name))
        # `changes/archive/` exists from the start so the first archive is a move
        # into a tracked directory rather than a directory creation nobody
        # reviewed.
        (data_path / "changes" / "archive").mkdir(parents=True, exist_ok=True)

        rules_path = _safe_path(root, ASDD_RULES)
        if overwrite or not rules_path.exists() or current["state"] != "ready":
            _atomic_write_text(rules_path, read_asdd_rules())

        gitignore_path = _safe_path(root, ASDD_GITIGNORE)
        if overwrite or not gitignore_path.exists():
            _atomic_write_text(gitignore_path, _GITIGNORE_TEXT)

        for name in ASDD_SKILL_NAMES:
            _directory, skill_file, scope_file = _skill_paths(root, name)
            if overwrite or not skill_file.exists():
                _atomic_write_text(skill_file, read_asdd_skill(name))
            if overwrite or not scope_file.exists():
                _atomic_write_text(scope_file, _SKILL_SCOPE_TEXT)
            template_file = _skill_template_path(root, name)
            if overwrite or not template_file.exists():
                _atomic_write_text(template_file, read_asdd_skill_template(name))
            for reference in ASDD_SKILL_REFERENCE_FILES:
                reference_file = _skill_reference_path(root, name, reference)
                if overwrite or not reference_file.exists():
                    _atomic_write_text(
                        reference_file, read_asdd_skill_reference(name, reference)
                    )

        manifest_path = _safe_path(root, ASDD_MANIFEST)
        if overwrite or not manifest_path.exists() or current["state"] != "ready":
            # Publish the manifest last so a partial filesystem failure stays
            # visibly retryable instead of claiming a complete installation.
            _atomic_write_text(manifest_path, _manifest_text(selected))

    return inspect_repositories(targets)


def resolve_data_directory(root: str | Path) -> Path:
    """Return the catalogue location one repository's manifest declares."""

    manifest = Path(root).expanduser().resolve() / ASDD_MANIFEST
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return DEFAULT_ASDD_DATA_DIRECTORY
    if not isinstance(payload, dict):
        return DEFAULT_ASDD_DATA_DIRECTORY
    try:
        return normalize_data_directory(str(payload.get("data_directory") or ""))
    except AsddStoreError:
        return DEFAULT_ASDD_DATA_DIRECTORY


__all__ = [
    "ASDD_DIRECTORY",
    "ASDD_GITIGNORE",
    "ASDD_MANIFEST",
    "ASDD_RULES",
    "ASDD_SKILLS_DIRECTORY",
    "AsddRepositoryTarget",
    "AsddSetupConflict",
    "AsddSetupState",
    "DEFAULT_ASDD_DATA_DIRECTORY",
    "METHODOLOGY",
    "METHODOLOGY_NAME",
    "PRODUCT_NAME",
    "RENAMED_PRODUCT_NAMES",
    "initialize_repositories",
    "inspect_repositories",
    "inspect_repository",
    "resolve_data_directory",
]
