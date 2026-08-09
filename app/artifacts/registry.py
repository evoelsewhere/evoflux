"""Format-driver registry for Artifact Fabric."""

from __future__ import annotations

from app.artifacts.domain import ArtifactFormat
from app.artifacts.drivers.base import ArtifactDriver


class ArtifactDriverRegistry:
    def __init__(self) -> None:
        self._drivers: dict[ArtifactFormat, ArtifactDriver] = {}

    def register(self, driver: ArtifactDriver) -> None:
        if driver.format in self._drivers:
            raise ValueError(f"artifact driver already registered: {driver.format}")
        self._drivers[driver.format] = driver

    def get(self, artifact_format: ArtifactFormat) -> ArtifactDriver:
        try:
            return self._drivers[artifact_format]
        except KeyError as exc:
            raise ValueError(f"unsupported artifact format: {artifact_format}") from exc

    def catalog(self) -> dict[str, object]:
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
                name: {
                    **driver.catalog(),
                    "extension": driver.extension,
                    "media_type": driver.media_type,
                    "driver_version": driver.version,
                    "protocol_version": driver.protocol_version,
                }
                for name, driver in self._drivers.items()
            },
        }


def build_default_registry() -> ArtifactDriverRegistry:
    from app.artifacts.drivers.docx import DocxArtifactDriver
    from app.artifacts.drivers.pdf import PdfArtifactDriver
    from app.artifacts.drivers.pptx import PptxArtifactDriver
    from app.artifacts.drivers.xlsx import XlsxArtifactDriver

    registry = ArtifactDriverRegistry()
    registry.register(DocxArtifactDriver())
    registry.register(XlsxArtifactDriver())
    registry.register(PptxArtifactDriver())
    registry.register(PdfArtifactDriver())
    return registry


__all__ = ["ArtifactDriverRegistry", "build_default_registry"]
