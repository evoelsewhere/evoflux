"""Create, inspect, import, and manage portable Agent Plugins."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.schemas.plugins import (
    PluginCreateRequest,
    PluginEnabledRequest,
    PluginInstallRequest,
    PluginListItem,
    PluginListResponse,
    PluginMcpRuntimeStatus,
    PluginOperationResponse,
    PluginPackRequest,
    PluginPathResponse,
)
from app.plugin_platform import (
    PluginInstallError,
    create_plugin,
    get_installation,
    inspect_plugin,
    install_plugin,
    link_plugin,
    list_installations,
    pack_plugin,
    set_enabled,
    uninstall_plugin,
)
from app.plugin_platform.installer import MAX_ARCHIVE_BYTES
from app.plugin_platform.models import PluginInspection, PluginInstallation
from app.plugin_platform.registry import plugin_data_root, staging_root
from app.services import team_manager


router = APIRouter()


def _inspection_for(installation: PluginInstallation) -> PluginInspection:
    return inspect_plugin(
        installation.root,
        data_root=plugin_data_root(installation.id),
    )


async def _after_mutation() -> None:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    team_manager.invalidate_skill_cache()
    await plugin_mcp_runtime.refresh()


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Plugin installation not found.")
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=PluginListResponse)
async def list_plugins() -> PluginListResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    installations = await asyncio.to_thread(list_installations)
    items = await asyncio.gather(
        *(asyncio.to_thread(_inspection_for, item) for item in installations)
    )
    return PluginListResponse(
        plugins=[
            PluginListItem(installation=installation, inspection=inspection)
            for installation, inspection in zip(installations, items, strict=True)
        ],
        mcp_servers=[
            PluginMcpRuntimeStatus.model_validate(status)
            for status in plugin_mcp_runtime.list_status()
        ],
    )


@router.get("/inspect", response_model=PluginInspection)
async def inspect_plugin_path(path: str = Query(min_length=1)) -> PluginInspection:
    return await asyncio.to_thread(inspect_plugin, path)


@router.post("/install", response_model=PluginOperationResponse, status_code=201)
async def install_plugin_path(body: PluginInstallRequest) -> PluginOperationResponse:
    try:
        operation = link_plugin if body.mode == "link" else install_plugin
        installation = await asyncio.to_thread(
            operation,
            body.path,
            enabled=body.enabled,
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=installation,
            inspection=_inspection_for(installation),
        )
    except (OSError, ValueError, KeyError) as exc:
        raise _http_error(exc) from exc


@router.post("/upload", response_model=PluginOperationResponse, status_code=201)
async def upload_plugin_archive(
    archive: UploadFile = File(...),
    enabled: bool = True,
) -> PluginOperationResponse:
    if not (archive.filename or "").casefold().endswith((".evoplugin", ".zip")):
        raise HTTPException(
            status_code=422, detail="Upload a .evoplugin or .zip archive."
        )
    staging_root().mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="upload-", dir=staging_root()))
    source = temporary / "upload.evoplugin"
    total = 0
    try:
        with source.open("wb") as output:
            while chunk := await archive.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise PluginInstallError(
                        f"Archive exceeds the {MAX_ARCHIVE_BYTES}-byte limit."
                    )
                output.write(chunk)
        installation = await asyncio.to_thread(
            install_plugin,
            source,
            enabled=enabled,
            source_ref=f"upload:{archive.filename}",
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=installation,
            inspection=_inspection_for(installation),
        )
    except (OSError, ValueError, KeyError) as exc:
        raise _http_error(exc) from exc
    finally:
        await archive.close()
        shutil.rmtree(temporary, ignore_errors=True)


@router.post("/create", response_model=PluginPathResponse, status_code=201)
async def create_plugin_package(body: PluginCreateRequest) -> PluginPathResponse:
    try:
        path = await asyncio.to_thread(
            create_plugin,
            body.destination,
            name=body.name,
            description=body.description,
            skill_name=body.skill_name,
        )
        return PluginPathResponse(path=str(path))
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/pack", response_model=PluginPathResponse)
async def pack_plugin_package(body: PluginPackRequest) -> PluginPathResponse:
    try:
        path = await asyncio.to_thread(pack_plugin, body.path, body.output)
        return PluginPathResponse(path=str(path))
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/{installation_id}", response_model=PluginOperationResponse)
async def get_plugin(installation_id: str) -> PluginOperationResponse:
    installation = await asyncio.to_thread(get_installation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    return PluginOperationResponse(
        installation=installation,
        inspection=await asyncio.to_thread(_inspection_for, installation),
    )


@router.patch("/{installation_id}/enabled", response_model=PluginOperationResponse)
async def update_plugin_enabled(
    installation_id: str,
    body: PluginEnabledRequest,
) -> PluginOperationResponse:
    try:
        installation = await asyncio.to_thread(
            set_enabled,
            installation_id,
            body.enabled,
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=installation,
            inspection=_inspection_for(installation),
        )
    except (OSError, ValueError, KeyError) as exc:
        raise _http_error(exc) from exc


@router.delete("/{installation_id}", response_model=PluginOperationResponse)
async def delete_plugin(
    installation_id: str,
    remove_data: bool = False,
) -> PluginOperationResponse:
    installation = await asyncio.to_thread(get_installation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    inspection = await asyncio.to_thread(_inspection_for, installation)
    try:
        removed = await asyncio.to_thread(
            uninstall_plugin,
            installation_id,
            remove_data=remove_data,
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=removed,
            inspection=inspection,
        )
    except (OSError, ValueError, KeyError) as exc:
        raise _http_error(exc) from exc


__all__ = ["router"]
