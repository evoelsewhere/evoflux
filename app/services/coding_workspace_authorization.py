"""Authorization helpers for project-bound Coding repository actions."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.coding_project_service import get_project_workspace_paths


async def project_contains_workspace_path(
    db: AsyncSession,
    project_id: UUID,
    workspace_path: str | Path,
) -> bool:
    """Return whether a canonical repository is a persisted project member."""
    target = Path(workspace_path).expanduser().resolve()
    return any(
        Path(path).expanduser().resolve() == target
        for path in await get_project_workspace_paths(db, project_id)
    )
