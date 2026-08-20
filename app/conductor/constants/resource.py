"""Managed-resource ownership and presentation constants."""

from __future__ import annotations

from enum import StrEnum


class ManagedResourceSource(StrEnum):
    CONDUCTOR = "conductor"


class ResourceTargetMode(StrEnum):
    WORK = "work"
    CODING = "coding"


class ResourceVersionGap(StrEnum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRERELEASE = "prerelease"
    UNKNOWN = "unknown"


class ResourceVersionStatus(StrEnum):
    BETA = "beta"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


DEFAULT_RESOURCE_TARGET_MODES = (
    ResourceTargetMode.WORK,
    ResourceTargetMode.CODING,
)
RESOURCE_MODE_SCOPE_FILENAME = ".evoflux.json"


MANAGED_RESOURCE_REMOVED_STATE = "removed"
