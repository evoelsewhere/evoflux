"""Portable Agent Plugins platform for EvoFlux.

This package is intentionally separate from :mod:`app.agent.plugins`, which
contains trusted, in-process legacy Python hooks.
"""

from app.plugin_platform.installer import (
    PluginInstallError,
    create_plugin,
    install_plugin,
    link_plugin,
    pack_plugin,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.registry import (
    get_installation,
    list_installations,
    list_effective_installations,
    set_enabled,
)
from app.plugin_platform.validator import inspect_plugin

__all__ = [
    "PluginInstallError",
    "create_plugin",
    "get_installation",
    "inspect_plugin",
    "install_plugin",
    "link_plugin",
    "list_installations",
    "list_effective_installations",
    "pack_plugin",
    "set_enabled",
    "uninstall_plugin",
    "update_plugin",
]
