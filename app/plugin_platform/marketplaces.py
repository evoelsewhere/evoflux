"""Local marketplace source and catalog management for Agent Plugins."""

from __future__ import annotations

import ipaddress
import hashlib
import io
import json
import os
import re
import shutil
import socket
import stat
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.plugin_platform.extensions import CREDENTIALS_EXTENSION
from app.plugin_platform.installer import extract_plugin_archive, install_plugin
from app.plugin_platform.models import (
    MCP_SCHEMA_ID,
    PluginInspection,
    PluginInstallation,
)
from app.plugin_platform.registry import plugin_platform_root, staging_root
from app.plugin_platform.validator import inspect_plugin

_MAX_REGISTRY_BYTES = 2 * 1024 * 1024
_MAX_CATALOG_BYTES = 8 * 1024 * 1024
_MAX_REDIRECTS = 3
_FETCH_TIMEOUT = 15.0
_LOCK = threading.RLock()
_SOURCE_ID = re.compile(r"^[a-f0-9]{16}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
_ENV_REFERENCE = re.compile(r"^\$\{([A-Z_][A-Z0-9_]*)\}$")
_SENSITIVE_ENV = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL)", re.I
)
_PREVIEW_ID = re.compile(r"^[a-f0-9]{32}$")
_MAX_REMOTE_PACKAGE_BYTES = 50 * 1024 * 1024
_MAX_EXPANDED_REPOSITORY_BYTES = 120 * 1024 * 1024
_MAX_REPOSITORY_FILES = 4096
_PREVIEW_TTL_SECONDS = 15 * 60


class MarketplaceKind(StrEnum):
    """Catalog formats understood by the host."""

    agent_plugins = "agent_plugins"
    claude_code = "claude_code"


MarketplaceCompatibility = Literal["compatible", "partial", "unsupported", "unknown"]
MarketplaceSourceType = Literal[
    "artifact",
    "relative",
    "url",
    "git-subdir",
    "github",
    "command",
    "npm",
    "unsupported",
]


class MarketplaceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_SOURCE_ID.pattern)
    kind: MarketplaceKind
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    added_at: datetime
    last_synced_at: datetime | None = None
    last_error: str | None = None


class MarketplacePlugin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    marketplace_id: str = Field(pattern=_SOURCE_ID.pattern)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    version: str | None = None
    author: str | None = None
    source_type: MarketplaceSourceType
    source_url: str | None = None
    source_path: str | None = None
    source_ref: str | None = None
    components: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    compatibility: MarketplaceCompatibility = "unknown"
    installable: bool = False
    verification: str = "unknown"
    artifact_sha256: str | None = None
    artifact_size: int | None = None


class _MarketplaceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    sources: list[MarketplaceSource] = Field(default_factory=list)


class _CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    plugins: list[MarketplacePlugin] = Field(default_factory=list)


class MarketplacePluginPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: str = Field(pattern=_PREVIEW_ID.pattern)
    plugin: MarketplacePlugin
    supported_components: list[str] = Field(default_factory=list)
    unsupported_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    inspection: PluginInspection


@dataclass(frozen=True)
class _MarketplaceNormalization:
    root: Path
    supported_components: list[str]
    unsupported_components: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class _MarketplacePreviewState:
    source_id: str
    source_name: str
    plugin_name: str
    source_ref: str
    root: Path
    content_sha256: str
    expires_at: float
    unsupported_components: tuple[str, ...]


_PREVIEWS: dict[str, _MarketplacePreviewState] = {}
_PREVIEW_LOCK = threading.RLock()


def validate_marketplace_url(url: str) -> str:
    """Validate a public HTTPS URL before a server-side fetch."""
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Marketplace URL is invalid or too long.")
    parsed = urlsplit(url.strip())
    if parsed.scheme.casefold() != "https":
        raise ValueError("Marketplace URL must use HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(
            "Marketplace URL must have a public hostname and no credentials."
        )
    if parsed.fragment:
        raise ValueError("Marketplace URL must not contain a fragment.")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("Marketplace URL must resolve to a public host.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Marketplace URL must resolve to a public host.")
    return parsed.geturl()


def _assert_public_dns(hostname: str, port: int) -> None:
    """Reject DNS names that resolve to any private or special-use address."""
    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Marketplace host could not be resolved.") from exc
    if not addresses:
        raise ValueError("Marketplace URL must resolve only to public addresses.")
    for item in addresses:
        resolved_host = item[4][0]
        if (
            not isinstance(resolved_host, str)
            or not ipaddress.ip_address(resolved_host.split("%", 1)[0]).is_global
        ):
            raise ValueError("Marketplace URL must resolve only to public addresses.")


