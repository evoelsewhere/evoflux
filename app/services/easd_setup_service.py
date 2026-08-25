"""Repository-local installation state for Evo Agent Specs (EASD)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from app.agent.skills.discovery import MAX_SKILL_FILE_BYTES
from app.agent.skills.validation import parse_skill_definition
from app.core.skill_scope import (
    SKILL_SCOPE_FILENAME,
    read_skill_modes_with_diagnostic,
    serialize_skill_modes,
)
from app.easd_skills import (
    EASD_SKILL_NAMES,
    EASD_TEMPLATE_NAMES,
    read_easd_rules,
    read_easd_skill,
    read_easd_template,
)


EASD_DIRECTORY = Path(".evoflux/easd")
EASD_MANIFEST = EASD_DIRECTORY / "config.json"
EASD_RULES = EASD_DIRECTORY / "RULES.md"
EASD_LOCAL_GITIGNORE = EASD_DIRECTORY / ".gitignore"
DEFAULT_EASD_DATA_DIRECTORY = Path("documents/easd")
EASD_SKILLS_DIRECTORY = Path(".evoflux/skills")
_MAX_MANIFEST_BYTES = 64 * 1024

EasdSetupState = Literal[
    "not_initialized",
    "upgrade_required",
    "ready",
    "invalid",
]

_SKILL_SCOPE_TEXT = serialize_skill_modes(("coding",))
_DATA_README_TEXT = """# Evo Agent Specs repository store

This directory is the version-controlled source of truth for EASD runs owned by
this repository. Commit Intent, immutable Spec/Plan revisions, lifecycle events,
mission snapshots, review/verification evidence, deviations, and convergence.

## Document skeleton

`<data_directory>` is this directory. It defaults to `documents/easd` and is
resolved from `.evoflux/easd/config.json`.

```text
<repository>/
├── .evoflux/
│   ├── easd/
│   │   ├── config.json
│   │   ├── RULES.md
│   │   ├── .gitignore
│   │   └── .local/                     # ignored, rebuildable
│   └── skills/
│       └── easd-{specify,plan,implement,review,verify}/
│           ├── SKILL.md
│           └── .evoflux.json
└── <data_directory>/
    ├── README.md
    ├── templates/
    │   ├── intent.yaml
    │   ├── specification.yaml
    │   ├── plan.yaml
    │   ├── run.yaml
    │   ├── mission.yaml
    │   ├── review.yaml
    │   ├── verification.yaml
    │   ├── evidence.yaml
    │   ├── deviation.yaml
    │   └── event.yaml
    └── runs/
        └── <slug>--<run-uuid>/
            ├── run.yaml                # mutable CAS lifecycle projection
            ├── intent.yaml
            ├── specifications/0001.yaml
            ├── plans/0001.yaml         # planned flow only
            ├── missions/<mission-uuid>.yaml
            ├── reviews/<evidence-uuid>.yaml
            ├── verifications/<evidence-uuid>.yaml
            ├── evidence/<evidence-uuid>.yaml
            ├── deviations/<deviation-uuid>.yaml
            ├── events/<sequence>-<event-uuid>.yaml
            └── convergence.yaml        # only after Converge
```

Later Spec/Plan revisions increment the zero-padded filename (`0002.yaml`,
`0003.yaml`, ...). Direct flow leaves `plans/` empty. Imported full drafts may
omit `intent.yaml`; phase-specific artifact directories remain empty until that
phase produces records.

Accepted Spec/Plan revisions and `convergence.yaml` are immutable. Events and
evidence are append-only. `run.yaml`, mission snapshots, and open deviations
use document hashes for compare-and-swap updates so collaborators never silently
overwrite newer repository state.

Do not store machine-specific session IDs, locks, credentials, or absolute paths
here. Rebuildable local state belongs under `.evoflux/easd/.local/`.
"""
_LOCAL_GITIGNORE_TEXT = ".local/\n"


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
        "templates_directory": (data_directory / "templates").as_posix(),
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
                if (
                    payload.get("templates_directory")
                    != (data_directory / "templates").as_posix()
                ):
                    raise ValueError(
                        "config.json templates_directory must be inside data_directory"
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
                templates_path = _safe_path(root, data_directory / "templates")
                runs_path = _safe_path(root, data_directory / "runs")
                if templates_path.is_symlink() or not templates_path.is_dir():
                    raise ValueError("EASD templates directory is missing")
                if runs_path.is_symlink() or not runs_path.is_dir():
                    raise ValueError("EASD runs directory is missing")
                missing_templates = [
                    name
                    for name in EASD_TEMPLATE_NAMES
                    if not (templates_path / name).is_file()
                    or (templates_path / name).is_symlink()
                ]
                if missing_templates:
                    raise ValueError(
                        "Missing EASD templates: " + ", ".join(missing_templates)
                    )
                if missing_skills:
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

    return {
        "path": str(root),
        "name": target.name,
        "display_name": target.display_name,
        "state": state,
        "installed": state == "ready",
        "manifest_path": str(EASD_MANIFEST),
        "data_directory": data_directory.as_posix(),
        "data_path": str(data_path),
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
        data_readme = _safe_path(root, selected_data_directory / "README.md")
        templates_directory = _safe_path(root, selected_data_directory / "templates")
        runs_directory = _safe_path(root, selected_data_directory / "runs")
        templates_directory.mkdir(parents=True, exist_ok=True)
        runs_directory.mkdir(parents=True, exist_ok=True)
        if overwrite or not data_readme.exists():
            _atomic_write_text(data_readme, _DATA_README_TEXT)
        for name in EASD_TEMPLATE_NAMES:
            template_file = _safe_path(
                root, selected_data_directory / "templates" / name
            )
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


__all__ = [
    "EASD_DIRECTORY",
    "EASD_MANIFEST",
    "EASD_RULES",
    "EASD_SKILLS_DIRECTORY",
    "DEFAULT_EASD_DATA_DIRECTORY",
    "EasdRepositoryTarget",
    "EasdSetupConflict",
    "initialize_repositories",
    "inspect_repositories",
    "inspect_repository",
    "normalize_data_directory",
]
