"""Create, inspect, import, and manage portable Agent Plugins."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.schemas.plugins import (
    PluginCreateRequest,
    PluginCredentialUpdateRequest,
    PluginEnabledRequest,
    PluginInstallRequest,
    PluginListItem,
    PluginLifecycleCapabilities,
    PluginListResponse,
    PluginMarketplaceInstallRequest,
    PluginMarketplaceItem,
    PluginMarketplaceResponse,
    PluginReadiness,
    PluginMcpRuntimeStatus,
    PluginOperationResponse,
    PluginPackRequest,
    PluginPathResponse,
    PluginRollbackRequest,
    PluginUpdateRequest,
    PluginWorkspaceDeleteRequest,
    PluginWorkspaceEntryRequest,
    PluginWorkspaceFileRequest,
    PluginWorkspaceFileResponse,
    PluginWorkspaceMutationResponse,
)
from app.plugin_platform import (
    PluginInstallError,
    create_plugin,
    get_installation,
    inspect_plugin,
    install_plugin,
    link_plugin,
    list_effective_installations,
    pack_plugin,
    rollback_plugin,
    set_enabled,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.installer import MAX_ARCHIVE_BYTES
from app.plugin_platform.marketplace import (
    MarketplaceError,
    MarketplaceProvider,
    install_marketplace_plugin,
)
from app.plugin_platform.credentials import (
    PluginCredentialState,
    clear_credentials,
    credential_state,
    save_credentials,
)
from app.plugin_platform.models import PluginInspection, PluginInstallation
from app.plugin_platform.registry import plugin_data_root, staging_root
from app.plugin_platform.workspace import (
    PluginWorkspaceEntry,
    create_workspace_entry,
    delete_workspace_entry,
    list_workspace,
    read_workspace_file,
    write_workspace_file,
)
from app.services import team_manager
from app.conductor.provenance import managed_resource_provider_by_id
from app.conductor.models import ManagedResourceProvider
from app.core.config import settings


router = APIRouter()


def _capabilities_for(installation: PluginInstallation) -> PluginLifecycleCapabilities:
    if installation.source_type == "builtin" or installation.managed_by == "conductor":
        return PluginLifecycleCapabilities(
            can_enable=False,
            can_edit=False,
            can_pack=False,
            can_update=False,
            can_uninstall=False,
        )
    return PluginLifecycleCapabilities(
        can_update=installation.source_type == "installed"
    )


def _require_mutable_path(path: str) -> None:
    from app.plugin_platform.builtins import path_is_builtin_plugin

    if path_is_builtin_plugin(path):
        raise HTTPException(
            status_code=409,
            detail="Bundled Agent Plugins are read-only and update with EvoFlux.",
        )


def _inspection_for(installation: PluginInstallation) -> PluginInspection:
    return inspect_plugin(
        installation.root,
        data_root=plugin_data_root(installation.id),
    )


def _credential_state_for(
    installation: PluginInstallation,
    inspection: PluginInspection,
) -> PluginCredentialState:
    try:
        return credential_state(installation.id, inspection)
    except (OSError, ValueError) as exc:
        return PluginCredentialState(
            supported=True,
            configured=False,
            error=str(exc),
        )


def _readiness_for(
    installation: PluginInstallation,
    inspection: PluginInspection,
    credentials: PluginCredentialState,
) -> PluginReadiness:
    reasons: list[str] = []
    missing_credentials = [
        field.key
        for field in credentials.fields
        if field.required and not field.configured
    ]
    verification_state = installation.provenance.verification_state
    if not inspection.valid:
        reasons.append("plugin inspection failed")
    if verification_state in {"revoked", "changed", "invalid", "failed"}:
        reasons.append(f"artifact verification state is {verification_state}")
    if verification_state == "unavailable":
        reasons.append("artifact verification is unavailable")
    pending_connections = [
        connection.id
        for connection in (
            inspection.manifest.connections if inspection.manifest else []
        )
    ]
    if credentials.error:
        reasons.append("credential store is unavailable")
    if missing_credentials:
        reasons.append("required credentials are missing")
    if pending_connections:
        reasons.append("connection approval is required")

    if not inspection.valid or verification_state in {
        "revoked",
        "changed",
        "invalid",
        "unavailable",
        "failed",
    }:
        return PluginReadiness(
            state="unavailable" if verification_state == "unavailable" else "blocked",
            reasons=reasons,
            missing_credentials=missing_credentials,
            pending_connections=pending_connections,
        )
    if credentials.error:
        return PluginReadiness(
            state="unavailable",
            reasons=reasons,
            missing_credentials=missing_credentials,
            pending_connections=pending_connections,
        )
    if missing_credentials:
        return PluginReadiness(
            state="missing-credentials",
            reasons=reasons,
            missing_credentials=missing_credentials,
            pending_connections=pending_connections,
        )
    if pending_connections:
        return PluginReadiness(
            state="pending-approval",
            reasons=reasons,
            pending_connections=pending_connections,
        )
    if installation.enabled:
        return PluginReadiness(state="ready", can_enable=True, reasons=reasons)
    return PluginReadiness(state="disabled", can_enable=True, reasons=reasons)


def _list_item_for(
    installation: PluginInstallation,
    inspection: PluginInspection,
) -> PluginListItem:
    credentials = _credential_state_for(installation, inspection)
    return PluginListItem(
        installation=installation,
        inspection=inspection,
        credentials=credentials,
        capabilities=_capabilities_for(installation),
        readiness=_readiness_for(installation, inspection, credentials),
        provider=_managed_provider_for(installation),
    )


def _managed_provider_for(
    installation: PluginInstallation,
) -> ManagedResourceProvider | None:
    if not installation.managed_project_id or not installation.managed_resource_id:
        return None
    provider = managed_resource_provider_by_id(
        installation.managed_project_id,
        installation.managed_resource_id,
    )
    if provider is None or installation.managed_version_id not in {
        provider.applied_version_id,
        provider.version_id,
    }:
        return None
    return provider


async def _after_mutation() -> None:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    team_manager.invalidate_skill_cache()
    # Workspace saves can change server implementation code while leaving
    # mcp.json byte-for-byte identical, so unchanged configs must still restart.
    await plugin_mcp_runtime.refresh(force=True)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail="Plugin installation not found.")
    if isinstance(exc, MarketplaceError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _marketplace_provider() -> MarketplaceProvider:
    url = settings.EVOFLUX_PLUGIN_MARKETPLACE_URL.strip()
    if not url:
        raise HTTPException(
            status_code=503, detail="Plugin marketplace is not configured."
        )
    return MarketplaceProvider(url)


def _marketplace_item(entry, installations) -> PluginMarketplaceItem:
    installed = next(
        (
            item
            for item in installations
            if item.name == entry.name and item.version == entry.version
        ),
        None,
    )
    return PluginMarketplaceItem(
        entry=entry,
        installed=installed is not None,
        installation_id=installed.id if installed else None,
        installed_version=installed.version if installed else None,
        verification_state=entry.verification.state,
        readiness=PluginReadiness(
            state="ready" if installed and installed.enabled else "disabled",
            can_enable=installed is not None
            and entry.verification.state in {"verified", "unverified"},
            reasons=[] if installed else ["install required"],
        ),
    )


@router.get("/marketplace", response_model=PluginMarketplaceResponse)
async def list_marketplace_plugins() -> PluginMarketplaceResponse:
    provider = _marketplace_provider()
    index = await provider.fetch_registry()
    installations = await asyncio.to_thread(list_effective_installations)
    return PluginMarketplaceResponse(
        items=[_marketplace_item(entry, installations) for entry in index.plugins]
    )


@router.get("/marketplace/{name}", response_model=PluginMarketplaceItem)
async def get_marketplace_plugin(name: str) -> PluginMarketplaceItem:
    provider = _marketplace_provider()
    index = await provider.fetch_registry()
    entry = next((item for item in index.plugins if item.name == name), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Marketplace plugin not found.")
    installations = await asyncio.to_thread(list_effective_installations)
    return _marketplace_item(entry, installations)


@router.post(
    "/marketplace/install", response_model=PluginOperationResponse, status_code=201
)
async def install_marketplace_plugin_route(
    body: PluginMarketplaceInstallRequest,
) -> PluginOperationResponse:
    provider = _marketplace_provider()
    index = await provider.fetch_registry()
    entry = next(
        (
            item
            for item in index.plugins
            if item.name == body.name and item.version == body.version
        ),
        None,
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Marketplace plugin not found.")
    try:
        installation = await install_marketplace_plugin(
            provider,
            entry,
            enabled=False,
            allow_unverified=body.allow_unverified,
        )
        inspection = await asyncio.to_thread(_inspection_for, installation)
        await _after_mutation()
        return PluginOperationResponse(installation=installation, inspection=inspection)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("", response_model=PluginListResponse)
async def list_plugins() -> PluginListResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    installations = await asyncio.to_thread(list_effective_installations)
    items = await asyncio.gather(
        *(asyncio.to_thread(_inspection_for, item) for item in installations)
    )
    return PluginListResponse(
        plugins=[
            _list_item_for(installation, inspection)
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
    enabled: bool = False,
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


@router.post(
    "/{installation_id}/rollback",
    response_model=PluginOperationResponse,
)
async def rollback_plugin_version(
    installation_id: str,
    body: PluginRollbackRequest,
) -> PluginOperationResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    try:
        await plugin_mcp_runtime.stop_installation(installation_id)
        installation = await asyncio.to_thread(
            rollback_plugin,
            installation_id,
            body.version,
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=installation,
            inspection=_inspection_for(installation),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{installation_id}/update",
    response_model=PluginOperationResponse,
)
async def update_plugin_path(
    installation_id: str,
    body: PluginUpdateRequest,
) -> PluginOperationResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    try:
        await plugin_mcp_runtime.stop_installation(installation_id)
        installation = await asyncio.to_thread(
            update_plugin,
            installation_id,
            body.path,
        )
        await _after_mutation()
        return PluginOperationResponse(
            installation=installation,
            inspection=_inspection_for(installation),
        )
    except (OSError, ValueError, KeyError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{installation_id}/update-upload",
    response_model=PluginOperationResponse,
)
async def update_plugin_archive(
    installation_id: str,
    archive: UploadFile = File(...),
) -> PluginOperationResponse:
    if not (archive.filename or "").casefold().endswith((".evoplugin", ".zip")):
        raise HTTPException(
            status_code=422, detail="Upload a .evoplugin or .zip archive."
        )
    staging_root().mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="update-upload-", dir=staging_root()))
    source = temporary / "update.evoplugin"
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
        from app.plugin_platform.runtime import plugin_mcp_runtime

        await plugin_mcp_runtime.stop_installation(installation_id)
        installation = await asyncio.to_thread(
            update_plugin,
            installation_id,
            source,
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
    _require_mutable_path(body.destination)
    try:
        path = await asyncio.to_thread(
            create_plugin,
            body.destination,
            name=body.name,
            description=body.description,
            version=body.version,
            author=body.author,
            license_name=body.license,
            skill_name=body.skill_name,
        )
        return PluginPathResponse(path=str(path))
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/pack", response_model=PluginPathResponse)
async def pack_plugin_package(body: PluginPackRequest) -> PluginPathResponse:
    _require_mutable_path(body.path)
    if body.output is not None:
        _require_mutable_path(body.output)
    try:
        path = await asyncio.to_thread(pack_plugin, body.path, body.output)
        return PluginPathResponse(path=str(path))
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/workspace/tree", response_model=list[PluginWorkspaceEntry])
async def list_plugin_workspace(
    root: str = Query(min_length=1),
) -> list[PluginWorkspaceEntry]:
    try:
        return await asyncio.to_thread(list_workspace, root)
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/workspace/file", response_model=PluginWorkspaceFileResponse)
async def get_plugin_workspace_file(
    root: str = Query(min_length=1),
    path: str = Query(min_length=1),
) -> PluginWorkspaceFileResponse:
    try:
        content = await asyncio.to_thread(read_workspace_file, root, path)
        return PluginWorkspaceFileResponse(root=root, path=path, content=content)
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.put("/workspace/file", response_model=PluginWorkspaceMutationResponse)
async def put_plugin_workspace_file(
    body: PluginWorkspaceFileRequest,
) -> PluginWorkspaceMutationResponse:
    _require_mutable_path(body.root)
    try:
        await asyncio.to_thread(
            write_workspace_file,
            body.root,
            body.path,
            body.content,
        )
        await _after_mutation()
        return PluginWorkspaceMutationResponse(
            inspection=await asyncio.to_thread(inspect_plugin, body.root)
        )
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspace/entry",
    response_model=PluginWorkspaceMutationResponse,
    status_code=201,
)
async def post_plugin_workspace_entry(
    body: PluginWorkspaceEntryRequest,
) -> PluginWorkspaceMutationResponse:
    _require_mutable_path(body.root)
    try:
        await asyncio.to_thread(
            create_workspace_entry,
            body.root,
            body.path,
            body.kind,
        )
        await _after_mutation()
        return PluginWorkspaceMutationResponse(
            inspection=await asyncio.to_thread(inspect_plugin, body.root)
        )
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspace/entry",
    response_model=PluginWorkspaceMutationResponse,
)
async def remove_plugin_workspace_entry(
    body: PluginWorkspaceDeleteRequest,
) -> PluginWorkspaceMutationResponse:
    _require_mutable_path(body.root)
    try:
        await asyncio.to_thread(delete_workspace_entry, body.root, body.path)
        await _after_mutation()
        return PluginWorkspaceMutationResponse(
            inspection=await asyncio.to_thread(inspect_plugin, body.root)
        )
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{installation_id}/credentials",
    response_model=PluginCredentialState,
)
async def get_plugin_credentials(installation_id: str) -> PluginCredentialState:
    installation = await asyncio.to_thread(get_installation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    try:
        inspection = await asyncio.to_thread(_inspection_for, installation)
        return await asyncio.to_thread(
            credential_state,
            installation.id,
            inspection,
        )
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{installation_id}/credentials",
    response_model=PluginCredentialState,
)
async def put_plugin_credentials(
    installation_id: str,
    body: PluginCredentialUpdateRequest,
) -> PluginCredentialState:
    installation = await asyncio.to_thread(get_installation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    try:
        inspection = await asyncio.to_thread(_inspection_for, installation)
        result = await asyncio.to_thread(
            save_credentials,
            installation.id,
            inspection,
            body.values,
        )
        await _after_mutation()
        return result
    except (OSError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{installation_id}/credentials",
    response_model=PluginCredentialState,
)
async def delete_plugin_credentials(installation_id: str) -> PluginCredentialState:
    installation = await asyncio.to_thread(get_installation, installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    try:
        inspection = await asyncio.to_thread(_inspection_for, installation)
        result = await asyncio.to_thread(
            clear_credentials,
            installation.id,
            inspection,
        )
        await _after_mutation()
        return result
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
    from app.plugin_platform.runtime import plugin_mcp_runtime

    try:
        await plugin_mcp_runtime.stop_installation(installation_id)
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
