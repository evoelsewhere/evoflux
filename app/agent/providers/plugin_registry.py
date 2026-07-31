from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from dotenv import dotenv_values
from loguru import logger

from app.agent.providers.plugin_api import ProviderPlugin


def _settings():
    from app.core.config import settings

    return settings


class ProviderCredentialStore:
    def __init__(
        self, provider_id: str, overrides: dict[str, str] | None = None
    ) -> None:
        self.provider_id = provider_id
        self.overrides = overrides or {}
        self._env_file = Path(_settings().EVOFLUX_CONFIG_DIR) / ".env"
        self._env_values: dict[str, str] | None = None

    def _saved_env(self) -> dict[str, str]:
        if self._env_values is None:
            raw = dotenv_values(self._env_file) if self._env_file.is_file() else {}
            self._env_values = {k: v for k, v in raw.items() if k and v}
        return self._env_values

    def get(self, name: str, default: str = "") -> str:
        if name in self.overrides:
            return self.overrides[name]
        return os.getenv(name) or self._saved_env().get(name, default) or default

    def delete(self, name: str) -> None:
        """Remove a saved plugin credential from every supported source."""
        from app.cli.seed import write_env_credentials

        self.overrides.pop(name, None)
        if self._env_file.is_file():
            write_env_credentials(self._env_file, {name: ""})
        os.environ.pop(name, None)
        self._env_values = None

    def token_path(self, filename: str) -> str:
        safe = filename.replace("/", "_")
        root = (
            Path(_settings().EVOFLUX_CACHE_DIR) / "provider-plugins" / self.provider_id
        )
        root.mkdir(parents=True, exist_ok=True)
        return str(root / safe)


_PLUGIN_CACHE: dict[str, ProviderPlugin] | None = None


def _load_provider_plugin(path: Path) -> ProviderPlugin | None:
    mod_name = f"_EVOFLUX_provider_plugin_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    provider = getattr(module, "provider", None)
    if provider is None:
        return None
    if not isinstance(provider, ProviderPlugin):
        raise TypeError(f"provider in {path} must be ProviderPlugin")
    if not provider.id or ":" in provider.id:
        raise ValueError(f"invalid provider plugin id in {path}: {provider.id!r}")
    if provider.kind == "oauth" and provider.login is None:
        raise ValueError(f"oauth provider plugin {provider.id!r} must define login")
    return provider


def provider_plugins() -> dict[str, ProviderPlugin]:
    global _PLUGIN_CACHE
    if _PLUGIN_CACHE is not None:
        return dict(_PLUGIN_CACHE)

    loaded: dict[str, ProviderPlugin] = {}
    for directory in _settings().plugin_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                plugin = _load_provider_plugin(path)
            except Exception as exc:  # noqa: BLE001 - isolate broken plugins
                logger.warning(
                    "provider_plugin_load_failed file={} error={}", path, exc
                )
                continue
            if plugin is None:
                continue
            if plugin.id in loaded:
                logger.warning(
                    "provider_plugin_duplicate id={} file={}", plugin.id, path
                )
                continue
            loaded[plugin.id] = plugin
    _PLUGIN_CACHE = loaded
    return dict(loaded)


def find_provider_plugin(provider_id: str) -> ProviderPlugin | None:
    return provider_plugins().get(provider_id)


def clear_provider_plugin_cache() -> None:
    global _PLUGIN_CACHE
    _PLUGIN_CACHE = None
