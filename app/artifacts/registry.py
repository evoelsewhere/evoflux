"""Format-driver registry for Artifact Fabric."""

from __future__ import annotations

from typing import Any

from app.artifacts.domain import ArtifactFormat
from app.artifacts.drivers.base import ArtifactDriver


class ArtifactDriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[str, ArtifactDriver] = {}

    def register(self, driver: ArtifactDriver) -> None:
        if driver.format in self._drivers:
            raise ValueError(f"artifact driver already registered: {driver.format}")
        self._drivers[driver.format] = driver

    def get(self, artifact_format: ArtifactFormat) -> ArtifactDriver:
        try:
            return self._drivers[artifact_format]
        except KeyError as exc:
            raise ValueError(f"unsupported artifact format: {artifact_format}") from exc

    def catalog(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "workflow": "immutable-native-document-revisions",
            "actions": [
                "catalog",
                "inspect",
                "validate",
                "preview",
                "publish",
                "status",
                "cancel",
            ],
            "invariants": [
                "Each format keeps its own native project schema and driver.",
                "Preview creates immutable candidate bytes plus QA evidence.",
                "Publish materializes the exact verified candidate and never rebuilds it.",
                "Jobs and revisions are durable and independent from the UI connection.",
            ],
            "formats": {
                name: self._describe_driver(driver)
                for name, driver in self._drivers.items()
            },
        }

    @staticmethod
    def _describe_driver(driver: ArtifactDriver) -> dict[str, Any]:
        metadata: dict[str, Any]
        try:
            metadata = {**driver.catalog(), "available": True}
        except ModuleNotFoundError as exc:
            if driver.required_extra is None:
                raise
            metadata = {
                "available": False,
                "required_extra": driver.required_extra,
                "unavailable_dependency": exc.name or "unknown",
            }
        return {
            **metadata,
            "extension": driver.extension,
            "media_type": driver.media_type,
            "driver_version": driver.version,
            "protocol_version": driver.protocol_version,
        }


def build_default_registry() -> ArtifactDriverRegistry:
    from app.plugin_platform.native import iter_builtin_native_providers

    registry = ArtifactDriverRegistry()
    for plugin_name, provider in iter_builtin_native_providers("artifact_provider"):
        drivers = provider()
        if not isinstance(drivers, (list, tuple)):
            raise TypeError(
                f"artifact provider from {plugin_name} must return a sequence"
            )
        for driver in drivers:
            registry.register(driver)
    return registry


__all__ = ["ArtifactDriverRegistry", "build_default_registry"]
