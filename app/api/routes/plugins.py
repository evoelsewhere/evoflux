"""Create, inspect, import, and manage portable Agent Plugins."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.schemas.plugins import (
    MarketplaceCreateRequest,
    MarketplaceInstallRequest,
    MarketplacePluginResponse,
    MarketplacePluginPreviewResponse,
    MarketplaceSourceResponse,
    PluginPackageReview,
    PluginFileText,
    PluginCreateRequest,
    PluginCredentialUpdateRequest,
    PluginEnabledRequest,
    PluginInstallRequest,
    PluginListItem,
    PluginLifecycleCapabilities,
    PluginListResponse,
    PluginMcpRuntimeStatus,
    PluginOperationResponse,
    PluginPackRequest,
    PluginPathResponse,
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
    set_enabled,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.installer import MAX_ARCHIVE_BYTES
from app.plugin_platform.credentials import (
    PluginCredentialState,
    clear_credentials,
    credential_state,
    save_credentials,
)
from app.plugin_platform.models import PluginInspection, PluginInstallation
from app.plugin_platform.marketplaces import (
    MarketplaceKind,
    MarketplacePlugin,
    marketplace_preview_root,
    MarketplaceSource,
    add_marketplace,
    list_marketplaces,
    install_marketplace_preview,
    prepare_marketplace_plugin,
    remove_marketplace,
    search_marketplace_plugins,
    sync_marketplace,
)
from app.plugin_platform.registry import plugin_data_root, staging_root
from app.plugin_platform.validator import redact_inspection
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


router = APIRouter()


@router.get(
    "/previews/{preview_id}/files", response_model=PluginPackageReview | PluginFileText
)
async def review_plugin_preview(
    preview_id: str, path: str | None = Query(default=None)
) -> PluginPackageReview | PluginFileText:
    from app.plugin_platform.review import list_package_files, read_package_file

    root = marketplace_preview_root(preview_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Plugin preview not found.")
    try:
        result = (
            list_package_files(root) if path is None else read_package_file(root, path)
        )
        return (
            PluginPackageReview.model_validate(result)
            if path is None
            else PluginFileText.model_validate(result)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Package file not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/{installation_id}/files", response_model=PluginPackageReview | PluginFileText
)
async def review_installed_plugin(
    installation_id: str, path: str | None = Query(default=None)
) -> PluginPackageReview | PluginFileText:
    from app.plugin_platform.review import list_package_files, read_package_file

    try:
        installation = get_installation(installation_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Plugin installation not found."
        ) from exc
    if installation is None:
        raise HTTPException(status_code=404, detail="Plugin installation not found.")
    try:
        result = (
            list_package_files(installation.root)
            if path is None
            else read_package_file(installation.root, path)
        )
        return (
            PluginPackageReview.model_validate(result)
            if path is None
            else PluginFileText.model_validate(result)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Package file not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    return redact_inspection(
        inspect_plugin(
            installation.root,
            data_root=plugin_data_root(installation.id),
        )
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
    return HTTPException(status_code=422, detail=str(exc))


def _marketplace_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc).strip("'"))
    if isinstance(exc, ValueError) and "already added" in str(exc):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail="Marketplace operation failed.")


@router.get("/marketplaces", response_model=list[MarketplaceSourceResponse])
async def get_marketplaces() -> list[MarketplaceSource]:
    return await asyncio.to_thread(list_marketplaces)


@router.post(
    "/marketplaces",
    response_model=MarketplaceSourceResponse,
    status_code=201,
)
async def create_marketplace(body: MarketplaceCreateRequest) -> MarketplaceSource:
    try:
        return await asyncio.to_thread(
            add_marketplace,
            kind=MarketplaceKind(body.kind),
            name=body.name,
            url=body.url,
        )
    except (KeyError, ValueError) as exc:
        raise _marketplace_http_error(exc) from exc


@router.delete(
    "/marketplaces/{marketplace_id}",
    response_model=MarketplaceSourceResponse,
)
async def delete_marketplace(marketplace_id: str) -> MarketplaceSource:
    try:
        return await asyncio.to_thread(remove_marketplace, marketplace_id)
    except (KeyError, ValueError) as exc:
        raise _marketplace_http_error(exc) from exc


@router.post(
    "/marketplaces/{marketplace_id}/sync",
    response_model=MarketplaceSourceResponse,
)
async def refresh_marketplace(marketplace_id: str) -> MarketplaceSource:
    try:
        return await asyncio.to_thread(sync_marketplace, marketplace_id)
    except (KeyError, ValueError) as exc:
        raise _marketplace_http_error(exc) from exc


@router.get(
    "/marketplaces/plugins",
    response_model=list[MarketplacePluginResponse],
)
async def search_marketplaces(
    q: str = Query(default="", max_length=200),
    marketplace_id: str | None = Query(default=None, max_length=16),
) -> list[MarketplacePlugin]:
    return await asyncio.to_thread(
        search_marketplace_plugins,
        q,
        marketplace_id=marketplace_id,
    )


@router.post(
    "/marketplaces/{marketplace_id}/plugins/{plugin_name}/prepare",
    response_model=MarketplacePluginPreviewResponse,
)
async def prepare_marketplace_install(
    marketplace_id: str,
    plugin_name: str,
) -> MarketplacePluginPreviewResponse:
    try:
        result = await asyncio.to_thread(
            prepare_marketplace_plugin,
            marketplace_id,
            plugin_name,
        )
        return MarketplacePluginPreviewResponse(
            preview_id=result.preview_id,
            plugin=MarketplacePluginResponse.model_validate(result.plugin),
            supported_components=result.supported_components,
            unsupported_components=result.unsupported_components,
            warnings=result.warnings,
            inspection=redact_inspection(result.inspection),
        )
    except (KeyError, ValueError) as exc:
        raise _marketplace_http_error(exc) from exc


@router.post(
    "/marketplaces/install",
    response_model=PluginOperationResponse,
)
async def install_prepared_marketplace_plugin(
    body: MarketplaceInstallRequest,
) -> PluginOperationResponse:
    try:
        installation = await asyncio.to_thread(
            install_marketplace_preview,
            body.preview_id,
            allow_partial=body.allow_partial,
        )
        inspection = await asyncio.to_thread(_inspection_for, installation)
    except (KeyError, ValueError) as exc:
        raise _marketplace_http_error(exc) from exc
    return PluginOperationResponse(installation=installation, inspection=inspection)


@router.get("", response_model=PluginListResponse)
async def list_plugins() -> PluginListResponse:
    from app.plugin_platform.runtime import plugin_mcp_runtime

    installations = await asyncio.to_thread(list_effective_installations)
    items = await asyncio.gather(
        *(asyncio.to_thread(_inspection_for, item) for item in installations)
    )
    return PluginListResponse(
        plugins=[
            PluginListItem(
                installation=installation,
                inspection=inspection,
                credentials=_credential_state_for(installation, inspection),
                capabilities=_capabilities_for(installation),
                provider=_managed_provider_for(installation),
            )
            for installation, inspection in zip(installations, items, strict=True)
        ],
        mcp_servers=[
            PluginMcpRuntimeStatus.model_validate(status)
            for status in plugin_mcp_runtime.list_status()
        ],
    )


@router.get("/inspect", response_model=PluginInspection)
async def inspect_plugin_path(path: str = Query(min_length=1)) -> PluginInspection:
    return redact_inspection(await asyncio.to_thread(inspect_plugin, path))


@router.post("/install", response_model=PluginOperationResponse, status_code=201)
async def install_plugin_path(body: PluginInstallRequest) -> PluginOperationResponse:
    try:
        operation = link_plugin if body.mode == "link" else install_plugin
        installation = await asyncio.to_thread(
            operation,
            body.path,
            enabled=body.enabled,
            **(
                {}
                if body.mode == "link"
                else {
                    "origin": {
                        "kind": "import_directory",
                        "source_ref": str(Path(body.path).expanduser().resolve()),
                    }
                }
            ),
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
            origin={
                "kind": "import_archive",
                "source_ref": f"upload:{archive.filename}",
            },
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
            inspection=redact_inspection(
                await asyncio.to_thread(inspect_plugin, body.root)
            )
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
            inspection=redact_inspection(
                await asyncio.to_thread(inspect_plugin, body.root)
            )
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
            inspection=redact_inspection(
                await asyncio.to_thread(inspect_plugin, body.root)
            )
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
