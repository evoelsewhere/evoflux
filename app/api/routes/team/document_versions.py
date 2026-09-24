"""Version history of a session's Office documents (undo/redo/rollback)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.api.routes.team.files import _resolve_workspace_entry, _session_workspace
from app.api.schemas.document_versions import (
    DocumentHistoryResponse,
    DocumentVersionActionRequest,
    DocumentVersionResponse,
)
from app.services import document_versions
from app.services.document_versions import DocumentHistory, DocumentVersionError

router = APIRouter()


async def _document(session_id: str, path: str) -> tuple[Path, str]:
    try:
        uuid.UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid session id.") from exc
    root = (await _session_workspace(session_id)).resolve()
    resolved = _resolve_workspace_entry(root, path)
    if not document_versions.is_versioned(resolved.name):
        raise HTTPException(
            status_code=415,
            detail="Only Word, Excel and PowerPoint files keep versions.",
        )
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Document not found.")
    await document_versions.ensure_watching(session_id, root)
    return root, resolved.relative_to(root).as_posix()


def _response(history: DocumentHistory) -> DocumentHistoryResponse:
    return DocumentHistoryResponse(
        path=history.path,
        head=history.head,
        can_undo=history.can_undo,
        can_redo=history.can_redo,
        versions=[
            DocumentVersionResponse(
                id=version.id,
                size=version.size,
                created_at=version.created_at,
                label=version.label,
                source=version.source,
            )
            for version in history.versions
        ],
    )


@router.get("/{session_id}/document-versions", response_model=DocumentHistoryResponse)
async def get_document_versions(
    session_id: str, path: str = Query(min_length=1)
) -> DocumentHistoryResponse:
    root, rel_path = await _document(session_id, path)
    history = await asyncio.to_thread(
        document_versions.get_history, session_id, root, rel_path
    )
    return _response(history)


@router.post("/{session_id}/document-versions", response_model=DocumentHistoryResponse)
async def change_document_version(
    session_id: str, body: DocumentVersionActionRequest
) -> DocumentHistoryResponse:
    root, rel_path = await _document(session_id, body.path)
    try:
        if body.action == "checkpoint":
            history = await asyncio.to_thread(
                document_versions.checkpoint, session_id, root, rel_path, body.label
            )
        elif body.action == "restore":
            if not body.version_id:
                raise HTTPException(status_code=422, detail="version_id is required.")
            history = await asyncio.to_thread(
                document_versions.restore_version,
                session_id,
                root,
                rel_path,
                body.version_id,
            )
        else:
            history = await asyncio.to_thread(
                document_versions.step,
                session_id,
                root,
                rel_path,
                offset=-1 if body.action == "undo" else 1,
            )
    except DocumentVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=423, detail="The file is open elsewhere; close it and retry."
        ) from exc
    return _response(history)
