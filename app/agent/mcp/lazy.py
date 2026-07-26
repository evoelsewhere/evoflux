"""Lazy access to the process-wide MCP manager.

Importing the MCP SDK pulls in its HTTP/OAuth stack and the complete agent tool
registry. Most EvoFlux starts have no configured MCP servers, so importing that
surface while FastAPI registers routes adds startup latency for no benefit.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


class LazyMCPManager:
    """Resolve the real singleton only when an MCP operation is requested."""

    def __init__(self) -> None:
        self._manager: Any | None = None

    def _resolve(self) -> Any:
        if self._manager is None:
            module = import_module("app.agent.mcp.manager")
            self._manager = module.mcp_manager
        return self._manager

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)


mcp_manager = LazyMCPManager()
