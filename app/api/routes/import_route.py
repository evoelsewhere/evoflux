"""Import API routes.

Provides endpoints for detecting, previewing, and executing data imports
from external AI tools (Claude, ChatGPT, Codex, Cursor).

All endpoints accept a **local filesystem path** — the Python sidecar reads
files directly.  No web upload, no temp staging.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_db_session
from app.services.import_service import (
    detect_conflicts,
    execute_import,
    get_bundle,
    parse_import,
    remove_bundle,
    store_bundle,
)

router = APIRouter()


# ── Request / Response schemas ───────────────────────────────────────────────


class DetectRequest(BaseModel):
    """Path to a local file or directory to import from."""

    path: str = Field(..., description="Absolute path to the export file or directory")
    source: str | None = Field(
        None,
        description="Explicit source identifier (e.g. 'claude_web'). "
        "If omitted, auto-detection is attempted.",
    )


class ImportItemPreview(BaseModel):
    id: str
    kind: str
    label: str
    preview: str
    action: str
    conflicts: list[str] = Field(default_factory=list)
    target_name: str


class DetectResponse(BaseModel):
    import_id: str
    detected_source: str
    path: str
    summary: dict[str, Any]
    items: list[ImportItemPreview] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UpdateItemRequest(BaseModel):
    """Update conflict resolution for a single item."""

    action: str = Field(
        ..., description="Resolution: 'import', 'skip', 'replace', or 'rename'"
    )


class ExecuteResponse(BaseModel):
    imported: dict[str, int]
    skipped: dict[str, int]
    errors: list[dict[str, Any]]


class HistoryItem(BaseModel):
    import_id: str
    source: str
    path: str
    item_count: int
    summary: dict[str, Any]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/detect", response_model=DetectResponse)
async def import_detect(body: DetectRequest) -> DetectResponse:
    """Auto-detect the source format and return a preview bundle.

    Accepts a local filesystem path.  The Python sidecar reads the file
    directly — no upload required.
    """
    path = Path(body.path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path not found: {path}")

    bundle = parse_import(path, source=body.source)
    if bundle.source == "unknown" or not bundle.items:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Could not detect import format",
                "warnings": bundle.warnings,
            },
        )

    import_id = uuid.uuid4().hex[:16]
    store_bundle(import_id, bundle)

    # Build item previews
    items: list[ImportItemPreview] = []
    for i, item in enumerate(bundle.items):
        preview_parts: list[str] = []
        if item.kind == "session":
            msg_count = len(item.data.get("messages", []))
            preview_parts.append(f"{msg_count} messages")
            created = item.data.get("created_at", "")[:10]
            if created:
                preview_parts.append(f"created {created}")

        items.append(
            ImportItemPreview(
                id=f"{import_id}_{i}",
                kind=item.kind,
                label=item.label,
                preview=", ".join(preview_parts) if preview_parts else item.kind,
                action=item.action,
                conflicts=item.conflicts,
                target_name=item.data.get("title")
                or item.data.get("name")
                or item.label,
            )
        )

    # Summary counts
    kind_counts: dict[str, int] = {}
    for item in bundle.items:
        kind_counts[item.kind] = kind_counts.get(item.kind, 0) + 1

    return DetectResponse(
        import_id=import_id,
        detected_source=bundle.source,
        path=str(path),
        summary={
            "total_items": len(bundle.items),
            "conflicts": sum(1 for it in bundle.items if it.conflicts),
            **kind_counts,
        },
        items=items,
        warnings=bundle.warnings,
    )


@router.get("/preview/{import_id}", response_model=DetectResponse)
async def import_preview(import_id: str) -> DetectResponse:
    """Return the current preview for a previously detected import."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    items: list[ImportItemPreview] = []
    for i, item in enumerate(bundle.items):
        preview_parts: list[str] = []
        if item.kind == "session":
            msg_count = len(item.data.get("messages", []))
            preview_parts.append(f"{msg_count} messages")
            created = item.data.get("created_at", "")[:10]
            if created:
                preview_parts.append(f"created {created}")

        items.append(
            ImportItemPreview(
                id=f"{import_id}_{i}",
                kind=item.kind,
                label=item.label,
                preview=", ".join(preview_parts) if preview_parts else item.kind,
                action=item.action,
                conflicts=item.conflicts,
                target_name=item.data.get("title")
                or item.data.get("name")
                or item.label,
            )
        )

    kind_counts: dict[str, int] = {}
    for item in bundle.items:
        kind_counts[item.kind] = kind_counts.get(item.kind, 0) + 1

    return DetectResponse(
        import_id=import_id,
        detected_source=bundle.source,
        path=bundle.metadata.get("source_path", ""),
        summary={
            "total_items": len(bundle.items),
            "conflicts": sum(1 for it in bundle.items if it.conflicts),
            **kind_counts,
        },
        items=items,
        warnings=bundle.warnings,
    )


@router.patch("/preview/{import_id}/items/{item_index}")
async def update_item_action(
    import_id: str,
    item_index: int,
    body: UpdateItemRequest,
) -> dict[str, str]:
    """Update the conflict resolution action for a specific item."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    if item_index < 0 or item_index >= len(bundle.items):
        raise HTTPException(status_code=400, detail="Invalid item index")

    allowed = {"import", "skip", "replace", "rename"}
    if body.action not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action. Allowed: {allowed}",
        )

    bundle.items[item_index].action = body.action  # type: ignore[assignment]
    return {"status": "ok"}


@router.post("/execute/{import_id}", response_model=ExecuteResponse)
async def import_execute(
    import_id: str,
    db: Any = Depends(get_db_session),
) -> ExecuteResponse:
    """Execute the import, writing accepted items to EvoFlux data stores."""
    bundle = get_bundle(import_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Import not found")

    # Detect conflicts against current DB state
    await detect_conflicts(db, bundle)

    # Reset actions for items that now have conflicts (unless user overrode)
    for item in bundle.items:
        if item.conflicts and item.action == "import":
            item.action = "skip"

    # Execute
    result = await execute_import(db, bundle)

    return ExecuteResponse(
        imported=result.imported,
        skipped=result.skipped,
        errors=result.errors,
    )


@router.delete("/{import_id}")
async def import_cancel(import_id: str) -> dict[str, str]:
    """Cancel and clean up a pending import."""
    remove_bundle(import_id)
    return {"status": "cancelled"}


@router.get("/history")
async def import_history(
    db: Any = Depends(get_db_session),
) -> dict[str, Any]:
    """Return past import operations from the history table."""
    from json import JSONDecodeError, loads

    from sqlmodel import select

    from app.models.import_job import ImportJob

    stmt = select(ImportJob).order_by(ImportJob.created_at.desc()).limit(50)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    items: list[dict[str, Any]] = []
    for job in jobs:
        imported: dict[str, Any] = {}
        skipped: dict[str, Any] = {}
        try:
            imported = loads(job.imported_counts)
        except (JSONDecodeError, TypeError):
            pass
        try:
            skipped = loads(job.skipped_counts)
        except (JSONDecodeError, TypeError):
            pass

        items.append(
            {
                "import_id": job.id,
                "source": job.source,
                "path": job.source_path,
                "detected_format": job.detected_format,
                "status": job.status,
                "imported": imported,
                "skipped": skipped,
                "error_count": job.error_count,
                "item_count": job.item_count,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "completed_at": job.completed_at.isoformat()
                if job.completed_at
                else None,
            }
        )

    return {"imports": items}
