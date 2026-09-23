from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.api.schemas.office_runtime import OfficeRuntimeStatusResponse
from app.services.office_runtime import (
    RuntimeInstallError,
    dismiss_install_error,
    runtime_status,
    start_runtime_install,
    uninstall_runtime,
)

router = APIRouter(prefix="/office-runtime")


def _status() -> OfficeRuntimeStatusResponse:
    return OfficeRuntimeStatusResponse.model_validate(asdict(runtime_status()))


@router.get("/status", response_model=OfficeRuntimeStatusResponse)
async def office_runtime_status_route() -> OfficeRuntimeStatusResponse:
    return await asyncio.to_thread(_status)


@router.post("/install", response_model=OfficeRuntimeStatusResponse)
async def install_office_runtime_route() -> OfficeRuntimeStatusResponse:
    """Start the user-requested download; progress arrives via /status."""
    try:
        start_runtime_install()
    except RuntimeInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(_status)


@router.post("/install/dismiss", status_code=204)
async def dismiss_office_runtime_error_route() -> None:
    dismiss_install_error()


@router.delete("", status_code=204)
async def uninstall_office_runtime_route() -> None:
    try:
        await asyncio.to_thread(uninstall_runtime)
    except RuntimeInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
