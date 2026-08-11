"""Load private native providers from trusted bundled Agent Plugins only."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import importlib
from pathlib import Path
from typing import Any

from app.plugin_platform.builtins import list_builtin_installations
from app.plugin_platform.extensions import BUILTIN_EXTENSION
from app.plugin_platform.registry import plugin_data_root
from app.plugin_platform.validator import inspect_plugin


def _load_entrypoint(value: str, *, package_root: Path) -> Callable[..., Any]:
    module_name, separator, attribute = value.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(f"invalid bundled provider entrypoint: {value!r}")
    expected_prefix = "app.agent.builtin_plugins." + package_root.name
    if module_name != expected_prefix and not module_name.startswith(
        expected_prefix + "."
    ):
        raise ValueError(
            f"bundled provider {value!r} must stay inside {expected_prefix}"
        )
    provider = getattr(importlib.import_module(module_name), attribute)
    if not callable(provider):
        raise TypeError(f"bundled provider is not callable: {value!r}")
    return provider


def iter_builtin_native_providers(
    name: str,
) -> Iterator[tuple[str, Callable[..., Any]]]:
    """Yield one named provider from each valid bundled package.

    The same extension on a managed or linked package is intentionally never
    interpreted as Python.  This preserves the portable plugin trust boundary.
    """

    for installation in list_builtin_installations():
        package_root = Path(installation.root)
        inspection = inspect_plugin(
            package_root,
            data_root=plugin_data_root(installation.id),
        )
        manifest = inspection.manifest
        if not inspection.valid or manifest is None:
            continue
        extension = manifest.extensions.get(BUILTIN_EXTENSION)
        value = extension.get(name) if isinstance(extension, dict) else None
        if not isinstance(value, str) or not value.strip():
            continue
        yield (
            installation.name,
            _load_entrypoint(value.strip(), package_root=package_root),
        )


__all__ = ["iter_builtin_native_providers"]