def _fetch_bytes(url: str, *, limit: int) -> bytes:
    current = validate_marketplace_url(url)
    for redirect_count in range(_MAX_REDIRECTS + 1):
        parsed = urlsplit(current)
        _assert_public_dns(parsed.hostname or "", parsed.port or 443)
        try:
            with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=False) as client:
                with client.stream(
                    "GET",
                    current,
                    headers={"Accept": "application/json, application/octet-stream"},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location or redirect_count == _MAX_REDIRECTS:
                            raise ValueError(
                                "Marketplace returned an invalid redirect."
                            )
                        current = validate_marketplace_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > limit:
                        raise ValueError("Marketplace response exceeds its size limit.")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(
                                "Marketplace response exceeds its size limit."
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not fetch marketplace URL: {exc}") from exc
    raise ValueError("Marketplace redirect limit exceeded.")


def fetch_marketplace_json(url: str) -> dict[str, Any]:
    """Fetch a bounded JSON marketplace document."""
    payload = _fetch_bytes(url, limit=_MAX_CATALOG_BYTES)
    try:
        result = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Marketplace response is not valid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("Marketplace document must be a JSON object.")
    return result


def _marketplaces_path() -> Path:
    return plugin_platform_root() / "marketplaces.json"


def _cache_path(source_id: str) -> Path:
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("Marketplace id is invalid.")
    return plugin_platform_root() / "marketplace-cache" / f"{source_id}.json"


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > _MAX_REGISTRY_BYTES:
        raise ValueError("Marketplace data exceeds its size limit.")
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_marketplaces() -> _MarketplaceDocument:
    path = _marketplaces_path()
    if not path.exists():
        return _MarketplaceDocument()
    try:
        if path.stat().st_size > _MAX_REGISTRY_BYTES:
            raise ValueError("Marketplace source registry exceeds its size limit.")
        return _MarketplaceDocument.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError(f"Could not read marketplace sources: {exc}") from exc


def _write_marketplaces(document: _MarketplaceDocument) -> None:
    _atomic_write_json(_marketplaces_path(), document.model_dump(mode="json"))


def _read_catalog(source_id: str) -> _CatalogDocument:
    path = _cache_path(source_id)
    if not path.exists():
        return _CatalogDocument()
    try:
        if path.stat().st_size > _MAX_REGISTRY_BYTES:
            raise ValueError("Marketplace cache exceeds its size limit.")
        return _CatalogDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError(f"Could not read marketplace cache: {exc}") from exc


def add_marketplace(*, kind: MarketplaceKind, name: str, url: str) -> MarketplaceSource:
    """Persist a new marketplace source without fetching it."""
    clean_url = validate_marketplace_url(url)
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Marketplace name is required.")
    with _LOCK:
        document = _read_marketplaces()
        if any(
            item.kind == kind
            and item.url.casefold().rstrip("/") == clean_url.casefold().rstrip("/")
            for item in document.sources
        ):
            raise ValueError("This marketplace URL was already added.")
        source = MarketplaceSource(
            id=uuid.uuid4().hex[:16],
            kind=kind,
            name=clean_name,
            url=clean_url,
            added_at=datetime.now(UTC),
        )
        _write_marketplaces(
            document.model_copy(update={"sources": [*document.sources, source]})
        )
        return source


def list_marketplaces() -> list[MarketplaceSource]:
    with _LOCK:
        return sorted(
            _read_marketplaces().sources,
            key=lambda item: (item.name.casefold(), item.id),
        )


def _get_marketplace(source_id: str) -> MarketplaceSource:
    if not _SOURCE_ID.fullmatch(source_id):
        raise ValueError("Marketplace id is invalid.")
    for source in _read_marketplaces().sources:
        if source.id == source_id:
            return source
    raise KeyError(f"Marketplace not found: {source_id}")


def remove_marketplace(source_id: str) -> MarketplaceSource:
    """Remove only the catalog source/cache, never installed plugin files."""
    with _LOCK:
        document = _read_marketplaces()
        source = next((item for item in document.sources if item.id == source_id), None)
        if source is None:
            raise KeyError(f"Marketplace not found: {source_id}")
        _write_marketplaces(
            document.model_copy(
                update={
                    "sources": [
                        item for item in document.sources if item.id != source_id
                    ]
                }
            )
        )
        try:
            _cache_path(source_id).unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"Could not remove marketplace cache: {exc}") from exc
        return source


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _author(value: object) -> str | None:
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, Mapping):
        return _string(cast(Mapping[str, object], value).get("name"))
    return None


def _compatibility(
    components: list[str], *, portable: bool, compatible_clients: list[str]
) -> MarketplaceCompatibility:
    supported = {"skills", "mcp"}
    if not portable or (compatible_clients and "evoflux" not in compatible_clients):
        return "unsupported"
    supported_components = supported.intersection(components)
    unsupported_components = set(components) - supported
    if supported_components and unsupported_components:
        return "partial"
    if supported_components:
        return "compatible"
    return "unknown" if not components else "unsupported"


