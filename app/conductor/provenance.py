"""Resolve Conductor ownership metadata without inspecting resource contents."""

from __future__ import annotations

from app.conductor.constants.resource import MANAGED_RESOURCE_REMOVED_STATE
from app.conductor.constants.resource import ResourceTargetMode, ResourceVersionStatus
from app.conductor.managed_state import ManagedResourceStore
from app.conductor.models import (
    GovernedResourceKind,
    ManagedResourceRecord,
    ManagedResourceProvider,
)
from app.conductor.semver import version_gap
from app.core.runtime_settings import load_runtime_settings


def managed_resource_providers() -> dict[tuple[str, str], ManagedResourceProvider]:
    """Return active managed ownership keyed by ``(kind, slug)``.

    The durable state uses stable project/resource IDs. Slugs are only used to
    attach presentation metadata to a resource that discovery already found on
    disk. Removed resources are intentionally excluded.
    """

    config = load_runtime_settings().conductor
    if not config.project_id:
        return {}
    document = ManagedResourceStore().load()
    if document.project_id != config.project_id:
        return {}

    project_name = (
        config.project_display_name or config.project_name or config.project_id
    )
    providers: dict[tuple[str, str], ManagedResourceProvider] = {}
    for record in sorted(document.resources, key=lambda item: item.observed_at):
        if record.observed_state == MANAGED_RESOURCE_REMOVED_STATE:
            continue
        provider = managed_resource_provider_from_record(record, project_name)
        if record.kind == "agent":
            if ResourceTargetMode.WORK in record.modes:
                providers[(record.kind, record.slug)] = provider
            if ResourceTargetMode.CODING in record.modes:
                providers[(record.kind, f"coding/{record.slug}")] = provider
        else:
            providers[(record.kind, record.slug)] = provider
    return providers


def managed_resource_provider(
    kind: GovernedResourceKind, slug: str
) -> ManagedResourceProvider | None:
    return managed_resource_providers().get((kind, slug))


def managed_resource_provider_by_id(
    project_id: str, resource_id: str
) -> ManagedResourceProvider | None:
    config = load_runtime_settings().conductor
    if config.project_id != project_id:
        return None
    document = ManagedResourceStore().load()
    if document.project_id != project_id:
        return None
    record = next(
        (item for item in document.resources if item.resource_id == resource_id),
        None,
    )
    if record is None or record.observed_state == MANAGED_RESOURCE_REMOVED_STATE:
        return None
    project_name = config.project_display_name or config.project_name or project_id
    return managed_resource_provider_from_record(record, project_name)


def managed_resource_provider_from_record(
    record: ManagedResourceRecord, project_name: str
) -> ManagedResourceProvider:
    applied_version_id = record.applied_version_id or (
        record.version_id if record.observed_state in {"applied", "in_sync"} else None
    )
    applied_version = record.applied_version or (
        record.version if record.observed_state in {"applied", "in_sync"} else None
    )
    current_notice = next(
        (
            notice
            for notice in record.version_history
            if notice.version_id == applied_version_id
        ),
        None,
    )
    update_available = bool(
        applied_version_id
        and record.version_id
        and applied_version_id != record.version_id
    )
    update_required = bool(
        update_available
        and current_notice
        and current_notice.status == ResourceVersionStatus.DEPRECATED
    )
    gap = version_gap(applied_version, record.version)
    return ManagedResourceProvider(
        project_id=record.project_id,
        project_name=project_name,
        resource_id=record.resource_id,
        modes=record.modes,
        version_id=record.version_id,
        version=record.version,
        applied_version_id=applied_version_id,
        applied_version=applied_version,
        description=record.description,
        changelog=record.changelog,
        version_history=record.version_history,
        update_available=update_available,
        update_required=update_required,
        version_gap=gap,
        current_version_deprecation_reason=(
            current_notice.deprecation_reason
            if update_required and current_notice
            else None
        ),
        release_channel=record.release_channel,
        observed_state=record.observed_state,
    )


__all__ = [
    "managed_resource_provider",
    "managed_resource_provider_by_id",
    "managed_resource_provider_from_record",
    "managed_resource_providers",
]
