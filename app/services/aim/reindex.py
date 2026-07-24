"""Rebuild the ``aim_units`` index table from a KB repo's ``modules/**/*.md``
frontmatter. The KB is the system of record; this table is a derived,
disposable index (``documents/research/aim-framework.md`` §3.5) — safe to
delete and rebuild in full via :func:`reindex_project`.

Deliberately does **not** delete rows whose doc has disappeared from the KB
(no pruning): an ``AimUnit`` row is referenced by ``aim_runs`` (FK cascade),
so silently deleting it here would destroy a unit's run history just
because its doc moved or was temporarily removed. An actually-removed unit
is a human decision, not something a reindex should infer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.aim import AimLink, AimRun, AimUnit
from app.services.aim import kb_store
from app.services.aim.models import UnitFrontmatter


@dataclass
class ReindexResult:
    created: int
    updated: int
    unchanged: int
    invalid: int = 0
    errors: list[str] = field(default_factory=list)
    runs_created: int = 0
    runs_updated: int = 0
    links_created: int = 0
    links_updated: int = 0


def _index_fields(frontmatter: UnitFrontmatter, kb_doc_path: str) -> dict:
    return {
        "kind": frontmatter.kind,
        "phase": frontmatter.phase,
        "wave": frontmatter.wave,
        "assignee": frontmatter.assignee,
        "source_paths": frontmatter.source_paths,
        "target_paths": frontmatter.target_paths,
        "depends_on": frontmatter.depends_on,
        "complexity": frontmatter.complexity,
        "revision": frontmatter.revision,
        "last_transition_id": frontmatter.last_transition_id,
        "kb_doc_path": kb_doc_path,
    }


async def upsert_unit(
    db: AsyncSession,
    project_id: UUID,
    module: str,
    name: str,
    frontmatter: UnitFrontmatter,
    kb_doc_path: str,
) -> tuple[AimUnit, Literal["created", "updated", "unchanged"]]:
    """Upsert a single unit's index row from its KB frontmatter.

    Used both by :func:`reindex_project` (bulk) and directly by the
    ``aim_units`` tool after a single ``set_phase`` call, so a targeted
    state change doesn't have to pay for a full KB walk.
    """
    row = (
        await db.exec(
            select(AimUnit).where(
                AimUnit.project_id == project_id,
                AimUnit.module == module,
                AimUnit.name == name,
            )
        )
    ).first()
    fields = _index_fields(frontmatter, kb_doc_path)
    if row is None:
        row = AimUnit(project_id=project_id, module=module, name=name, **fields)
        db.add(row)
        await db.flush()
        return row, "created"

    changed = any(getattr(row, key) != value for key, value in fields.items())
    for key, value in fields.items():
        setattr(row, key, value)
    db.add(row)
    await db.flush()
    return row, ("updated" if changed else "unchanged")


async def reindex_project(
    db: AsyncSession, project_id: UUID, kb_root: Path
) -> ReindexResult:
    """Upsert every ``modules/**/*.md`` unit into ``aim_units`` for *project_id*."""
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    try:
        state_schema = kb_store.read_manifest(kb_root).state_schema
    except (FileNotFoundError, ValueError):
        state_schema = 1
    scanned_units, errors = kb_store.scan_units(kb_root)
    for module, name, frontmatter, doc_path in scanned_units:
        error = kb_store.validate_unit_state(
            kb_root,
            module,
            name,
            frontmatter,
            state_schema=state_schema,
        )
        if error:
            errors.append(error)
            continue
        _row, status = await upsert_unit(
            db, project_id, module, name, frontmatter, doc_path
        )
        counts[status] += 1
    runs_created = 0
    runs_updated = 0
    run_metas, run_errors = kb_store.scan_run_metas(kb_root)
    errors.extend(run_errors)
    for module, name, meta in run_metas:
        unit = (
            await db.exec(
                select(AimUnit).where(
                    AimUnit.project_id == project_id,
                    AimUnit.module == module,
                    AimUnit.name == name,
                )
            )
        ).first()
        if unit is None:
            errors.append(f"run {meta.id}: unit {module}/{name} is not indexed")
            continue
        row = await db.get(AimRun, meta.id)
        fields = {
            "unit_id": unit.id,
            "kind": meta.kind,
            "verdict": meta.verdict,
            "case_set": meta.case_set,
            "stats": meta.stats,
            "report_path": meta.report_path,
            "session_id": meta.session_id,
            "workflow_execution_id": meta.workflow_execution_id,
            "created_at": meta.created_at,
        }
        if row is None:
            db.add(AimRun(id=meta.id, **fields))
            runs_created += 1
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            db.add(row)
            runs_updated += 1

    links_created = 0
    links_updated = 0
    link_metas, link_errors = kb_store.scan_link_metas(kb_root)
    errors.extend(link_errors)
    for meta in link_metas:
        row = await db.get(AimLink, meta.id)
        fields = {
            "project_id": project_id,
            "from_ref": meta.from_ref,
            "to_ref": meta.to_ref,
            "kind": meta.kind,
            "note": meta.note,
            "created_at": meta.created_at,
        }
        if row is None:
            db.add(AimLink(id=meta.id, **fields))
            links_created += 1
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            db.add(row)
            links_updated += 1

    return ReindexResult(
        **counts,
        invalid=len(errors),
        errors=errors,
        runs_created=runs_created,
        runs_updated=runs_updated,
        links_created=links_created,
        links_updated=links_updated,
    )
