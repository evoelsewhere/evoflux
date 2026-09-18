"""MCP transport boundaries.

This module owns process/HTTP connection setup only. It deliberately does not
know about tool projection, status transitions, OAuth policy, or config
watching. A transport yields the two MCP streams and keeps every SDK context
open in the same task as its consumer.
"""

from __future__ import annotations

import os
import shutil
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, AsyncIterator

from app.agent.mcp.config import (
    HttpServerConfig,
    StdioServerConfig,
    resolve_headers,
    resolve_secret_refs,
)

if TYPE_CHECKING:
    from mcp.shared.message import SessionMessage
    from mcp.shared._stream_protocols import ReadStream, WriteStream


@dataclass(frozen=True)
class StdioLaunch:
    """Resolved executable and environment for a stdio MCP server."""

    command: str
    env: dict[str, str]


async def resolve_stdio_launch(
    server_cfg: StdioServerConfig,
    *,
    user_path_loader: Callable[..., Awaitable[str]],
) -> StdioLaunch:
    """Resolve a configured executable without leaking the parent env."""
    configured_path = server_cfg.env.get("PATH")
    if configured_path is not None:
        effective_path = configured_path
    else:
        user_path = await user_path_loader()
        effective_path = user_path or os.environ.get("PATH", "")
    resolved_command = shutil.which(server_cfg.command, path=effective_path)

    if not resolved_command and configured_path is None:
        user_path = await user_path_loader(force_refresh=True)
        effective_path = user_path or os.environ.get("PATH", "")
        resolved_command = shutil.which(server_cfg.command, path=effective_path)

    env: dict[str, str] = {}
    if effective_path:
        env["PATH"] = effective_path
    env.update(
        {
            key: resolve_secret_refs(value) if server_cfg.resolve_env_refs else value
            for key, value in server_cfg.env.items()
        }
    )
    return StdioLaunch(command=resolved_command or server_cfg.command, env=env)


class MCPTransportFactory:
    """Open stdio or native MCP 2.x Streamable HTTP transports."""

    def __init__(
        self,
        *,
        stdio_launch_resolver: Callable[[StdioServerConfig], Awaitable[StdioLaunch]],
        header_resolver: Callable[[dict[str, str]], dict[str, str]] = resolve_headers,
    ) -> None:
        self._stdio_launch_resolver = stdio_launch_resolver
        self._header_resolver = header_resolver

    @asynccontextmanager
    async def open(
        self,
        server_cfg: StdioServerConfig | HttpServerConfig,
        *,
        auth: Any = None,
    ) -> AsyncIterator[
        tuple[ReadStream[SessionMessage | Exception], WriteStream[SessionMessage]]
    ]:
        """Yield MCP read/write streams with all transport resources scoped."""
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        async with AsyncExitStack() as stack:
            if isinstance(server_cfg, StdioServerConfig):
                launch = await self._stdio_launch_resolver(server_cfg)
                params = StdioServerParameters(
                    command=launch.command,
                    args=list(server_cfg.args),
                    env=launch.env,
                    cwd=server_cfg.cwd,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
                yield read, write
                return

            headers = (
                self._header_resolver(server_cfg.headers)
                if server_cfg.resolve_header_refs
                else dict(server_cfg.headers)
            )
            import httpx2

            http_client = httpx2.AsyncClient(
                headers=headers or None,
                auth=auth,
                timeout=httpx2.Timeout(30.0, read=300.0),
                # MCP 2.x follows only safe same-origin redirects in the
                # transport, regardless of this client's default policy.
                follow_redirects=False,
            )
            await stack.enter_async_context(http_client)

            # Import dynamically so callers/tests can replace the SDK
            # transport and so importing config remains cheap.
            from mcp.client.streamable_http import streamable_http_client

            read, write = await stack.enter_async_context(
                streamable_http_client(
                    server_cfg.url,
                    http_client=http_client,
                )
            )
            yield read, write


__all__ = ["MCPTransportFactory", "StdioLaunch", "resolve_stdio_launch"]
