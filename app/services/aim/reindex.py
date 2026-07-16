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

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.aim import AimUnit
from app.services.aim.kb_store import list_units
from app.services.aim.models import UnitFrontmatter


@dataclass
class ReindexResult:
    created: int
    updated: int
    unchanged: int


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
    for module, name, frontmatter, doc_path in list_units(kb_root):
        _row, status = await upsert_unit(
            db, project_id, module, name, frontmatter, doc_path
        )
        counts[status] += 1
    return ReindexResult(**counts)
