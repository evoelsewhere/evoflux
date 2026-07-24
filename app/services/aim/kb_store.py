"""Read/write access to an AIM project's KB repo — the system of record for
migration-unit state (``documents/research/aim-framework.md`` §3.5/§3.6).

Frontmatter parsing reuses the exact same shape as skills/commands
(``app.agent.tools.builtin.skill._parse_frontmatter``); only the write side
is new here, since skills/commands always rewrite a file's full content
verbatim from client input, while a unit's state is updated field-by-field
(e.g. ``set_phase``) while preserving everything else in the file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

import yaml
from pydantic import ValidationError

import app
from app.agent.tools.builtin.skill import _parse_frontmatter
from app.services.aim.models import (
    AimLinkMeta,
    AimManifest,
    AimRunMeta,
    CutoverChecklist,
    UnitFrontmatter,
)


def _unit_doc_path(kb_root: Path, module: str, name: str) -> Path:
    return kb_root / "modules" / module / f"{name}.md"


def read_manifest(kb_root: Path) -> AimManifest:
    """Parse ``aim.yaml`` at the root of a KB repo."""
    data = yaml.safe_load((kb_root / "aim.yaml").read_text(encoding="utf-8")) or {}
    return AimManifest.model_validate(data)


def write_manifest_phase(kb_root: Path, phase: str) -> None:
    """Update the project-level ``phase`` field in ``aim.yaml``, preserving
    every other key.
    """
    path = kb_root / "aim.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["phase"] = phase
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def write_manifest_state_schema(kb_root: Path, state_schema: int) -> None:
    path = kb_root / "aim.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["state_schema"] = state_schema
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def aim_kb_template_dir() -> Path:
    """AIM KB template from a source checkout or wheel-bundled seed tree."""
    checkout = Path(__file__).resolve().parents[3] / "seed" / "aim-kb-template"
    if checkout.is_dir():
        return checkout.resolve()
    bundled = Path(app.__file__).resolve().parent / "_seed" / "aim-kb-template"
    return bundled.resolve()


def scaffold_kb_from_template(kb_root: Path) -> None:
    """Copy ``seed/aim-kb-template/`` into a fresh (or empty) *kb_root*.

    Only fills gaps — an existing file at the target is left untouched,
    same philosophy as ``install_seed`` (app/cli/seed.py).
    """
    import shutil

    kb_root.mkdir(parents=True, exist_ok=True)
    template_dir = aim_kb_template_dir()
    for src in sorted(template_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(template_dir)
        target = kb_root / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)


def create_manifest(
    kb_root: Path,
    *,
    rulebook_id: str,
    rulebook_version: str,
    source_identities: list[str],
    target_identities: list[str],
    compare_default_profile: str = "default",
) -> None:
    """Write a brand-new ``aim.yaml`` — the shareable project manifest a
    "join existing" teammate reads (identity strings, not local paths).
    """
    data = {
        "rulebook": {"id": rulebook_id, "version": rulebook_version},
        "roles": {"source": source_identities, "target": target_identities},
        "golden_dir": "golden",
        "compare_default_profile": compare_default_profile,
        "phase": "assess",
        "state_schema": 2,
    }
    (kb_root / "aim.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def read_unit(
    kb_root: Path, module: str, name: str
) -> tuple[UnitFrontmatter, str] | None:
    """Read a unit's frontmatter + body. ``None`` if the doc doesn't exist yet."""
    path = _unit_doc_path(kb_root, module, name)
    if not path.exists():
        return None
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    return UnitFrontmatter.model_validate(meta), body


def write_unit(
    kb_root: Path,
    module: str,
    name: str,
    *,
    kind: str | None = None,
    phase: str | None = None,
    wave: int | None = None,
    assignee: str | None = None,
    source_paths: list[str] | None = None,
    target_paths: list[str] | None = None,
    depends_on: list[str] | None = None,
    complexity: dict | None = None,
    revision: int | None = None,
    last_transition_id: str | None = None,
    body: str | None = None,
) -> Path:
    """Create or partially update a unit's KB doc.

    Only the fields explicitly passed (non-``None``) change; everything
    else in the file — including the prose body — is preserved. This is
    what lets ``aim_units`` do a narrow update like ``set_phase`` without
    clobbering the module doc `aim-archaeologist` wrote earlier.
    """
    path = _unit_doc_path(kb_root, module, name)
    existing_meta: dict = {}
    existing_body = ""
    if path.exists():
        existing_meta, existing_body = _parse_frontmatter(
            path.read_text(encoding="utf-8")
        )

    merged = dict(existing_meta)
    updates = {
        "kind": kind,
        "phase": phase,
        "wave": wave,
        "assignee": assignee,
        "source_paths": source_paths,
        "target_paths": target_paths,
        "depends_on": depends_on,
        "complexity": complexity,
        "revision": revision,
        "last_transition_id": last_transition_id,
    }
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    merged.setdefault("kind", "unknown")
    merged.setdefault("phase", "inventory")

    final_body = body if body is not None else existing_body
    frontmatter_yaml = yaml.safe_dump(
        merged, sort_keys=False, allow_unicode=True
    ).strip()
    content = f"---\n{frontmatter_yaml}\n---\n\n{final_body}\n".rstrip() + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_transition_event(
    kb_root: Path,
    module: str,
    name: str,
    *,
    from_phase: str,
    to_phase: str,
    revision: int,
    workflow_name: str,
    workflow_execution_id: str,
    session_id: str | None,
    evidence_refs: list[str] | None = None,
) -> str:
    """Append a file-backed unit transition event and return its id."""
    event_id = str(uuid7())
    path = kb_root / "state" / "transitions" / module / name / f"{event_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "id": event_id,
                "unit": f"{module}/{name}",
                "from_phase": from_phase,
                "to_phase": to_phase,
                "revision": revision,
                "workflow": workflow_name,
                "workflow_execution_id": workflow_execution_id,
                "session_id": session_id,
                "evidence_refs": evidence_refs or [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return event_id


def validate_unit_state(
    kb_root: Path,
    module: str,
    name: str,
    frontmatter: UnitFrontmatter,
    *,
    state_schema: int,
) -> str | None:
    """Validate that schema-v2 phase state is backed by an append-only event."""
    if state_schema < 2:
        return None
    if frontmatter.phase == "inventory" and frontmatter.last_transition_id is None:
        return None
    if not frontmatter.last_transition_id:
        return f"{module}/{name}: phase {frontmatter.phase} has no transition event"
    try:
        event_id = str(UUID(frontmatter.last_transition_id))
    except ValueError:
        return f"{module}/{name}: invalid last_transition_id"
    path = kb_root / "state" / "transitions" / module / name / f"{event_id}.yaml"
    if not path.is_file():
        return f"{module}/{name}: transition event {event_id} is missing"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return f"{module}/{name}: transition event {event_id} is invalid: {exc}"
    expected = {
        "id": event_id,
        "unit": f"{module}/{name}",
        "to_phase": frontmatter.phase,
        "revision": frontmatter.revision,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            return (
                f"{module}/{name}: transition event {event_id} has {key}="
                f"{data.get(key)!r}, expected {value!r}"
            )
    return None


def write_run_meta(
    kb_root: Path,
    module: str,
    name: str,
    *,
    run_id: UUID,
    kind: Literal["compare", "convert", "test"],
    verdict: Literal["pass", "fail", "acceptable_diff", "error"],
    case_set: str | None,
    stats: dict,
    report_path: str | None,
    session_id: UUID | None,
    workflow_execution_id: str | None,
    created_at: datetime | None = None,
) -> Path:
    timestamp = created_at or datetime.now(timezone.utc)
    meta = AimRunMeta(
        id=run_id,
        unit=f"{module}/{name}",
        kind=kind,
        verdict=verdict,
        case_set=case_set,
        stats=stats,
        report_path=report_path,
        session_id=session_id,
        workflow_execution_id=workflow_execution_id,
        created_at=timestamp,
    )
    path = kb_root / "runs" / module / name / str(run_id) / "meta.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            meta.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return path


def write_link_meta(
    kb_root: Path,
    *,
    link_id: UUID,
    from_ref: str,
    to_ref: str,
    kind: str,
    note: str | None,
    created_at: datetime | None = None,
) -> Path:
    meta = AimLinkMeta(
        id=link_id,
        from_ref=from_ref,
        to_ref=to_ref,
        kind=kind,
        note=note,
        created_at=created_at or datetime.now(timezone.utc),
    )
    path = kb_root / "state" / "links" / f"{link_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            meta.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return path


def scan_run_metas(
    kb_root: Path,
) -> tuple[list[tuple[str, str, AimRunMeta]], list[str]]:
    results: list[tuple[str, str, AimRunMeta]] = []
    errors: list[str] = []
    runs_root = kb_root / "runs"
    if not runs_root.is_dir():
        return results, errors
    for path in sorted(runs_root.glob("*/*/*/meta.yaml")):
        relative = path.relative_to(runs_root)
        module, name = relative.parts[:2]
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            meta = AimRunMeta.model_validate(data)
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
            errors.append(f"{path.relative_to(kb_root)}: {exc}")
            continue
        if meta.unit != f"{module}/{name}":
            errors.append(
                f"{path.relative_to(kb_root)}: names unit {meta.unit}, "
                f"expected {module}/{name}"
            )
            continue
        results.append((module, name, meta))
    return results, errors


def list_run_metas(kb_root: Path) -> list[tuple[str, str, AimRunMeta]]:
    return scan_run_metas(kb_root)[0]


def scan_link_metas(kb_root: Path) -> tuple[list[AimLinkMeta], list[str]]:
    links_root = kb_root / "state" / "links"
    if not links_root.is_dir():
        return [], []
    results: list[AimLinkMeta] = []
    errors: list[str] = []
    for path in sorted(links_root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            results.append(AimLinkMeta.model_validate(data))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as exc:
            errors.append(f"{path.relative_to(kb_root)}: {exc}")
    return results, errors


def list_link_metas(kb_root: Path) -> list[AimLinkMeta]:
    return scan_link_metas(kb_root)[0]


def write_cutover_checklist(kb_root: Path, checklist: CutoverChecklist) -> Path:
    path = kb_root / "state" / "cutover" / f"wave-{checklist.wave}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            checklist.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        ),
        encoding="utf-8",
    )
    return path


def read_cutover_checklist(kb_root: Path, wave: int) -> CutoverChecklist | None:
    path = kb_root / "state" / "cutover" / f"wave-{wave}.yaml"
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CutoverChecklist.model_validate(data)


def reconcile_legacy_state(kb_root: Path) -> tuple[str, int]:
    """Accept current legacy phases as an explicit schema-v2 baseline.

    This does not invent the missing historical transitions. It records one
    auditable baseline event per advanced unit and a project-level manifest
    naming the operator action that accepted the imported state.
    """
    reconciliation_id = str(uuid7())
    reconciled = 0
    accepted_units: list[str] = []
    for module, name, frontmatter, _ in list_units(kb_root):
        if frontmatter.phase == "inventory":
            continue
        revision = frontmatter.revision + 1
        event_id = write_transition_event(
            kb_root,
            module,
            name,
            from_phase="legacy-baseline",
            to_phase=frontmatter.phase,
            revision=revision,
            workflow_name="legacy-state-reconciliation",
            workflow_execution_id=reconciliation_id,
            session_id=None,
        )
        write_unit(
            kb_root,
            module,
            name,
            revision=revision,
            last_transition_id=event_id,
        )
        reconciled += 1
        accepted_units.append(f"{module}/{name}")

    write_manifest_state_schema(kb_root, 2)
    audit_path = kb_root / "state" / "reconciliations" / f"{reconciliation_id}.yaml"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        yaml.safe_dump(
            {
                "id": reconciliation_id,
                "kind": "accept-current-state",
                "state_schema": 2,
                "units": accepted_units,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return reconciliation_id, reconciled


def scan_units(
    kb_root: Path,
) -> tuple[list[tuple[str, str, UnitFrontmatter, str]], list[str]]:
    """Walk ``modules/**/*.md`` — yields ``(module, name, frontmatter, doc_path_rel)``.

    Files with no parseable ``UnitFrontmatter`` (missing ``kind``, stray
    non-unit markdown) are skipped rather than raising — a reindex should
    degrade gracefully on an in-progress or malformed doc, not abort.
    """
    modules_dir = kb_root / "modules"
    if not modules_dir.is_dir():
        return [], []
    results: list[tuple[str, str, UnitFrontmatter, str]] = []
    errors: list[str] = []
    for module_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
        for doc_path in sorted(module_dir.glob("*.md")):
            try:
                meta, _ = _parse_frontmatter(doc_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                errors.append(f"{doc_path.relative_to(kb_root)}: {exc}")
                continue
            if not meta:
                errors.append(
                    f"{doc_path.relative_to(kb_root)}: missing unit frontmatter"
                )
                continue
            try:
                frontmatter = UnitFrontmatter.model_validate(meta)
            except ValidationError as exc:
                errors.append(f"{doc_path.relative_to(kb_root)}: {exc}")
                continue
            rel = doc_path.relative_to(kb_root).as_posix()
            results.append((module_dir.name, doc_path.stem, frontmatter, rel))
    return results, errors


def list_units(
    kb_root: Path,
) -> list[tuple[str, str, UnitFrontmatter, str]]:
    return scan_units(kb_root)[0]


def sync_project_phase_from_units(kb_root: Path) -> str | None:
    """Advance the project phase when every unit crosses a lifecycle boundary."""
    units = list_units(kb_root)
    if not units or not (kb_root / "aim.yaml").is_file():
        return None
    phases = {frontmatter.phase for _, _, frontmatter, _ in units}
    if "inventory" in phases:
        project_phase = "understand"
    elif "understood" in phases:
        project_phase = "design"
    elif "designed" in phases:
        project_phase = "convert"
    elif "converted" in phases:
        project_phase = "test"
    else:
        project_phase = "cutover"
    manifest = read_manifest(kb_root)
    if manifest.phase != project_phase:
        write_manifest_phase(kb_root, project_phase)
    return project_phase
