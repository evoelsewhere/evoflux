"""Service layer for CodingProject (multi-repo project grouping)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.chat import CodingProject, CodingProjectWorkspace, CodingWorkspace
from app.services.coding_workspace_service import upsert_coding_workspace

# Sentinel distinguishing "field omitted" (leave unchanged) from an explicit
# ``None`` (clear the column). Callers pass ``UNSET`` for fields the client did
# not include in the PATCH/PUT body.
UNSET: Any = object()


async def create_project(
    db: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    workspace_paths: list[str],
    settings: dict | None = None,
) -> CodingProject:
    project = CodingProject(
        name=name,
        description=description,
        settings=settings or {},
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    # De-duplicate by *resolved* workspace id (upsert_coding_workspace resolves
    # the path), so two inputs that point at the same directory — e.g. a
    # trailing slash or a symlink — don't violate the (project_id, workspace_id)
    # unique constraint (which would otherwise 500 the whole create).
    seen_ids: set[UUID] = set()
    order = 0
    for path in workspace_paths:
        ws = await upsert_coding_workspace(db, path=path, kind="repo")
        if ws.id in seen_ids:
            continue
        seen_ids.add(ws.id)
        db.add(
            CodingProjectWorkspace(
                project_id=project.id,
                workspace_id=ws.id,
                sort_order=order,
            )
        )
        order += 1

    await db.flush()
    return project


async def get_project(db: AsyncSession, project_id: UUID) -> CodingProject | None:
    return (
        await db.exec(
            select(CodingProject).where(
                CodingProject.id == project_id,
                col(CodingProject.deleted_at).is_(None),
            )
        )
    ).first()


async def list_visible_projects(
    db: AsyncSession, *, kind: str | None = None
) -> list[CodingProject]:
    """List non-hidden, non-deleted projects.

    ``kind`` filters to "coding" or "aim" — Forge/Coding UIs should always
    pass ``kind="coding"`` and the AIM Board's project picker
    ``kind="aim"``, so the two modes never surface each other's projects
    (documents/research/aim-framework.md §3.3).
    """
    stmt = select(CodingProject).where(
        ~col(CodingProject.hidden),
        col(CodingProject.deleted_at).is_(None),
    )
    if kind is not None:
        stmt = stmt.where(CodingProject.kind == kind)
    stmt = stmt.order_by(col(CodingProject.created_at).asc())
    return list((await db.exec(stmt)).all())


async def update_project(
    db: AsyncSession,
    project_id: UUID,
    *,
    name: str | None = None,
    description: str | None | Any = UNSET,
    settings: dict | None = None,
) -> CodingProject | None:
    """Partial-update a project.

    ``description`` uses the ``UNSET`` sentinel so an explicit ``None`` clears
    the column while an omitted field leaves it unchanged. ``settings`` is
    *merged* into the stored dict (existing keys survive) — callers wanting a
    full replacement should send the complete object.
    """
    project = await get_project(db, project_id)
    if project is None:
        return None
    if name is not None:
        project.name = name
    if description is not UNSET:
        project.description = description
    if settings is not None:
        project.settings = {**project.settings, **settings}
    project.updated_at = datetime.now(timezone.utc)
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def soft_delete_project(db: AsyncSession, project_id: UUID) -> bool:
    project = await get_project(db, project_id)
    if project is None:
        return False
    project.deleted_at = datetime.now(timezone.utc)
    db.add(project)
    await db.flush()
    return True


async def add_workspace_to_project(
    db: AsyncSession,
    project_id: UUID,
    workspace_path: str,
    display_name: str | None = None,
) -> CodingProjectWorkspace | None:
    project = await get_project(db, project_id)
    if project is None:
        return None

    ws = await upsert_coding_workspace(db, path=workspace_path, kind="repo")

    existing = (
        await db.exec(
            select(CodingProjectWorkspace).where(
                CodingProjectWorkspace.project_id == project_id,
                CodingProjectWorkspace.workspace_id == ws.id,
            )
        )
    ).first()
    if existing:
        if display_name is not None:
            existing.display_name = display_name
            db.add(existing)
            await db.flush()
        return existing

    max_order_result = (
        await db.exec(
            select(CodingProjectWorkspace.sort_order)
            .where(CodingProjectWorkspace.project_id == project_id)
            .order_by(col(CodingProjectWorkspace.sort_order).desc())
        )
    ).first()
    # Start at 0 for the first repo (mirrors create_project's 0-based numbering)
    # and append after the current max otherwise.
    next_order = (max_order_result if max_order_result is not None else -1) + 1

    link = CodingProjectWorkspace(
        project_id=project_id,
        workspace_id=ws.id,
        display_name=display_name or Path(workspace_path).name,
        sort_order=next_order,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    return link


async def remove_workspace_from_project(
    db: AsyncSession, project_id: UUID, workspace_id: UUID
) -> bool:
    link = (
        await db.exec(
            select(CodingProjectWorkspace).where(
                CodingProjectWorkspace.project_id == project_id,
                CodingProjectWorkspace.workspace_id == workspace_id,
            )
        )
    ).first()
    if link is None:
        return False
    await db.delete(link)
    await db.flush()
    return True


async def get_project_workspaces(
    db: AsyncSession, project_id: UUID
) -> list[tuple[CodingProjectWorkspace, CodingWorkspace]]:
    # Exclude soft-deleted and hidden member repos so a removed/hidden
    # directory can never surface in the project's workspace list or
    # become the derived primary workspace (paths[0]) used to launch a
    # project session — mirrors the sidebar's own hidden-workspace filter.
    rows = (
        await db.exec(
            select(CodingProjectWorkspace, CodingWorkspace)
            .join(
                CodingWorkspace,
                col(CodingWorkspace.id) == col(CodingProjectWorkspace.workspace_id),
            )
            .where(
                CodingProjectWorkspace.project_id == project_id,
                col(CodingWorkspace.deleted_at).is_(None),
                ~col(CodingWorkspace.hidden),
            )
            .order_by(col(CodingProjectWorkspace.sort_order).asc())
        )
    ).all()
    return [(link, ws) for link, ws in rows]


async def get_project_workspace_paths(
    db: AsyncSession, project_id: UUID
) -> list[str]:
    pairs = await get_project_workspaces(db, project_id)
    return [ws.path for _, ws in pairs]


async def get_projects_for_workspace(
    db: AsyncSession, workspace_id: UUID
) -> list[UUID]:
    """Reverse lookup: which live project(s) contain this workspace as a member.

    Used by the code-graph indexer to scope cross-repo reference tracking —
    a standalone (non-project) workspace has no sibling repos to link against.
    """
    rows = (
        await db.exec(
            select(CodingProjectWorkspace.project_id)
            .join(CodingProject, CodingProject.id == CodingProjectWorkspace.project_id)
            .where(
                CodingProjectWorkspace.workspace_id == workspace_id,
                col(CodingProject.deleted_at).is_(None),
            )
        )
    ).all()
    return list(rows)
