"""Provider-neutral client for the static plugin marketplace registry."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.plugin_platform.models import PluginInstallation

_MAX_REGISTRY_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class MarketplaceError(RuntimeError):
    """A safe, user-facing marketplace provider failure."""


class MarketplaceArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    url: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int | None = Field(default=None, gt=0)


class MarketplacePublisher(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    signature_algorithm: str = Field(alias="signatureAlgorithm")
    public_key: str | None = Field(default=None, alias="publicKey")
    signature: str | None = None


class MarketplaceVerification(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    state: Literal[
        "verified",
        "unverified",
        "revoked",
        "changed",
        "invalid",
        "unavailable",
        "failed",
    ]
    verified_at: str | None = Field(default=None, alias="verifiedAt")
    reason: str | None = None


class MarketplaceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)

    npm_package: str = Field(alias="npmPackage")
    name: str
    version: str
    description: str
    license: str
    portable: bool
    portable_components: list[str] = Field(alias="portableComponents")
    compatible_clients: list[str] = Field(alias="compatibleClients")
    host_capabilities: list[str] = Field(alias="hostCapabilities")
    skills: list[str]
    mcp_servers: list[str] = Field(alias="mcpServers")
    connections: list[dict[str, Any]]
    artifact: MarketplaceArtifact
    publisher: MarketplacePublisher
    verification: MarketplaceVerification
    lifecycle: str
    report_templates: list[dict[str, Any]] = Field(
        default_factory=list, alias="reportTemplates"
    )


class MarketplaceIndex(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)

    version: int
    generated_at: str | None = Field(default=None, alias="generatedAt")
    plugins: list[MarketplaceEntry]


class DownloadedArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    entry: MarketplaceEntry
    content: bytes
    sha256: str


class MarketplaceProvider:
    """Fetch and validate registry metadata and pinned package bytes.

    The provider performs no installation or persistence. Callers can stage
    the returned bytes and verify them before invoking the local installer.
    """

    def __init__(
        self,
        registry_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_registry_bytes: int = _MAX_REGISTRY_BYTES,
        max_artifact_bytes: int = _MAX_ARTIFACT_BYTES,
    ) -> None:
        self.registry_url = self._require_https(registry_url)
        self._transport = transport
        self._max_registry_bytes = max_registry_bytes
        self._max_artifact_bytes = max_artifact_bytes

    @staticmethod
    def _require_https(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise MarketplaceError("Marketplace URLs must use HTTPS")
        return url

    async def fetch_registry(self) -> MarketplaceIndex:
        payload = await self._get_bytes(self.registry_url, self._max_registry_bytes)
        try:
            return MarketplaceIndex.model_validate_json(payload)
        except ValueError as exc:
            raise MarketplaceError("Marketplace registry metadata is invalid") from exc

    async def download_artifact(self, entry: MarketplaceEntry) -> DownloadedArtifact:
        url = self._require_https(entry.artifact.url)
        content = await self._get_bytes(url, self._max_artifact_bytes)
        digest = hashlib.sha256(content).hexdigest()
        if digest != entry.artifact.sha256:
            raise MarketplaceError(
                f"Artifact digest mismatch for {entry.name}@{entry.version}"
            )
        if entry.artifact.size is not None and len(content) != entry.artifact.size:
            raise MarketplaceError(
                f"Artifact size mismatch for {entry.name}@{entry.version}"
            )
        return DownloadedArtifact(entry=entry, content=content, sha256=digest)

    async def _get_bytes(self, url: str, maximum: int) -> bytes:
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    url,
                    headers={"Accept": "application/json, application/octet-stream"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MarketplaceError("Marketplace request failed") from exc
        content_length = response.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > maximum
        ):
            raise MarketplaceError(
                "Marketplace response exceeds the configured size limit"
            )
        content = response.content
        if len(content) > maximum:
            raise MarketplaceError(
                "Marketplace response exceeds the configured size limit"
            )
        return content


async def install_marketplace_plugin(
    provider: MarketplaceProvider,
    entry: MarketplaceEntry,
    *,
    enabled: bool = False,
    allow_unverified: bool = False,
) -> PluginInstallation:
    """Stage a verified marketplace artifact through the local installer."""
    if entry.verification.state == "unverified" and not allow_unverified:
        raise MarketplaceError(
            f"Artifact requires trust review: {entry.name}@{entry.version} "
            f"({entry.verification.state})"
        )
    if entry.verification.state not in {"verified", "unverified"}:
        raise MarketplaceError(
            f"Artifact cannot be installed: {entry.name}@{entry.version} "
            f"({entry.verification.state})"
        )
    downloaded = await provider.download_artifact(entry)
    from app.plugin_platform.installer import install_plugin
    from app.plugin_platform.models import PluginProvenance

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".evoplugin", delete=False
        ) as temporary:
            temporary.write(downloaded.content)
            temporary_path = Path(temporary.name)
        provenance = PluginProvenance(
            registry_url=provider.registry_url,
            artifact_url=entry.artifact.url,
            source_revision=entry.version,
            publisher_id=entry.publisher.id,
            verification_state=entry.verification.state,
            verification_reason=entry.verification.reason,
            verified_at=entry.verification.verified_at,
        )
        return install_plugin(
            temporary_path,
            enabled=enabled,
            source_ref=entry.artifact.url,
            provenance=provenance,
        )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = [
    "DownloadedArtifact",
    "MarketplaceArtifact",
    "MarketplaceEntry",
    "MarketplaceError",
    "MarketplaceIndex",
    "MarketplaceProvider",
    "MarketplacePublisher",
    "MarketplaceVerification",
]
