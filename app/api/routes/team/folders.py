"""Session folder CRUD and session→folder assignment, all under /team.

Folders group Work-mode sessions in the sidebar. Listing returns each
folder together with its first page of sessions so the sidebar tree comes
from one request; older sessions have a dedicated cursor endpoint. Per-session
assignment lives here rather than in
``chat.py``'s title PATCH, so a drag-and-drop move never has to send a
title it isn't changing.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.api.schemas.sessions import (
    SessionFolderAssignRequest,
    SessionFolderCreateRequest,
    SessionFolderListResponse,
    SessionFolderResponse,
    SessionFolderUpdateRequest,
    SessionPageResponse,
    SessionResponse,
)
from app.models.chat import ChatSession, SessionFolder, normalize_mode
from app.services import memory_stream_store as stream_store
from app.services.session_folder_service import (
    FolderModeMismatch,
    FolderNotFound,
    assign_session_folder,
    count_folder_sessions,
    create_folder,
    delete_folder,
    get_folder,
    list_folder_sessions_page,
    list_folders,
    update_folder,
)

router = APIRouter()

# Newest sessions returned inline per folder. Older chats remain reachable
# through GET /session-folders/{id}/sessions.
FOLDER_SESSIONS_LIMIT = 40


def _session_response(session: ChatSession, running_ids: set[str]) -> SessionResponse:
    return SessionResponse.model_validate(session).model_copy(
        update={"running": str(session.id) in running_ids}
    )


def _folder_response(
    folder: SessionFolder,
    sessions: list[ChatSession],
    session_count: int,
    running_ids: set[str],
    *,
    next_cursor: str | None = None,
    has_more: bool = False,
) -> SessionFolderResponse:
    return SessionFolderResponse(
        id=folder.id,
        name=folder.name,
        mode=folder.mode,
        share_context=folder.share_context,
        sort_order=folder.sort_order,
        session_count=session_count,
        sessions=[_session_response(s, running_ids) for s in sessions],
        next_cursor=next_cursor,
        has_more=has_more,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.get("/session-folders", response_model=SessionFolderListResponse)
async def list_team_session_folders(
    db: DbSession,
    mode: str = Query("work", description="App mode the folders belong to."),
) -> SessionFolderListResponse:
    """List folders of one mode, each with its newest sessions inline."""
    resolved_mode = normalize_mode(mode)
    if resolved_mode not in {"work", "coding", "aim"}:
        raise HTTPException(status_code=422, detail="Invalid mode")

    running_ids = set(stream_store.running_session_ids())
    folders = await list_folders(db, mode=resolved_mode)
    payload: list[SessionFolderResponse] = []
    for folder in folders:
        sessions, next_cursor, has_more = await list_folder_sessions_page(
            db, folder.id, limit=FOLDER_SESSIONS_LIMIT
        )
        total = (
            len(sessions)
            if not has_more
            else await count_folder_sessions(db, folder.id)
        )
        payload.append(
            _folder_response(
                folder,
                sessions,
                total,
                running_ids,
                next_cursor=next_cursor,
                has_more=has_more,
            )
        )
    return SessionFolderListResponse(folders=payload)


@router.get("/session-folders/{folder_id}/sessions", response_model=SessionPageResponse)
async def list_team_session_folder_sessions(
    folder_id: UUID,
    db: DbSession,
    before: str | None = Query(
        None,
        description="ISO 8601 created_at cursor — return sessions older than this.",
    ),
    limit: int = Query(40, ge=1, le=100),
) -> SessionPageResponse:
    """Load another page from a folder without hiding older conversations."""
    if await get_folder(db, folder_id) is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    try:
        sessions, next_cursor, has_more = await list_folder_sessions_page(
            db, folder_id, before=before, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid 'before' cursor — expected ISO 8601 datetime.",
        ) from exc
    running_ids = set(stream_store.running_session_ids())
    return SessionPageResponse(
        data=[_session_response(session, running_ids) for session in sessions],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/session-folders", response_model=SessionFolderResponse, status_code=201)
async def create_team_session_folder(
    body: SessionFolderCreateRequest, db: DbSession
) -> SessionFolderResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty.")
    if body.mode not in {"work", "coding", "aim"}:
        raise HTTPException(status_code=422, detail="Invalid mode")
    folder = await create_folder(
        db, name=name, mode=body.mode, share_context=body.share_context
    )
    return _folder_response(folder, [], 0, set())


@router.patch("/session-folders/{folder_id}", response_model=SessionFolderResponse)
async def update_team_session_folder(
    folder_id: UUID, body: SessionFolderUpdateRequest, db: DbSession
) -> SessionFolderResponse:
    name = body.name.strip() if body.name is not None else None
    if body.name is not None and not name:
        raise HTTPException(status_code=422, detail="Folder name cannot be empty.")
    folder = await update_folder(
        db,
        folder_id,
        name=name,
        share_context=body.share_context,
        sort_order=body.sort_order,
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found.")
    running_ids = set(stream_store.running_session_ids())
    sessions, next_cursor, has_more = await list_folder_sessions_page(
        db, folder.id, limit=FOLDER_SESSIONS_LIMIT
    )
    total = (
        len(sessions) if not has_more else await count_folder_sessions(db, folder.id)
    )
    return _folder_response(
        folder,
        sessions,
        total,
        running_ids,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.delete("/session-folders/{folder_id}", status_code=204)
async def delete_team_session_folder(folder_id: UUID, db: DbSession) -> None:
    """Delete a folder; its sessions survive, un-filed."""
    if not await delete_folder(db, folder_id):
        raise HTTPException(status_code=404, detail="Folder not found.")


@router.patch("/sessions/{session_id}/folder", response_model=SessionResponse)
async def set_team_session_folder(
    session_id: UUID, body: SessionFolderAssignRequest, db: DbSession
) -> SessionResponse:
    """File a session under a folder, or un-file it with ``folder_id: null``."""
    try:
        session = await assign_session_folder(db, session_id, body.folder_id)
    except FolderNotFound as exc:
        raise HTTPException(status_code=404, detail="Folder not found.") from exc
    except FolderModeMismatch as exc:
        raise HTTPException(
            status_code=422,
            detail="Folder belongs to a different mode than the session.",
        ) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return _session_response(session, set(stream_store.running_session_ids()))