def _parse_agent_plugins(
    source: MarketplaceSource, document: Mapping[str, Any]
) -> list[MarketplacePlugin]:
    if document.get("version") != 1 or not isinstance(document.get("plugins"), list):
        raise ValueError(
            "Agent Plugins registry must contain version 1 and a plugins array."
        )
    result: list[MarketplacePlugin] = []
    for entry in document["plugins"]:
        if not isinstance(entry, Mapping):
            continue
        name = _string(entry.get("name"))
        artifact = entry.get("artifact")
        if not name or not isinstance(artifact, Mapping):
            continue
        artifact_url = _string(artifact.get("url"))
        digest = _string(artifact.get("sha256"))
        size_value = artifact.get("size")
        if not artifact_url or not digest or not _SHA256.fullmatch(digest):
            continue
        if (
            not isinstance(size_value, int)
            or isinstance(size_value, bool)
            or size_value <= 0
        ):
            continue
        try:
            validate_marketplace_url(artifact_url)
        except ValueError:
            continue
        raw_components = entry.get("portableComponents", [])
        components = (
            [item for item in raw_components if isinstance(item, str)]
            if isinstance(raw_components, list)
            else []
        )
        clients_raw = entry.get("compatibleClients", [])
        clients = (
            [item for item in clients_raw if isinstance(item, str)]
            if isinstance(clients_raw, list)
            else []
        )
        portable = entry.get("portable") is True
        compatibility = _compatibility(
            components, portable=portable, compatible_clients=clients
        )
        verification = entry.get("verification")
        if isinstance(verification, Mapping):
            verification_state = _string(verification.get("state")) or "unverified"
        else:
            verification_state = (
                "verified" if entry.get("verified") is True else "unverified"
            )
        result.append(
            MarketplacePlugin(
                id=f"{source.id}:{name}",
                marketplace_id=source.id,
                name=name,
                description=_string(entry.get("description")) or "",
                version=_string(entry.get("version")),
                author=_author(entry.get("publisher") or entry.get("author")),
                source_type="artifact",
                source_url=artifact_url,
                components=components,
                categories=_string_list(entry.get("categories")),
                keywords=_string_list(entry.get("keywords")),
                compatibility=compatibility,
                installable=compatibility in {"compatible", "partial"},
                verification=verification_state,
                artifact_sha256=digest.lower(),
                artifact_size=size_value,
            )
        )
    return result


def _parse_claude_marketplace(
    source: MarketplaceSource, document: Mapping[str, Any]
) -> list[MarketplacePlugin]:
    entries = document.get("plugins")
    if not isinstance(entries, list):
        raise ValueError("Claude marketplace must contain a plugins array.")
    result: list[MarketplacePlugin] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        name = _string(entry.get("name"))
        raw_source = entry.get("source")
        if not name or raw_source is None:
            continue
        source_type: MarketplaceSourceType = "unsupported"
        source_url: str | None = None
        source_path: str | None = None
        source_ref: str | None = None
        if isinstance(raw_source, str) and raw_source.startswith(("./", "../")):
            source_type = "relative"
            source_path = raw_source
        elif isinstance(raw_source, Mapping):
            kind = _string(raw_source.get("source"))
            if kind in {"url", "git-subdir", "github"}:
                source_type = cast(MarketplaceSourceType, kind)
                source_url = _string(raw_source.get("url")) or _string(
                    raw_source.get("repo")
                )
                source_path = _string(raw_source.get("path"))
                source_ref = _string(raw_source.get("sha")) or _string(
                    raw_source.get("ref")
                )
            elif kind in {"command", "npm"}:
                source_type = cast(MarketplaceSourceType, kind)
        elif isinstance(raw_source, str):
            source_type = "unsupported"
        supported_source = source_type in {"relative", "url", "git-subdir", "github"}
        result.append(
            MarketplacePlugin(
                id=f"{source.id}:{name}",
                marketplace_id=source.id,
                name=name,
                description=_string(entry.get("description")) or "",
                version=_string(entry.get("version")),
                author=_author(entry.get("author")),
                source_type=source_type,
                source_url=source_url,
                source_path=source_path,
                source_ref=source_ref,
                categories=_string_list(entry.get("categories")),
                keywords=_string_list(entry.get("keywords")),
                compatibility="unknown" if supported_source else "unsupported",
                installable=supported_source,
                verification="unverified",
            )
        )
    return result


