"""KB-local AIM rulebook resolution and validation.

An AIM engagement owns exactly one rulebook at ``<kb>/rulebook/``. EvoFlux
does not ship, select, install, or fall back to a shared rulebook catalog.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.aim.models import AimManifest

RULEBOOK_DIRNAME = "rulebook"
TEMPLATE_RULEBOOK_ID = "project-rulebook"


class RulebookStack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stack: str = Field(min_length=1)
    language: str | None = None
    standard: str | None = None
    edition: str | None = None
    version: str | None = None
    file_extensions: list[str] = Field(default_factory=list)

    @field_validator("file_extensions")
    @classmethod
    def _validate_extensions(cls, values: list[str]) -> list[str]:
        invalid = [value for value in values if not value.startswith(".")]
        if invalid:
            raise ValueError(f"file extensions must start with '.': {invalid}")
        return values


class RulebookWorkspaceActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)

    @field_validator("skills", "workflows", "commands")
    @classmethod
    def _validate_project_paths(cls, values: list[str], info) -> list[str]:
        expected_root = Path(".evoflux") / info.field_name
        invalid = [
            value
            for value in values
            if Path(value).is_absolute()
            or ".." in Path(value).parts
            or not Path(value).is_relative_to(expected_root)
        ]
        if invalid:
            raise ValueError(
                f"{info.field_name} activation paths must be under "
                f"{expected_root.as_posix()}/: {invalid}"
            )
        return values


class RulebookManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    version: str = Field(min_length=1)
    description: str = ""
    source: RulebookStack | None = None
    target: RulebookStack | None = None
    unit_kinds: list[str] = Field(default_factory=list)
    parser_strategy: Literal["tree_sitter", "structural", "none"] = "none"
    capabilities: dict[str, str] = Field(default_factory=dict)
    compare_default_profile: str = "default"
    canonicalizers: dict[str, str] = Field(default_factory=dict)
    extractors: list[str] = Field(default_factory=list)
    runners: dict[str, str] = Field(default_factory=dict)
    mappings: dict[str, str] = Field(default_factory=dict)
    assets: dict[str, str] = Field(default_factory=dict)
    target_base: str | None = None
    ui_patterns: str | None = None
    workspace_activation: RulebookWorkspaceActivation = Field(
        default_factory=RulebookWorkspaceActivation
    )


def rulebook_dir(kb_root: Path) -> Path:
    return kb_root / RULEBOOK_DIRNAME


def read_rulebook_manifest(kb_root: Path) -> RulebookManifest:
    path = rulebook_dir(kb_root) / "rulebook.yaml"
    if not path.is_file():
        raise FileNotFoundError(
            f"AIM KB rulebook manifest is missing: {path}. "
            "Adapt the sample rulebook shipped in the KB template."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"AIM rulebook manifest is invalid: {path}: {exc}") from exc
    return RulebookManifest.model_validate(data)


def resolve_rulebook_dir(kb_root: Path) -> Path:
    rulebook = read_rulebook_manifest(kb_root)
    if (kb_root / "aim.yaml").is_file():
        from app.services.aim.kb_store import read_manifest

        _assert_rulebook_identity(read_manifest(kb_root), rulebook)
    return rulebook_dir(kb_root)


def resolve_rulebook_path(kb_root: Path, declared_path: str) -> Path:
    base = resolve_rulebook_dir(kb_root).resolve()
    relative = Path(declared_path)
    if relative.is_absolute():
        raise ValueError(f"Rulebook path must be relative: {declared_path!r}")
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Rulebook path escapes rulebook directory: {declared_path!r}")
    return resolved


def _assert_rulebook_identity(project: AimManifest, rulebook: RulebookManifest) -> None:
    if (
        rulebook.id != project.rulebook.id
        or rulebook.version != project.rulebook.version
    ):
        raise ValueError(
            "AIM rulebook identity mismatch: "
            f"aim.yaml pins {project.rulebook.id}@{project.rulebook.version}, "
            f"but rulebook/rulebook.yaml declares {rulebook.id}@{rulebook.version}."
        )


def validate_rulebook_identity(
    kb_root: Path,
    project_manifest: AimManifest | None = None,
) -> RulebookManifest:
    project = project_manifest
    if project is None:
        from app.services.aim.kb_store import read_manifest

        project = read_manifest(kb_root)
    rulebook = read_rulebook_manifest(kb_root)
    _assert_rulebook_identity(project, rulebook)
    return rulebook


def validate_unit_kind(kb_root: Path, kind: str) -> None:
    manifest = validate_rulebook_identity(kb_root)
    if manifest.unit_kinds and kind not in manifest.unit_kinds:
        raise ValueError(
            f"Unit kind {kind!r} is not allowed by rulebook {manifest.id}; "
            f"expected one of {', '.join(manifest.unit_kinds)}."
        )


def project_rulebook_id(project_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name.strip().lower()).strip(".-_")
    return f"{slug}-rulebook" if slug else "project-rulebook"


def specialize_template_rulebook(
    kb_root: Path,
    *,
    project_name: str,
) -> RulebookManifest:
    path = rulebook_dir(kb_root) / "rulebook.yaml"
    current = read_rulebook_manifest(kb_root)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["id"] = (
        project_rulebook_id(project_name)
        if current.id == TEMPLATE_RULEBOOK_ID
        else current.id
    )
    data["version"] = current.version
    if not str(data.get("description") or "").strip():
        data["description"] = f"Project-owned migration policy for {project_name}."
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return read_rulebook_manifest(kb_root)
