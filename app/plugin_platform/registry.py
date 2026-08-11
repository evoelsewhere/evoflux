"""Atomic, local-first registry for installed Agent Plugins."""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.plugin_platform.models import PluginInstallation, PluginRegistryDocument


_LOCK = threading.RLock()
_MAX_REGISTRY_BYTES = 2 * 1024 * 1024


def plugin_platform_root() -> Path:
    return Path(settings.EVOFLUX_DATA_DIR) / "agent-plugins"


def registry_path() -> Path:
    return plugin_platform_root() / "registry.json"


def installed_root() -> Path:
    return plugin_platform_root() / "installed"


def plugin_data_root(installation_id: str) -> Path:
    return plugin_platform_root() / "data" / installation_id


def staging_root() -> Path:
    return Path(settings.EVOFLUX_CACHE_DIR) / "agent-plugins" / "staging"


def _read_document(*, strict: bool = False) -> PluginRegistryDocument:
    path = registry_path()
    if not path.exists():
        return PluginRegistryDocument()
    try:
        if path.stat().st_size > _MAX_REGISTRY_BYTES:
            raise ValueError("plugin registry exceeds its size limit")
        raw = json.loads(path.read_text(encoding="utf-8"))
        document = PluginRegistryDocument.model_validate(raw)
        persisted_builtins = [
            item for item in document.installations if item.source_type == "builtin"
        ]
        if persisted_builtins:
            logger.error(
                "plugin_registry_builtin_records_ignored path={} ids={}",
                path,
                [item.id for item in persisted_builtins],
            )
            document = document.model_copy(
                update={
                    "installations": [
                        item
                        for item in document.installations
                        if item.source_type != "builtin"
                    ]
                }
            )
        return document
    except Exception as exc:
        if strict:
            raise ValueError(f"Could not read plugin registry {path}: {exc}") from exc
        logger.error("plugin_registry_invalid path={} error={}", path, exc)
        return PluginRegistryDocument()


def _write_document(document: PluginRegistryDocument) -> None:
    if any(item.source_type == "builtin" for item in document.installations):
        raise ValueError(
            "Bundled Agent Plugins are virtual and cannot be persisted in the registry."
        )
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            document.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    fd, temporary = tempfile.mkstemp(
        prefix=".registry.", suffix=".tmp", dir=path.parent
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


def list_installations(*, enabled_only: bool = False) -> list[PluginInstallation]:
    with _LOCK:
        items = list(_read_document().installations)
    if enabled_only:
        items = [item for item in items if item.enabled]
    return sorted(items, key=lambda item: (item.name, item.id))


def list_effective_installations(
    *, enabled_only: bool = False
) -> list[PluginInstallation]:
    """Return user installations plus immutable plugins bundled with EvoFlux."""

    from app.plugin_platform.builtins import list_builtin_installations

    items = [*list_installations(), *list_builtin_installations()]
    if enabled_only:
        items = [item for item in items if item.enabled]
    # User-managed packages intentionally precede release-bundled packages.
    # Skill discovery preserves this order when two installations contribute
    # the same Skill name, giving users an explicit override seam while keeping
    # the bundled package as the fallback.
    return sorted(
        items,
        key=lambda item: (item.source_type == "builtin", item.name, item.id),
    )


def get_installation(installation_id: str) -> PluginInstallation | None:
    return next(
        (item for item in list_effective_installations() if item.id == installation_id),
        None,
    )


def add_installation(installation: PluginInstallation) -> PluginInstallation:
    if installation.source_type == "builtin":
        raise ValueError(
            "Bundled Agent Plugins are virtual and cannot be persisted in the registry."
        )
    with _LOCK:
        document = _read_document(strict=True)
        if any(item.id == installation.id for item in document.installations):
            raise ValueError(f"Plugin installation already exists: {installation.id}")
        if any(
            item.name == installation.name
            and item.source_ref == installation.source_ref
            for item in document.installations
        ):
            raise ValueError(
                f"Plugin {installation.name!r} is already installed from this source."
            )
        document.installations.append(installation)
        _write_document(document)
    return installation


def set_enabled(installation_id: str, enabled: bool) -> PluginInstallation:
    from datetime import UTC, datetime
    from app.plugin_platform.builtins import is_builtin_installation

    if is_builtin_installation(installation_id):
        raise ValueError("Bundled Agent Plugins are always enabled.")

    with _LOCK:
        document = _read_document(strict=True)
        for index, item in enumerate(document.installations):
            if item.id != installation_id:
                continue
            updated = item.model_copy(
                update={
                    "enabled": enabled,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            document.installations[index] = updated
            _write_document(document)
            return updated
    raise KeyError(installation_id)


def replace_installation(installation: PluginInstallation) -> PluginInstallation:
    """Atomically replace registry metadata for one existing installation."""

    if installation.source_type == "builtin":
        raise ValueError("Bundled Agent Plugins cannot be replaced.")
    with _LOCK:
        document = _read_document(strict=True)
        for index, item in enumerate(document.installations):
            if item.id != installation.id:
                continue
            document.installations[index] = installation
            _write_document(document)
            return installation
    raise KeyError(installation.id)


def remove_installation(installation_id: str) -> PluginInstallation:
    from app.plugin_platform.builtins import is_builtin_installation

    if is_builtin_installation(installation_id):
        raise ValueError("Bundled Agent Plugins cannot be uninstalled.")
    with _LOCK:
        document = _read_document(strict=True)
        for index, item in enumerate(document.installations):
            if item.id != installation_id:
                continue
            removed = document.installations.pop(index)
            _write_document(document)
            return removed
    raise KeyError(installation_id)


def registry_signature() -> tuple[int, int, int]:
    path = registry_path()
    try:
        stat_result = path.stat()
        digest = hashlib.blake2b(path.read_bytes(), digest_size=8).digest()
        return (
            stat_result.st_mtime_ns,
            stat_result.st_size,
            int.from_bytes(digest, "big"),
        )
    except OSError:
        return (0, 0, 0)


__all__ = [
    "add_installation",
    "get_installation",
    "installed_root",
    "list_installations",
    "list_effective_installations",
    "plugin_data_root",
    "plugin_platform_root",
    "registry_path",
    "registry_signature",
    "remove_installation",
    "replace_installation",
    "set_enabled",
    "staging_root",
]
