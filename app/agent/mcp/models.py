"""Runtime state models shared by the MCP orchestration layers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp import ClientSession

    from app.agent.mcp.tools import MCPTool


@dataclass
class MCPServerStatus:
    """Live state for one MCP server, exposed by the HTTP API."""

    name: str
    transport: str
    enabled: bool
    state: str  # "stopped" | "starting" | "ready" | "error" | "auth_required"
    error: str | None = None
    tool_names: list[str] = field(default_factory=list)
    started_at: str | None = None


@dataclass
class MCPServerRunner:
    """Mutable lifecycle state for one configured MCP server.

    The runtime owns this object, while ``ServerSessionRunner`` owns the
    task's enter/exit discipline. Keeping the state separate makes global and
    plugin-scoped runtimes use the same session implementation safely.
    """

    shutdown: asyncio.Event
    ready: asyncio.Event
    task: asyncio.Task[None] | None = None
    session: "ClientSession | None" = None
    status: MCPServerStatus = field(
        default_factory=lambda: MCPServerStatus(
            name="", transport="", enabled=False, state="stopped"
        )
    )
    tools: list["MCPTool"] = field(default_factory=list)


# Private compatibility alias retained for existing tests and integrations.
_ServerRunner = MCPServerRunner
