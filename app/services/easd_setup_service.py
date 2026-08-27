"""Repository-local installation state for Evo Agent Specs (EASD)."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml

from app.agent.skills.discovery import MAX_SKILL_FILE_BYTES
from app.agent.skills.validation import parse_skill_definition
from app.core.skill_scope import (
    SKILL_SCOPE_FILENAME,
    read_skill_modes_with_diagnostic,
    serialize_skill_modes,
)
from app.easd_skills import (
    EASD_LEGACY_OPTIONAL_SKELETON_FILES,
    EASD_SKILL_NAMES,
    EASD_SKELETON_FILES,
    EASD_TEMPLATE_NAMES,
    read_easd_rules,
    read_easd_skeleton,
    read_easd_skill,
    read_easd_template,
)


EASD_DIRECTORY = Path(".evoflux/easd")
EASD_MANIFEST = EASD_DIRECTORY / "config.json"
EASD_RULES = EASD_DIRECTORY / "RULES.md"
EASD_LOCAL_GITIGNORE = EASD_DIRECTORY / ".gitignore"
DEFAULT_EASD_DATA_DIRECTORY = Path("documents/easd")
EASD_SKILLS_DIRECTORY = Path(".evoflux/skills")
EASD_RUNTIME_DIRECTORY = EASD_DIRECTORY / ".local" / "runs"
EASD_TEMPLATES_DIRECTORY = EASD_DIRECTORY / ".local" / "templates"
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_SKELETON_FILE_BYTES = 256 * 1024
_MAX_RUNTIME_MIGRATION_RUNS = 1_000
_MAX_RUNTIME_MIGRATION_FILES = 10_000

EasdSetupState = Literal[
    "not_initialized",
    "upgrade_required",
    "ready",
    "invalid",
]

_SKILL_SCOPE_TEXT = serialize_skill_modes(("coding",))
_LOCAL_GITIGNORE_TEXT = ".local/\n"
_RUN_SUFFIX = re.compile(
    r"--(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
_KNOWLEDGE_INDEX_CONTRACT = yaml.safe_load(read_easd_skeleton("index.yaml"))
_LEGACY_KNOWLEDGE_README_SHA256 = (
    "886b1bb3b7d2e6c1939df684285a4c80c431716cdca8ecca53d85f110b4bfb8f"
)


def normalize_data_directory(value: str | Path) -> Path:
    raw = str(value).strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise ValueError("EASD data_directory must be a repository-relative path")
    if path.parts[0] == ".git" or path.parts[:3] == (".evoflux", "easd", ".local"):
        raise ValueError("EASD data_directory cannot use Git internals or local state")
    return Path(*path.parts)


def _manifest_text(data_directory: Path) -> str:
    payload: dict[str, Any] = {
        "product": "Evo Agent Specs",
        "methodology": "EASD",
        "methodology_name": "Evo Agent Specification-Driven Development",
        "data_directory": data_directory.as_posix(),
        "rules_file": str(EASD_RULES),
        "templates_directory": str(EASD_TEMPLATES_DIRECTORY),
        "runtime_storage": "local",
        "runtime_directory": str(EASD_RUNTIME_DIRECTORY),
        "publish_converged_runs": "manual",
        "skills_directory": str(EASD_SKILLS_DIRECTORY),
        "skills": list(EASD_SKILL_NAMES),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class EasdSetupConflict(ValueError):
    """Existing repository setup cannot be overwritten without explicit repair."""


@dataclass(frozen=True, slots=True)
class EasdRepositoryTarget:
    path: str
    name: str
    display_name: str | None = None


def _root(target: EasdRepositoryTarget) -> Path:
    root = Path(target.path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository does not exist or is not a directory: {root}")
    return root


def _safe_path(root: Path, relative: Path) -> Path:
    candidate = root / relative
    resolved_parent = candidate.parent.resolve(strict=False)
    if resolved_parent != root and root not in resolved_parent.parents:
        raise ValueError(f"EASD setup path escapes repository: {candidate}")
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
    directory = _safe_path(root, EASD_SKILLS_DIRECTORY / name)
    skill_file = _safe_path(root, EASD_SKILLS_DIRECTORY / name / "SKILL.md")
    scope_file = _safe_path(
        root,
        EASD_SKILLS_DIRECTORY / name / SKILL_SCOPE_FILENAME,
    )
    return directory, skill_file, scope_file


def _read_bounded_text(path: Path, *, limit: int, label: str) -> str:
    if path.stat().st_size > limit:
        raise ValueError(f"{label} exceeds {limit} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc


def _inspect_skill_bundle(root: Path) -> tuple[list[str], str | None]:
    """Return missing standard skills and one fail-closed validation issue."""

    skills_root = _safe_path(root, EASD_SKILLS_DIRECTORY)
    if skills_root.exists() and (skills_root.is_symlink() or not skills_root.is_dir()):
        return [], f"{EASD_SKILLS_DIRECTORY} must be a repository-local directory"

    missing: list[str] = []
    for name in EASD_SKILL_NAMES:
        try:
            directory, skill_file, scope_file = _skill_paths(root, name)
        except ValueError as exc:
            return [], str(exc)
        if not directory.exists():
            missing.append(name)
            continue
        if directory.is_symlink() or not directory.is_dir():
            return [], f"EASD skill directory must be local and regular: {name}"
        if not skill_file.exists() or not scope_file.exists():
            missing.append(name)
            continue
        if skill_file.is_symlink() or not skill_file.is_file():
            return [], f"EASD SKILL.md must be a regular file: {name}"
        if scope_file.is_symlink() or not scope_file.is_file():
            return [], f"EASD skill scope must be a regular file: {name}"
        try:
            content = _read_bounded_text(
                skill_file,
                limit=MAX_SKILL_FILE_BYTES,
                label=f"{name}/SKILL.md",
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
            return [], f"Invalid EASD skill {name}: {exc}"
    return missing, None


def _inspect_skeleton(
    root: Path,
    data_directory: Path,
) -> tuple[list[str], str | None]:
    """Return missing knowledge files and one fail-closed validation issue."""

    missing: list[str] = []
    for name in EASD_SKELETON_FILES:
        try:
            path = _safe_path(root, data_directory / Path(name))
            _reject_symlink_ancestors(
                root,
                path,
                label=f"EASD knowledge file {name}",
            )
        except ValueError as exc:
            return [], str(exc)
        if not path.exists():
            missing.append(name)
            continue
        if path.is_symlink() or not path.is_file() or path.parent.is_symlink():
            return [], f"EASD knowledge file must be repository-local: {name}"
        try:
            content = _read_bounded_text(
                path,
                limit=_MAX_SKELETON_FILE_BYTES,
                label=f"EASD knowledge file {name}",
            )
            parsed = (
                yaml.safe_load(content) if path.suffix in {".yaml", ".yml"} else None
            )
            if path.suffix in {".yaml", ".yml"} and not isinstance(parsed, dict):
                raise ValueError(f"EASD knowledge file {name} must contain a mapping")
            if name == "index.yaml":
                if not isinstance(parsed, dict):
                    raise ValueError("EASD knowledge index must contain a mapping")
                expected_sections = _KNOWLEDGE_INDEX_CONTRACT["sections"]
                actual_sections = parsed.get("sections")
                if not isinstance(actual_sections, dict):
                    raise ValueError("EASD knowledge index must define sections")
                mismatched = [
                    key
                    for key, expected in expected_sections.items()
                    if actual_sections.get(key) != expected
                ]
                if mismatched:
                    raise ValueError(
                        "EASD knowledge index has invalid sections: "
                        + ", ".join(mismatched)
                    )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return [], str(exc)
    return missing, None


def _normalize_knowledge_index(root: Path, data_directory: Path) -> None:
    index_path = _safe_path(root, data_directory / "index.yaml")
    if not index_path.is_file() or index_path.is_symlink():
        return
    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return
    if not isinstance(payload, dict):
        return
    changed = False
    sections = payload.get("sections")
    if isinstance(sections, dict):
        for key in ("runs", "templates"):
            if sections.get(key) == key:
                sections.pop(key)
                changed = True
    authority = payload.get("authority")
    if isinstance(authority, dict) and authority.get("execution") == "runs":
        authority["execution"] = str(EASD_RUNTIME_DIRECTORY)
        changed = True
    if changed:
        _atomic_write_text(
            index_path,
            yaml.safe_dump(
                payload,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
        )


def _normalize_knowledge_readme(root: Path, data_directory: Path) -> None:
    readme_path = _safe_path(root, data_directory / "README.md")
    if not readme_path.is_file() or readme_path.is_symlink():
        return
    try:
        content = readme_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    if hashlib.sha256(content.encode("utf-8")).hexdigest() == (
        _LEGACY_KNOWLEDGE_README_SHA256
    ):
        _atomic_write_text(readme_path, read_easd_skeleton("README.md"))


def _legacy_run_directories(root: Path, data_directory: Path) -> list[Path]:
    runs_path = _safe_path(root, data_directory / "runs")
    if not runs_path.is_dir() or runs_path.is_symlink():
        return []
    return [
        path
        for path in sorted(runs_path.iterdir())
        if path.is_dir() and not path.is_symlink() and _RUN_SUFFIX.search(path.name)
    ]


def _legacy_generated_files(root: Path, data_directory: Path) -> list[Path]:
    candidates = [
        (
            _safe_path(root, data_directory / "templates" / name),
            read_easd_template(name),
        )
        for name in EASD_TEMPLATE_NAMES
    ] + [
        (
            _safe_path(root, data_directory / Path(name)),
            read_easd_skeleton(name),
        )
        for name in EASD_LEGACY_OPTIONAL_SKELETON_FILES
    ]
    output: list[Path] = []
    for path, bundled in candidates:
        try:
            if (
                path.is_file()
                and not path.is_symlink()
                and path.read_text(encoding="utf-8") == bundled
            ):
                output.append(path)
        except (OSError, UnicodeError):
            continue
    return output


def inspect_repository(target: EasdRepositoryTarget) -> dict[str, Any]:
    root = _root(target)
    state: EasdSetupState = "not_initialized"
    issue: str | None = None
    data_directory = DEFAULT_EASD_DATA_DIRECTORY
    try:
        manifest_path = _safe_path(root, EASD_MANIFEST)
        rules_path = _safe_path(root, EASD_RULES)
        _safe_path(root, EASD_SKILLS_DIRECTORY)
    except ValueError as exc:
        return {
            "path": str(root),
            "name": target.name,
            "display_name": target.display_name,
            "state": "invalid",
            "installed": False,
            "manifest_path": str(EASD_MANIFEST),
            "data_directory": DEFAULT_EASD_DATA_DIRECTORY.as_posix(),
            "data_path": str(root / DEFAULT_EASD_DATA_DIRECTORY),
            "runtime_directory": str(EASD_RUNTIME_DIRECTORY),
            "runtime_path": str(root / EASD_RUNTIME_DIRECTORY),
            "legacy_run_count": 0,
            "legacy_generated_file_count": 0,
            "rules_path": str(EASD_RULES),
            "skills_path": str(EASD_SKILLS_DIRECTORY),
            "skill_names": list(EASD_SKILL_NAMES),
            "issue": str(exc),
        }

    missing_skills, skill_issue = _inspect_skill_bundle(root)
    if manifest_path.exists():
        try:
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise ValueError("config.json must be a regular file")
            if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                raise ValueError("config.json exceeds 64 KiB")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("config.json must contain an object")
            if payload.get("methodology") != "EASD":
                raise ValueError("config.json methodology must be EASD")
            if payload.get("product") != "Evo Agent Specs":
                raise ValueError("config.json product must be Evo Agent Specs")
            if skill_issue:
                raise ValueError(skill_issue)
            legacy_keys = {
                "schema_version",
                "skill_bundle_version",
                "rules_version",
                "template_bundle_version",
                "specs_directory",
                "store_format",
            }
            is_legacy = bool(legacy_keys & payload.keys()) or any(
                key not in payload
                for key in (
                    "data_directory",
                    "rules_file",
                    "templates_directory",
                    "runtime_storage",
                    "runtime_directory",
                    "publish_converged_runs",
                    "skills_directory",
                    "skills",
                )
            )
            if is_legacy:
                configured = payload.get("data_directory")
                if isinstance(configured, str):
                    data_directory = normalize_data_directory(configured)
                state = "upgrade_required"
                issue = "EASD setup needs the current repository-store layout"
            else:
                if (
                    payload.get("methodology_name")
                    != "Evo Agent Specification-Driven Development"
                ):
                    raise ValueError(
                        "config.json methodology_name must be "
                        "Evo Agent Specification-Driven Development"
                    )
                data_directory = normalize_data_directory(
                    str(payload.get("data_directory") or "")
                )
                if payload.get("rules_file") != str(EASD_RULES):
                    raise ValueError(f"config.json rules_file must be {EASD_RULES}")
                if payload.get("templates_directory") != str(EASD_TEMPLATES_DIRECTORY):
                    raise ValueError(
                        f"config.json templates_directory must be {EASD_TEMPLATES_DIRECTORY}"
                    )
                if payload.get("runtime_storage") != "local":
                    raise ValueError("config.json runtime_storage must be local")
                if payload.get("runtime_directory") != str(EASD_RUNTIME_DIRECTORY):
                    raise ValueError(
                        f"config.json runtime_directory must be {EASD_RUNTIME_DIRECTORY}"
                    )
                if payload.get("publish_converged_runs") != "manual":
                    raise ValueError(
                        "config.json publish_converged_runs must be manual"
                    )
                if payload.get("skills_directory") != str(EASD_SKILLS_DIRECTORY):
                    raise ValueError(
                        f"config.json skills_directory must be {EASD_SKILLS_DIRECTORY}"
                    )
                if payload.get("skills") != list(EASD_SKILL_NAMES):
                    raise ValueError(
                        "config.json skills must match current EASD skills"
                    )
                data_path = _safe_path(root, data_directory)
                resolved_data = data_path.resolve(strict=False)
                if resolved_data != root and root not in resolved_data.parents:
                    raise ValueError("EASD data_directory escapes repository")
                if data_path.is_symlink() or not data_path.is_dir():
                    raise ValueError("EASD data_directory is missing or symlinked")
                if rules_path.is_symlink() or not rules_path.is_file():
                    raise ValueError("EASD core rules are missing")
                templates_path = _safe_path(root, EASD_TEMPLATES_DIRECTORY)
                runtime_path = _safe_path(root, EASD_RUNTIME_DIRECTORY)
                if templates_path.is_symlink() or not templates_path.is_dir():
                    raise ValueError("EASD templates directory is missing")
                if runtime_path.is_symlink() or not runtime_path.is_dir():
                    raise ValueError("EASD local runtime directory is missing")
                missing_templates = [
                    name
                    for name in EASD_TEMPLATE_NAMES
                    if not (templates_path / name).exists()
                ]
                invalid_templates = [
                    name
                    for name in EASD_TEMPLATE_NAMES
                    if (templates_path / name).exists()
                    and (
                        not (templates_path / name).is_file()
                        or (templates_path / name).is_symlink()
                    )
                ]
                if invalid_templates:
                    raise ValueError(
                        "Invalid EASD templates: " + ", ".join(invalid_templates)
                    )
                missing_skeleton, skeleton_issue = _inspect_skeleton(
                    root, data_directory
                )
                if skeleton_issue:
                    raise ValueError(skeleton_issue)
                if missing_templates:
                    state = "upgrade_required"
                    issue = "Missing EASD templates: " + ", ".join(missing_templates)
                elif missing_skeleton:
                    state = "upgrade_required"
                    issue = "Missing EASD knowledge skeleton: " + ", ".join(
                        missing_skeleton
                    )
                elif missing_skills:
                    state = "upgrade_required"
                    issue = "Missing EASD skills: " + ", ".join(missing_skills)
                else:
                    state = "ready"
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            state = "invalid"
            issue = str(exc)
    elif skill_issue:
        state = "invalid"
        issue = skill_issue

    data_path = _safe_path(root, data_directory)
    runtime_path = _safe_path(root, EASD_RUNTIME_DIRECTORY)
    legacy_run_count = len(_legacy_run_directories(root, data_directory))
    legacy_generated_file_count = len(_legacy_generated_files(root, data_directory))

    return {
        "path": str(root),
        "name": target.name,
        "display_name": target.display_name,
        "state": state,
        "installed": state == "ready",
        "manifest_path": str(EASD_MANIFEST),
        "data_directory": data_directory.as_posix(),
        "data_path": str(data_path),
        "runtime_directory": str(EASD_RUNTIME_DIRECTORY),
        "runtime_path": str(runtime_path),
        "legacy_run_count": legacy_run_count,
        "legacy_generated_file_count": legacy_generated_file_count,
        "rules_path": str(EASD_RULES),
        "skills_path": str(EASD_SKILLS_DIRECTORY),
        "skill_names": list(EASD_SKILL_NAMES),
        "issue": issue,
    }


def inspect_repositories(targets: list[EasdRepositoryTarget]) -> list[dict[str, Any]]:
    return [inspect_repository(target) for target in targets]


def initialize_repositories(
    targets: list[EasdRepositoryTarget],
    *,
    data_directory: str | Path | None = None,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    requested_data_directory = (
        normalize_data_directory(data_directory) if data_directory is not None else None
    )
    inspected = inspect_repositories(targets)
    invalid = [item for item in inspected if item["state"] == "invalid"]
    if invalid and not overwrite:
        names = ", ".join(item["display_name"] or item["name"] for item in invalid)
        raise EasdSetupConflict(
            f"EASD setup needs repair in: {names}. Retry with overwrite=true."
        )

    by_path = {item["path"]: item for item in inspected}
    for target in targets:
        root = _root(target)
        manifest_path = _safe_path(root, EASD_MANIFEST)
        current = by_path[str(root)]
        selected_data_directory = requested_data_directory or normalize_data_directory(
            current.get("data_directory") or DEFAULT_EASD_DATA_DIRECTORY
        )
        if (
            current["state"] == "ready"
            and requested_data_directory is not None
            and current["data_directory"] != requested_data_directory.as_posix()
            and not overwrite
        ):
            raise EasdSetupConflict(
                f"Changing EASD data_directory in {target.name} requires "
                "overwrite=true after reviewing the existing store."
            )
        data_path = _safe_path(root, selected_data_directory)
        resolved_data = data_path.resolve(strict=False)
        if resolved_data != root and root not in resolved_data.parents:
            raise ValueError(f"EASD data_directory escapes repository: {data_path}")
        if data_path.is_symlink():
            raise ValueError("EASD data_directory must not be a symlink")
        templates_directory = _safe_path(root, EASD_TEMPLATES_DIRECTORY)
        runs_directory = _safe_path(root, EASD_RUNTIME_DIRECTORY)
        _reject_symlink_ancestors(
            root,
            templates_directory,
            label="EASD templates directory",
        )
        _reject_symlink_ancestors(
            root,
            runs_directory,
            label="EASD runs directory",
        )
        templates_directory.mkdir(parents=True, exist_ok=True)
        runs_directory.mkdir(parents=True, exist_ok=True)
        for name in EASD_SKELETON_FILES:
            skeleton_file = _safe_path(root, selected_data_directory / Path(name))
            _reject_symlink_ancestors(
                root,
                skeleton_file,
                label=f"EASD knowledge file {name}",
            )
            skeleton_file.parent.mkdir(parents=True, exist_ok=True)
            if overwrite or not skeleton_file.exists():
                _atomic_write_text(skeleton_file, read_easd_skeleton(name))
        _normalize_knowledge_index(root, selected_data_directory)
        _normalize_knowledge_readme(root, selected_data_directory)
        for name in EASD_TEMPLATE_NAMES:
            template_file = _safe_path(root, EASD_TEMPLATES_DIRECTORY / name)
            if overwrite or not template_file.exists():
                _atomic_write_text(template_file, read_easd_template(name))
        rules_path = _safe_path(root, EASD_RULES)
        if overwrite or not rules_path.exists() or current["state"] != "ready":
            _atomic_write_text(rules_path, read_easd_rules())
        gitignore_path = _safe_path(root, EASD_LOCAL_GITIGNORE)
        if overwrite or not gitignore_path.exists():
            _atomic_write_text(gitignore_path, _LOCAL_GITIGNORE_TEXT)
        for name in EASD_SKILL_NAMES:
            _directory, skill_file, scope_file = _skill_paths(root, name)
            if overwrite or not skill_file.exists():
                _atomic_write_text(skill_file, read_easd_skill(name))
            if overwrite or not scope_file.exists():
                _atomic_write_text(scope_file, _SKILL_SCOPE_TEXT)
        if overwrite or not manifest_path.exists() or current["state"] != "ready":
            # Publish the manifest last so a partial filesystem failure remains
            # visibly retryable instead of claiming a complete installation.
            _atomic_write_text(manifest_path, _manifest_text(selected_data_directory))

    return inspect_repositories(targets)


def preview_runtime_migration(
    targets: list[EasdRepositoryTarget],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for target in targets:
        root = _root(target)
        inspected = inspect_repository(target)
        if inspected["state"] not in {"ready", "upgrade_required"}:
            raise EasdSetupConflict(
                f"EASD setup must be valid before runtime migration: {target.name}"
            )
        data_directory = normalize_data_directory(inspected["data_directory"])
        generated_files = _legacy_generated_files(root, data_directory)
        entries: list[dict[str, Any]] = []
        legacy_runs = _legacy_run_directories(root, data_directory)
        if len(legacy_runs) > _MAX_RUNTIME_MIGRATION_RUNS:
            raise EasdSetupConflict(
                f"Legacy EASD Run count exceeds {_MAX_RUNTIME_MIGRATION_RUNS}: {target.name}"
            )
        migrated_file_count = 0
        for source in legacy_runs:
            files = [path for path in source.rglob("*") if path.is_file()]
            migrated_file_count += len(files)
            if migrated_file_count > _MAX_RUNTIME_MIGRATION_FILES:
                raise EasdSetupConflict(
                    f"Legacy EASD file count exceeds {_MAX_RUNTIME_MIGRATION_FILES}: {target.name}"
                )
            match = _RUN_SUFFIX.search(source.name)
            assert match is not None
            entries.append(
                {
                    "run_id": match.group("id"),
                    "name": source.name,
                    "source": source.relative_to(root).as_posix(),
                    "target": (EASD_RUNTIME_DIRECTORY / source.name).as_posix(),
                    "file_count": len(files),
                    "bytes": sum(path.stat().st_size for path in files),
                }
            )
        results.append(
            {
                "path": str(root),
                "name": target.name,
                "display_name": target.display_name,
                "legacy_run_count": len(entries),
                "runs": entries,
                "legacy_generated_file_count": len(generated_files),
                "generated_files": [
                    path.relative_to(root).as_posix() for path in generated_files
                ],
                "generated_bytes": sum(path.stat().st_size for path in generated_files),
            }
        )
    return results


def localize_legacy_runs(
    targets: list[EasdRepositoryTarget],
) -> list[dict[str, Any]]:
    previews = preview_runtime_migration(targets)
    moves: list[tuple[Path, Path]] = []
    generated_files: list[tuple[Path, Path]] = []
    for repository in previews:
        root = Path(repository["path"])
        for entry in repository["runs"]:
            source = _safe_path(root, Path(entry["source"]))
            target = _safe_path(root, Path(entry["target"]))
            if source.is_symlink() or not source.is_dir():
                raise EasdSetupConflict(
                    f"Legacy EASD Run is not a regular directory: {entry['source']}"
                )
            if any(path.is_symlink() for path in source.rglob("*")):
                raise EasdSetupConflict(
                    f"Legacy EASD Run contains a symlink: {entry['source']}"
                )
            if target.exists():
                raise EasdSetupConflict(
                    f"Local EASD Run already exists: {entry['target']}"
                )
            moves.append((source, target))
        root = Path(repository["path"])
        for relative in repository["generated_files"]:
            path = _safe_path(root, Path(relative))
            if path.is_symlink() or not path.is_file():
                raise EasdSetupConflict(
                    f"Legacy generated EASD file changed: {relative}"
                )
            generated_files.append((root, path))
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
    for root, path in generated_files:
        data_path = _safe_path(
            root,
            normalize_data_directory(
                inspect_repository(
                    EasdRepositoryTarget(path=str(root), name=root.name)
                )["data_directory"]
            ),
        )
        path.unlink()
        parent = path.parent
        while parent != data_path and parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return [
        {
            **repository,
            "moved_run_count": len(repository["runs"]),
            "removed_generated_file_count": len(repository["generated_files"]),
        }
        for repository in previews
    ]


__all__ = [
    "EASD_DIRECTORY",
    "EASD_MANIFEST",
    "EASD_RULES",
    "EASD_RUNTIME_DIRECTORY",
    "EASD_SKILLS_DIRECTORY",
    "EASD_TEMPLATES_DIRECTORY",
    "DEFAULT_EASD_DATA_DIRECTORY",
    "EasdRepositoryTarget",
    "EasdSetupConflict",
    "initialize_repositories",
    "localize_legacy_runs",
    "inspect_repositories",
    "inspect_repository",
    "normalize_data_directory",
    "preview_runtime_migration",
]
