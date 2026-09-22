"""Per-server MCP session runner.

The runner owns the SDK context-manager rule: transport and ``ClientSession``
are entered, initialized, and exited by the same long-lived asyncio task.
Runtime orchestration handles reconciliation and error policy around it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.agent.mcp.config import HttpServerConfig, StdioServerConfig
from app.agent.mcp.models import MCPServerRunner
from app.agent.mcp.tools import MCPTool, validate_mcp_tool
from app.agent.mcp.transport import MCPTransportFactory


async def run_server_session(
    name: str,
    server_cfg: StdioServerConfig | HttpServerConfig,
    runner: MCPServerRunner,
    *,
    transport_factory: MCPTransportFactory,
    auth: Any = None,
) -> None:
    """Run one initialized MCP session until its shutdown event is set."""
    from mcp import ClientSession

    async with transport_factory.open(server_cfg, auth=auth) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools_resp = await session.list_tools()

            runner.session = session
            runner.tools = []
            for tool in tools_resp.tools:
                valid, reason = validate_mcp_tool(tool)
                if not valid:
                    logger.warning(
                        "mcp_tool_rejected server={} reason={}", name, reason
                    )
                    continue
                runner.tools.append(
                    MCPTool(
                        server_name=name,
                        mcp_tool=tool,
                        session_provider=lambda r=runner: r.session,
                        server_capabilities=server_cfg.capabilities,
                    )
                )
            runner.status.state = "ready"
            runner.status.tool_names = [tool.name for tool in runner.tools]
            runner.status.started_at = datetime.now(UTC).isoformat()
            runner.status.error = None
            runner.ready.set()
            logger.info(
                "mcp_server_ready name={} transport={} tools={}",
                name,
                server_cfg.transport,
                len(runner.tools),
            )

            await runner.shutdown.wait()
            runner.session = None
            logger.info("mcp_server_stopping name={}", name)


__all__ = ["run_server_session"]
