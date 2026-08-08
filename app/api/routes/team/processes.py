"""Unified process listing and termination endpoints."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select

from app.api.schemas.processes import ProcessListResponse, ProcessResponse
from app.core import db as db_module
from app.models.chat import ChatSession
from app.services.process_manager import (
    list_active_processes,
    terminate_active_process,
)

router = APIRouter()


async def _session_titles(session_ids: set[str]) -> dict[str, str]:
    valid_ids: list[UUID] = []
    for session_id in session_ids:
        try:
            valid_ids.append(UUID(session_id))
        except ValueError:
            continue
    if not valid_ids:
        return {}
    async with db_module.async_session_factory() as db:
        rows = (
            await db.exec(select(ChatSession).where(col(ChatSession.id).in_(valid_ids)))
        ).all()
    return {
        str(row.id): row.title or row.agent_name or "Untitled session" for row in rows
    }


@router.get("/processes", response_model=ProcessListResponse)
async def list_processes() -> ProcessListResponse:
    processes = list_active_processes()
    titles = await _session_titles(
        {process.session_id for process in processes if process.session_id}
    )
    return ProcessListResponse(
        processes=[
            ProcessResponse(
                **asdict(process),
                session_title=titles.get(process.session_id or ""),
            )
            for process in processes
        ]
    )


@router.delete("/processes/{process_id}", status_code=status.HTTP_204_NO_CONTENT)
async def terminate_process(process_id: str) -> None:
    if not await terminate_active_process(process_id):
        raise HTTPException(status_code=404, detail="Process not found")