def sync_marketplace(
    source_id: str,
    *,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> MarketplaceSource:
    """Fetch and cache catalog metadata; stale cache survives fetch errors."""
    fetch = fetcher or fetch_marketplace_json
    with _LOCK:
        source = _get_marketplace(source_id)
    try:
        document = fetch(source.url)
        if not isinstance(document, Mapping):
            raise ValueError("Marketplace response must be a JSON object.")
        plugins = (
            _parse_agent_plugins(source, document)
            if source.kind == MarketplaceKind.agent_plugins
            else _parse_claude_marketplace(source, document)
        )
        catalog = _CatalogDocument(plugins=plugins)
        _atomic_write_json(_cache_path(source.id), catalog.model_dump(mode="json"))
    except Exception as exc:
        with _LOCK:
            current = _read_marketplaces()
            updated = [
                item.model_copy(update={"last_error": str(exc)[:500]})
                if item.id == source.id
                else item
                for item in current.sources
            ]
            _write_marketplaces(current.model_copy(update={"sources": updated}))
        raise

    synced = source.model_copy(
        update={"last_synced_at": datetime.now(UTC), "last_error": None}
    )
    with _LOCK:
        current = _read_marketplaces()
        updated = [synced if item.id == source.id else item for item in current.sources]
        _write_marketplaces(current.model_copy(update={"sources": updated}))
    return synced


def search_marketplace_plugins(
    query: str = "",
    *,
    marketplace_id: str | None = None,
) -> list[MarketplacePlugin]:
    """Search only synchronized catalog metadata; never perform network I/O."""
    sources = list_marketplaces()
    if marketplace_id is not None:
        sources = [source for source in sources if source.id == marketplace_id]
    needle = query.strip().casefold()
    results: list[MarketplacePlugin] = []
    for source in sources:
        results.extend(_read_catalog(source.id).plugins)
    if needle:
        results = [
            item
            for item in results
            if needle
            in f"{item.name} {item.description} {item.author or ''}".casefold()
        ]
    return sorted(results, key=lambda item: (item.name.casefold(), item.marketplace_id))


def _safe_relative_source_path(value: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/").removeprefix("./")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
    ):
        raise ValueError("Claude plugin source path is not a safe relative path.")
    return path.parts


def _github_marketplace_context(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname != "raw.githubusercontent.com" or len(parts) < 5:
        raise ValueError(
            "Relative Claude sources require a raw GitHub marketplace URL."
        )
    owner, repository, revision = parts[:3]
    if parts[3:] != [".claude-plugin", "marketplace.json"]:
        raise ValueError(
            "Claude marketplace URL must end in .claude-plugin/marketplace.json."
        )
    return owner, repository.removesuffix(".git"), revision


def _github_repository(value: str) -> tuple[str, str]:
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        owner, repository = value.split("/", 1)
        return owner, repository.removesuffix(".git")
    parsed = urlsplit(value)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
        raise ValueError(
            "Claude plugin source must identify a public GitHub repository."
        )
    return parts[0], parts[1].removesuffix(".git")


def _github_archive_url(owner: str, repository: str, revision: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", repository
    ):
        raise ValueError("GitHub repository coordinates are invalid.")
    if not revision or revision.startswith("-") or ".." in revision:
        raise ValueError("Claude plugin source revision is invalid.")
    return f"https://codeload.github.com/{owner}/{repository}/zip/{revision}"


def _extract_repository_subdirectory(
    archive_bytes: bytes,
    destination: Path,
    source_path: str | None,
) -> Path:
    """Safely extract only the selected plugin subtree from a GitHub archive."""
    if len(archive_bytes) > _MAX_REMOTE_PACKAGE_BYTES:
        raise ValueError("Claude plugin archive exceeds its compressed size limit.")
    prefix = _safe_relative_source_path(source_path) if source_path else ()
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    expanded_size = 0
    extracted = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_REPOSITORY_FILES:
                raise ValueError("Claude plugin archive contains too many entries.")
            for info in infos:
                raw_name = info.filename
                if "\\" in raw_name:
                    raise ValueError("Claude plugin archive contains an unsafe path.")
                member = PurePosixPath(raw_name)
                if member.is_absolute() or any(
                    part in {"", ".", ".."} or ":" in part for part in member.parts
                ):
                    raise ValueError("Claude plugin archive contains an unsafe path.")
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("Claude plugin archive contains a symbolic link.")
                if info.flag_bits & 0x1:
                    raise ValueError(
                        "Encrypted Claude plugin archives are not supported."
                    )
                expanded_size += info.file_size
                if expanded_size > _MAX_EXPANDED_REPOSITORY_BYTES:
                    raise ValueError(
                        "Claude plugin archive exceeds its expanded size limit."
                    )
                if info.file_size and info.compress_size == 0:
                    raise ValueError(
                        "Claude plugin archive has an invalid compression ratio."
                    )
                if info.compress_size and info.file_size > info.compress_size * 1000:
                    raise ValueError(
                        "Claude plugin archive has an invalid compression ratio."
                    )

                parts = member.parts
                if len(parts) < 2:
                    continue
                relative_parts = parts[1:]
                if prefix:
                    if relative_parts[: len(prefix)] != prefix:
                        continue
                    relative_parts = relative_parts[len(prefix) :]
                if not relative_parts or info.is_dir():
                    continue
                relative = PurePosixPath(*relative_parts)
                relative_key = relative.as_posix().casefold()
                if relative_key in seen:
                    raise ValueError("Claude plugin archive contains duplicate paths.")
                seen.add(relative_key)
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("Claude plugin archive contains an unsafe path.")
                size = 0
                with archive.open(info) as source, target.open("xb") as output:
                    while chunk := source.read(64 * 1024):
                        size += len(chunk)
                        if size > info.file_size:
                            raise ValueError(
                                "Claude plugin archive entry exceeds its declared size."
                            )
                        output.write(chunk)
                if size != info.file_size:
                    raise ValueError("Claude plugin archive entry has an invalid size.")
                extracted += 1
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(f"Could not unpack Claude plugin source: {exc}") from exc
    if extracted == 0:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError(
            "Claude plugin source path was not found in the GitHub archive."
        )
    return destination


def _rewrite_claude_placeholders(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("${CLAUDE_PLUGIN_ROOT}", "${PLUGIN_ROOT}").replace(
            "${CLAUDE_PLUGIN_DATA}", "${PLUGIN_DATA}"
        )
    if isinstance(value, list):
        return [_rewrite_claude_placeholders(item) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_claude_placeholders(item) for key, item in value.items()}
    return value


def _normalize_claude_mcp(
    source: Path,
    destination: Path,
) -> tuple[bool, list[dict[str, Any]]]:
    config_path = source / ".mcp.json"
    manifest_path = source / ".claude-plugin" / "plugin.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Claude plugin manifest is not valid JSON.") from exc
        if isinstance(loaded_manifest, dict):
            manifest = loaded_manifest
    if config_path.is_file():
        try:
            raw_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Claude MCP configuration is not valid JSON.") from exc
    elif isinstance(manifest.get("mcpServers"), dict):
        raw_config = {"mcpServers": manifest["mcpServers"]}
    else:
        return False, []

    if not isinstance(raw_config, dict):
        raise ValueError("Claude MCP configuration must be a JSON object.")
    servers = raw_config.get("mcpServers", raw_config)
    if not isinstance(servers, dict) or not servers:
        raise ValueError("Claude MCP configuration must contain named servers.")

    credentials: dict[str, dict[str, Any]] = {}
    normalized: dict[str, dict[str, Any]] = {}
    for server_name, raw_server in servers.items():
        if not isinstance(server_name, str) or not isinstance(raw_server, dict):
            raise ValueError("Claude MCP server definitions must be objects.")
        server = _rewrite_claude_placeholders(raw_server)
        server_type = server.get("type")
        if server_type is None:
            server_type = "stdio" if isinstance(server.get("command"), str) else None
            if server_type is None and isinstance(server.get("url"), str):
                server_type = "streamable-http"
        if server_type == "http":
            server_type = "streamable-http"
        if server_type not in {"stdio", "streamable-http", "sse"}:
            raise ValueError(
                f"Claude MCP server {server_name!r} has an unsupported transport."
            )
        server["type"] = server_type

        if server_type == "stdio":
            allowed = {"type", "command", "args", "env", "cwd"}
            if (
                not isinstance(server.get("command"), str)
                or not server["command"].strip()
            ):
                raise ValueError(
                    f"Claude stdio MCP server {server_name!r} needs a command."
                )
            env = server.get("env", {})
            if not isinstance(env, dict):
                raise ValueError(
                    f"Claude MCP server {server_name!r} has invalid environment values."
                )
            for env_name, env_value in env.items():
                if not isinstance(env_name, str) or not isinstance(env_value, str):
                    raise ValueError("Claude MCP environment values must be strings.")
                reference = _ENV_REFERENCE.fullmatch(env_value)
                if reference:
                    referenced_name = reference.group(1)
                    if referenced_name != env_name:
                        raise ValueError(
                            "MCP credential placeholders must match their environment key."
                        )
                    if env_name in {"PLUGIN_ROOT", "PLUGIN_DATA", "PATH"}:
                        raise ValueError(
                            "Claude MCP configuration cannot request a reserved environment key."
                        )
                    key = re.sub(r"[^a-z0-9_.-]", "_", env_name.casefold())[:64]
                    credentials[key] = {
                        "key": key,
                        "label": env_name.replace("_", " ").title(),
                        "env": env_name,
                        "type": "secret" if _SENSITIVE_ENV.search(env_name) else "text",
                        "required": True,
                    }
                elif _SENSITIVE_ENV.search(env_name) and env_value:
                    raise ValueError(
                        "Literal secrets are not imported from marketplace packages."
                    )
                elif "${" in env_value:
                    raise ValueError("Unrecognized MCP environment placeholder.")
            if set(server) - allowed:
                raise ValueError(
                    f"Claude stdio MCP server {server_name!r} has unsupported fields."
                )
        else:
            allowed = {"type", "url", "headers"}
            if not isinstance(server.get("url"), str) or not server["url"].strip():
                raise ValueError(f"Claude HTTP MCP server {server_name!r} needs a URL.")
            if "${" in server["url"]:
                raise ValueError(
                    "Dynamic HTTP MCP URLs are not imported from marketplace packages."
                )
            headers = server.get("headers", {})
            if not isinstance(headers, dict) or any(
                not isinstance(key, str) or not isinstance(value, str) or "${" in value
                for key, value in headers.items()
            ):
                raise ValueError(
                    "Dynamic or invalid MCP HTTP headers are not supported."
                )
            if set(server) - allowed:
                raise ValueError(
                    f"Claude HTTP MCP server {server_name!r} has unsupported fields."
                )
        normalized[server_name] = server

    if not normalized:
        raise ValueError("Claude MCP configuration has no supported servers.")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": normalized,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True, list(credentials.values())


def normalize_claude_plugin_directory(
    source: Path,
    destination: Path,
    *,
    name: str,
    description: str = "",
    version: str | None = None,
) -> _MarketplaceNormalization:
    """Convert only Claude Skills/MCP into an Agent Plugins 1.0 package."""
    if not source.is_dir() or destination.exists():
        raise ValueError("Claude plugin source or destination is invalid.")
    claude_manifest_path = source / ".claude-plugin" / "plugin.json"
    claude_manifest: dict[str, Any] = {}
    if claude_manifest_path.is_file():
        try:
            loaded = json.loads(claude_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Claude plugin manifest is not valid JSON.") from exc
        if not isinstance(loaded, dict):
            raise ValueError("Claude plugin manifest must be a JSON object.")
        claude_manifest = loaded

    destination.mkdir(parents=True)
    supported: list[str] = []
    unsupported: set[str] = set()
    warnings: list[str] = []
    skills = source / "skills"
    if skills.is_dir():
        skill_files = list(skills.rglob("SKILL.md"))
        if skill_files:
            for path in skills.rglob("*"):
                if path.is_symlink():
                    raise ValueError("Claude Skills cannot contain symbolic links.")
            shutil.copytree(skills, destination / "skills")
            supported.append("skills")
        elif "skills" in claude_manifest:
            unsupported.add("skills")
    elif "skills" in claude_manifest:
        unsupported.add("skills")

    try:
        has_mcp, credential_fields = _normalize_claude_mcp(source, destination)
        if has_mcp:
            supported.append("mcp")
    except ValueError as exc:
        unsupported.add("mcp")
        warnings.append(str(exc))
        credential_fields = []
        (destination / "mcp.json").unlink(missing_ok=True)

    component_directories = {
        "agents": "agents",
        "commands": "commands",
        "hooks": "hooks",
        "lspServers": "lsp",
        "outputStyles": "output-styles",
    }
    for component, directory in component_directories.items():
        if component in claude_manifest or (source / directory).exists():
            unsupported.add(component)

    normalized_name = (
        re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:64].rstrip("-")
    )
    if not normalized_name:
        raise ValueError(
            "Claude plugin name cannot be converted to an Agent Plugin name."
        )
    normalized_manifest: dict[str, Any] = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": normalized_name,
        "compatibility": {
            "portableComponents": supported,
            "compatibleClients": ["evoflux"],
            "hostCapabilities": [],
        },
    }
    normalized_version = _string(claude_manifest.get("version")) or version
    if normalized_version:
        normalized_manifest["version"] = normalized_version
    normalized_description = _string(claude_manifest.get("description")) or description
    if normalized_description:
        normalized_manifest["description"] = normalized_description
    author = _author(claude_manifest.get("author"))
    if author:
        normalized_manifest["author"] = {"name": author}
    if credential_fields:
        normalized_manifest["extensions"] = {
            CREDENTIALS_EXTENSION: {"fields": credential_fields}
        }
    (destination / "plugin.json").write_text(
        json.dumps(normalized_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return _MarketplaceNormalization(
        root=destination,
        supported_components=sorted(supported),
        unsupported_components=sorted(unsupported),
        warnings=warnings,
    )


def _find_cached_plugin(marketplace_id: str, plugin_name: str) -> MarketplacePlugin:
    matches = [
        item
        for item in _read_catalog(marketplace_id).plugins
        if item.name == plugin_name or item.id == plugin_name
    ]
    if not matches:
        raise KeyError(f"Marketplace plugin not found: {plugin_name}")
    if len(matches) > 1:
        raise ValueError("Marketplace plugin id is ambiguous; use its exact name.")
    return matches[0]


def _claude_archive_location(
    marketplace: MarketplaceSource,
    plugin: MarketplacePlugin,
) -> tuple[str, str]:
    source_path = plugin.source_path
    if plugin.source_type == "relative":
        owner, repository, revision = _github_marketplace_context(marketplace.url)
        safe_path = "/".join(_safe_relative_source_path(source_path or ""))
        return _github_archive_url(owner, repository, revision), safe_path
    if (
        plugin.source_type not in {"url", "git-subdir", "github"}
        or not plugin.source_url
    ):
        raise ValueError("This Claude plugin source type is not supported by EvoFlux.")
    owner, repository = _github_repository(plugin.source_url)
    revision = plugin.source_ref or "main"
    if plugin.source_type == "github" and not source_path:
        source_path = None
    safe_path = "/".join(_safe_relative_source_path(source_path)) if source_path else ""
    return _github_archive_url(owner, repository, revision), safe_path


def _preview_directory(preview_id: str) -> Path:
    if not _PREVIEW_ID.fullmatch(preview_id):
        raise ValueError("Marketplace preview id is invalid.")
    return staging_root() / "marketplace-previews" / preview_id


def _clean_expired_previews() -> None:
    now = datetime.now(UTC).timestamp()
    expired: list[_MarketplacePreviewState] = []
    with _PREVIEW_LOCK:
        for preview_id, state in list(_PREVIEWS.items()):
            if state.expires_at <= now:
                expired.append(state)
                del _PREVIEWS[preview_id]
    for state in expired:
        shutil.rmtree(state.root.parent, ignore_errors=True)


def marketplace_preview_root(preview_id: str) -> Path | None:
    """Return a live prepared package root for a known preview token."""
    _clean_expired_previews()
    with _PREVIEW_LOCK:
        state = _PREVIEWS.get(preview_id)
        return state.root if state is not None else None


def prepare_marketplace_plugin(
    marketplace_id: str,
    plugin_name: str,
    *,
    byte_fetcher: Callable[[str, int], bytes] | None = None,
) -> MarketplacePluginPreview:
    """Download, verify, normalize, and inspect a package without enabling it."""
    _clean_expired_previews()
    fetch = byte_fetcher or (lambda url, limit: _fetch_bytes(url, limit=limit))
    marketplace = _get_marketplace(marketplace_id)
    plugin = _find_cached_plugin(marketplace_id, plugin_name)
    if not plugin.installable and marketplace.kind == MarketplaceKind.agent_plugins:
        raise ValueError("This Agent Plugin is not portable to EvoFlux.")
    if plugin.compatibility == "unsupported" or plugin.source_type in {
        "command",
        "npm",
        "unsupported",
    }:
        raise ValueError("This Claude plugin source is not supported by EvoFlux.")

    preview_id = uuid.uuid4().hex
    preview_root = _preview_directory(preview_id)
    preview_root.mkdir(parents=True, exist_ok=False)
    try:
        source_ref = plugin.source_ref or plugin.artifact_sha256 or "unverified"
        supported: list[str]
        unsupported: list[str]
        warnings: list[str] = []
        if marketplace.kind == MarketplaceKind.agent_plugins:
            if (
                not plugin.source_url
                or not plugin.artifact_sha256
                or not plugin.artifact_size
            ):
                raise ValueError(
                    "Agent Plugin registry entry lacks artifact provenance."
                )
            if plugin.artifact_size > _MAX_REMOTE_PACKAGE_BYTES:
                raise ValueError(
                    "Agent Plugin artifact exceeds the download size limit."
                )
            artifact = fetch(plugin.source_url, _MAX_REMOTE_PACKAGE_BYTES)
            if len(artifact) != plugin.artifact_size:
                raise ValueError(
                    "Agent Plugin artifact size does not match its registry entry."
                )
            artifact_digest = hashlib.sha256(artifact).hexdigest()
            if artifact_digest != plugin.artifact_sha256:
                raise ValueError(
                    "Agent Plugin artifact digest does not match its registry entry."
                )
            archive_path = preview_root / "artifact.evoplugin"
            archive_path.write_bytes(artifact)
            package_root = extract_plugin_archive(
                archive_path, preview_root / "package"
            )
            inspection = inspect_plugin(package_root)
            source_ref = artifact_digest
            supported = []
            if inspection.skills:
                supported.append("skills")
            if inspection.mcp_servers:
                supported.append("mcp")
            unsupported = sorted(set(plugin.components) - set(supported))
        else:
            archive_url, source_path = _claude_archive_location(marketplace, plugin)
            archive_bytes = fetch(archive_url, _MAX_REMOTE_PACKAGE_BYTES)
            source_root = _extract_repository_subdirectory(
                archive_bytes,
                preview_root / "source",
                source_path or None,
            )
            normalized = normalize_claude_plugin_directory(
                source_root,
                preview_root / "package",
                name=plugin.name,
                description=plugin.description,
                version=plugin.version,
            )
            inspection = inspect_plugin(normalized.root)
            supported = normalized.supported_components
            unsupported = normalized.unsupported_components
            warnings = normalized.warnings
            source_ref = (
                f"{source_path or '.'}@{hashlib.sha256(archive_bytes).hexdigest()}"
            )

        if not inspection.valid or not inspection.content_sha256:
            raise ValueError(
                "Marketplace plugin failed Agent Plugins 1.0 validation: "
                + "; ".join(
                    item.message
                    for item in inspection.diagnostics
                    if item.severity == "error"
                )
            )
        compatibility: MarketplaceCompatibility
        if not supported:
            compatibility = "unsupported"
        elif unsupported:
            compatibility = "partial"
        else:
            compatibility = "compatible"
        reviewed_plugin = plugin.model_copy(
            update={
                "components": sorted(supported + unsupported),
                "compatibility": compatibility,
                "installable": bool(supported),
                "verification": plugin.verification,
            }
        )
        if not reviewed_plugin.installable:
            raise ValueError(
                "Marketplace plugin has no components supported by EvoFlux."
            )
        state = _MarketplacePreviewState(
            source_id=marketplace.id,
            source_name=marketplace.name,
            plugin_name=plugin.name,
            source_ref=source_ref,
            root=Path(inspection.root),
            content_sha256=inspection.content_sha256,
            expires_at=datetime.now(UTC).timestamp() + _PREVIEW_TTL_SECONDS,
            unsupported_components=tuple(sorted(unsupported)),
        )
        with _PREVIEW_LOCK:
            _PREVIEWS[preview_id] = state
        return MarketplacePluginPreview(
            preview_id=preview_id,
            plugin=reviewed_plugin,
            supported_components=sorted(supported),
            unsupported_components=sorted(unsupported),
            warnings=warnings,
            inspection=inspection,
        )
    except Exception:
        shutil.rmtree(preview_root, ignore_errors=True)
        raise


def install_marketplace_preview(
    preview_id: str,
    *,
    allow_partial: bool = False,
) -> PluginInstallation:
    """Install a reviewed marketplace preview disabled, preserving provenance."""
    _clean_expired_previews()
    if not _PREVIEW_ID.fullmatch(preview_id):
        raise ValueError("Marketplace preview id is invalid.")
    with _PREVIEW_LOCK:
        state = _PREVIEWS.get(preview_id)
    if state is None:
        raise KeyError("Marketplace preview expired or does not exist.")
    if state.unsupported_components and not allow_partial:
        unsupported = ", ".join(state.unsupported_components)
        raise ValueError(
            "Marketplace plugin includes unsupported components "
            f"({unsupported}); explicit consent is required to install supported components only."
        )
    inspection = inspect_plugin(state.root)
    if (
        not inspection.valid
        or not inspection.content_sha256
        or inspection.content_sha256 != state.content_sha256
        or any(item.severity == "error" for item in inspection.diagnostics)
    ):
        raise ValueError("Marketplace preview changed after compatibility review.")
    source_ref = f"marketplace:{state.source_id}/{state.plugin_name}@{state.source_ref}"
    installation = install_plugin(
        state.root,
        enabled=False,
        source_ref=source_ref,
        origin={
            "kind": "marketplace",
            "marketplace_id": state.source_id,
            "marketplace_name": state.source_name,
            "source_ref": source_ref,
        },
    )
    with _PREVIEW_LOCK:
        _PREVIEWS.pop(preview_id, None)
    shutil.rmtree(state.root.parent, ignore_errors=True)
    return installation


__all__ = [
    "MarketplaceCompatibility",
    "MarketplaceKind",
    "MarketplacePlugin",
    "MarketplacePluginPreview",
    "MarketplaceSource",
    "add_marketplace",
    "fetch_marketplace_json",
    "install_marketplace_preview",
    "list_marketplaces",
    "normalize_claude_plugin_directory",
    "prepare_marketplace_plugin",
    "remove_marketplace",
    "search_marketplace_plugins",
    "sync_marketplace",
    "validate_marketplace_url",
]
