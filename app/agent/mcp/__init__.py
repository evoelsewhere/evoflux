"""Model Context Protocol client integration with lazy runtime imports.

Configuration schemas stay cheap to import. The MCP SDK, OAuth stack, and tool
registry are loaded only when the manager is first used.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "MCPConfig": ("app.agent.mcp.config", "MCPConfig"),
    "MCPServerConfig": ("app.agent.mcp.config", "MCPServerConfig"),
    "StdioServerConfig": ("app.agent.mcp.config", "StdioServerConfig"),
    "HttpServerConfig": ("app.agent.mcp.config", "HttpServerConfig"),
    "load_config": ("app.agent.mcp.config", "load_config"),
    "save_config": ("app.agent.mcp.config", "save_config"),
    "MCPManager": ("app.agent.mcp.manager", "MCPManager"),
    "MCPServerStatus": ("app.agent.mcp.manager", "MCPServerStatus"),
    "mcp_manager": ("app.agent.mcp.lazy", "mcp_manager"),
}


def __getattr__(name: str) -> Any:  # noqa: ANN401 - public lazy re-export
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "StdioServerConfig",
    "HttpServerConfig",
    "MCPManager",
    "MCPServerStatus",
    "load_config",
    "save_config",
    "mcp_manager",
]
