"""KB-local AIM rulebook resolution and validation.

An AIM engagement owns exactly one rulebook at ``<kb>/rulebook/``. EvoFlux
does not ship, select, install, or fall back to a shared rulebook catalog.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.services.aim.models import AimManifest

RULEBOOK_DIRNAME = "rulebook"
TEMPLATE_RULEBOOK_ID = "project-rulebook"


class RulebookManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    version: str = Field(min_length=1)
    description: str = ""
    compare_default_profile: str = "default"


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


def _assert_rulebook_identity(
    project: AimManifest, rulebook: RulebookManifest
) -> None:
    if rulebook.id != project.rulebook.id or rulebook.version != project.rulebook.version:
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


def project_rulebook_id(project_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name.strip().lower()).strip(
        ".-_"
    )
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