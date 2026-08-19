"""Immutable, portable Agent Plugin packages bundled with EvoFlux releases."""

from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path

from app.plugin_platform.models import PluginInstallation
from app.plugin_platform.validator import inspect_plugin


def builtin_plugins_root() -> Path:
    return Path(__file__).resolve().parents[1] / "agent" / "builtin_plugins"


def _installation_id(name: str) -> str:
    return hashlib.sha256(f"evoflux:builtin-plugin:{name}".encode()).hexdigest()[:32]


@lru_cache(maxsize=1)
def list_builtin_installations() -> tuple[PluginInstallation, ...]:
    root = builtin_plugins_root()
    if not root.is_dir():
        return ()
    installations: list[PluginInstallation] = []
    for package_root in sorted(root.iterdir(), key=lambda item: item.name):
        if not package_root.is_dir() or package_root.name.startswith("_"):
            continue
        inspection = inspect_plugin(package_root)
        if not inspection.valid or inspection.manifest is None:
            continue
        manifest = inspection.manifest
        installations.append(
            PluginInstallation(
                id=_installation_id(manifest.name),
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                root=str(package_root.resolve()),
                source_type="builtin",
                source_ref="evoflux://builtin/" + package_root.name,
                content_sha256=inspection.content_sha256 or "0" * 64,
                enabled=True,
                installed_at="1970-01-01T00:00:00+00:00",
                updated_at="1970-01-01T00:00:00+00:00",
            )
        )
    return tuple(installations)


def is_builtin_installation(installation_id: str) -> bool:
    return any(item.id == installation_id for item in list_builtin_installations())


def path_is_builtin_plugin(path: str | Path) -> bool:
    candidate = Path(path).expanduser().resolve()
    root = builtin_plugins_root().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate != root


__all__ = [
    "builtin_plugins_root",
    "is_builtin_installation",
    "list_builtin_installations",
    "path_is_builtin_plugin",
]
