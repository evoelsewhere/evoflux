"""AIM project folder-layout convention + auto-detection.

The on-disk convention (user-defined, 2026-07-16): one project root folder
holds everything, named so the wizard/API can detect the three roles from a
single folder pick —

    <project_name>/
    ├─ aim_source_base/                  # ≥1 child dir, each = one legacy source repo
    │   ├─ repo-a/
    │   └─ repo-b/
    ├─ aim_<project_name>_document/      # the SHARED repo (KB) teammates clone;
    │                                    # carries aim.yaml once the project exists
    └─ aim_target_source/                # target repo, already scaffolded with the
                                         # target stack

``project_name`` is authoritative from the document repo's own name (the
``aim_{project_name}_document`` condition), not from the root folder — a
teammate may clone the layout under any root dirname; a mismatch is
surfaced as a warning, not an error.

Detection is pure filesystem inspection (no DB). When the document repo
already contains ``aim.yaml`` the detection also proposes an
identity → local-path mapping so a join needs zero manual re-entry when
the checked-out repos match the manifest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SOURCE_BASE_DIR = "aim_source_base"
TARGET_SOURCE_DIR = "aim_target_source"
_DOCUMENT_RE = re.compile(r"^aim_(?P<name>.+)_document$")


def document_repo_name(project_name: str) -> str:
    """The conventional shared-repo name for ``project_name``."""
    return f"aim_{project_name}_document"


@dataclass(slots=True)
class AimLayoutDetection:
    """Everything a create/join call needs, read off one root folder."""

    root: str
    project_name: str
    source_paths: list[str]
    kb_path: str
    target_path: str
    #: True when the document repo already carries an ``aim.yaml`` — the
    #: caller should JOIN this existing project rather than create one.
    has_manifest: bool
    #: Only meaningful when ``has_manifest``: manifest source/target
    #: identities mapped to detected local paths (None = present in the
    #: manifest but not found in this layout — the caller must ask).
    source_identity_map: dict[str, str | None] = field(default_factory=dict)
    target_identity_map: dict[str, str | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def detect_aim_layout(root: str | Path) -> AimLayoutDetection:
    """Inspect ``root`` for the AIM folder convention.

    Raises ``ValueError`` with a user-facing message when the layout does
    not match — every message names exactly what is missing so the wizard
    can show it verbatim.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise ValueError(f"'{root_path}' is not a directory.")

    source_base = root_path / SOURCE_BASE_DIR
    if not source_base.is_dir():
        raise ValueError(
            f"Missing '{SOURCE_BASE_DIR}/' under '{root_path.name}' — the "
            f"folder that holds the legacy source repo(s)."
        )
    source_paths = sorted(
        str(child)
        for child in source_base.iterdir()
        if child.is_dir() and not child.name.startswith(".")
    )
    if not source_paths:
        raise ValueError(
            f"'{SOURCE_BASE_DIR}/' has no child repositories — add at least "
            f"one legacy source repo inside it."
        )

    document_dirs = [
        child
        for child in sorted(root_path.iterdir())
        if child.is_dir() and _DOCUMENT_RE.match(child.name)
    ]
    if not document_dirs:
        raise ValueError(
            f"No 'aim_<project_name>_document/' folder under "
            f"'{root_path.name}' — the shared document (KB) repo is required."
        )
    if len(document_dirs) > 1:
        names = ", ".join(d.name for d in document_dirs)
        raise ValueError(
            f"Multiple document repos found ({names}) — a project root must "
            f"contain exactly one 'aim_<project_name>_document/'."
        )
    kb_dir = document_dirs[0]
    match = _DOCUMENT_RE.match(kb_dir.name)
    assert match is not None  # guaranteed by the filter above
    project_name = match.group("name")

    target_path = root_path / TARGET_SOURCE_DIR
    if not target_path.is_dir():
        raise ValueError(
            f"Missing '{TARGET_SOURCE_DIR}/' under '{root_path.name}' — the "
            f"target repo (already scaffolded with the target stack)."
        )

    warnings: list[str] = []
    if root_path.name != project_name:
        warnings.append(
            f"Root folder is named '{root_path.name}' but the document repo "
            f"says the project is '{project_name}' — using '{project_name}'."
        )

    detection = AimLayoutDetection(
        root=str(root_path),
        project_name=project_name,
        source_paths=source_paths,
        kb_path=str(kb_dir),
        target_path=str(target_path),
        has_manifest=(kb_dir / "aim.yaml").is_file(),
        warnings=warnings,
    )
    if detection.has_manifest:
        _propose_identity_maps(detection)
    return detection


def _propose_identity_maps(detection: AimLayoutDetection) -> None:
    """Match manifest identities against the detected repos' identities.

    Best-effort convenience for join: whatever matches is pre-filled,
    whatever doesn't stays None and the caller asks the user. Manifest
    parse errors degrade to a warning — detection itself still succeeds,
    the join path will surface the real error.
    """
    from app.services.aim.kb_store import read_manifest
    from app.services.aim.project import resolve_repo_identity

    try:
        manifest = read_manifest(Path(detection.kb_path))
    except Exception as exc:  # noqa: BLE001 — any parse/validation error
        detection.warnings.append(f"aim.yaml could not be read: {exc}")
        return

    detected_sources = {
        resolve_repo_identity(path): path for path in detection.source_paths
    }
    detection.source_identity_map = {
        identity: detected_sources.get(identity) for identity in manifest.roles.source
    }
    target_identity = resolve_repo_identity(detection.target_path)
    detection.target_identity_map = {
        identity: (detection.target_path if identity == target_identity else None)
        for identity in manifest.roles.target
    }
    unmatched = [
        identity
        for identity, path in {
            **detection.source_identity_map,
            **detection.target_identity_map,
        }.items()
        if path is None
    ]
    if unmatched:
        detection.warnings.append(
            "Manifest identities not found in this layout: " + ", ".join(unmatched)
        )
