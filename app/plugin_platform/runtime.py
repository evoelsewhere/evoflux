"""Runtime adapters for installed portable Agent Plugins."""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.agent.mcp.config import HttpServerConfig, MCPConfig, StdioServerConfig
from app.agent.mcp.manager import MCPManager
from app.agent.tools.registry import Tool
from app.plugin_platform.credentials import credential_environment
from app.plugin_platform.models import (
    PluginInspection,
    PluginInstallation,
    PluginMCPComponent,
)
from app.plugin_platform.registry import (
    list_installations,
    plugin_data_root,
    registry_signature,
)
from app.plugin_platform.validator import inspect_plugin


_SERVER_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")
_PLACEHOLDER_RE = re.compile(r"\$\{(PLUGIN_ROOT|PLUGIN_DATA)\}")
_MCP_EXTENSION = "evoflux.mcp"


def _runtime_server_name(installation_id: str, server_name: str) -> str:
    slug = _SERVER_SLUG_RE.sub("_", server_name).strip("_-") or "server"
    suffix = hashlib.sha256(server_name.encode("utf-8")).hexdigest()[:8]
    return f"plugin_{installation_id[:8]}_{slug[:40]}_{suffix}"


def _expand(value: str, *, root: Path, data_root: Path) -> str:
    """Expand the two portable placeholders exactly once."""

    replacements = {
        "PLUGIN_ROOT": str(root),
        "PLUGIN_DATA": str(data_root),
    }
    return _PLACEHOLDER_RE.sub(
        lambda match: replacements[match.group(1)],
        value,
    )


def _native_server_config(
    installation: PluginInstallation,
    inspection: PluginInspection,
    component: PluginMCPComponent,
) -> StdioServerConfig | HttpServerConfig | None:
    if not component.valid or component.transport == "sse":
        return None
    root = Path(installation.root).resolve()
    data = plugin_data_root(installation.id).resolve()
    config = component.config
    capabilities: list[str] = []
    if inspection.manifest is not None:
        extension = inspection.manifest.extensions.get(_MCP_EXTENSION, {})
        servers = extension.get("servers", {}) if isinstance(extension, dict) else {}
        server_extension = (
            servers.get(component.name, {}) if isinstance(servers, dict) else {}
        )
        raw_capabilities = (
            server_extension.get("capabilities", [])
            if isinstance(server_extension, dict)
            else []
        )
        if isinstance(raw_capabilities, list):
            capabilities = [
                value.strip().casefold()
                for value in raw_capabilities
                if isinstance(value, str) and value.strip()
            ]
    if component.transport == "stdio":
        data.mkdir(parents=True, exist_ok=True)
        command = (
            str(root / config["command"][2:])
            if config["command"].startswith("./")
            else config["command"]
        )
        env = {
            key: _expand(value, root=root, data_root=data)
            for key, value in config.get("env", {}).items()
        }
        env.update(credential_environment(installation.id, inspection))
        # Reserved values are applied after configured overrides as required
        # by Agent Plugins 1.0.0.
        env["PLUGIN_ROOT"] = str(root)
        env["PLUGIN_DATA"] = str(data)
        raw_cwd = config.get("cwd")
        if raw_cwd is None:
            cwd = str(root)
        elif raw_cwd.startswith("./"):
            cwd = str((root / raw_cwd[2:]).resolve())
        else:
            cwd = str(Path(_expand(raw_cwd, root=root, data_root=data)).resolve())
        return StdioServerConfig(
            command=command,
            args=[
                _expand(value, root=root, data_root=data)
                for value in config.get("args", [])
            ],
            env=env,
            cwd=cwd,
            resolve_env_refs=False,
            capabilities=capabilities,
        )
    if component.transport == "streamable-http":
        return HttpServerConfig(
            url=config["url"],
            headers=dict(config.get("headers", {})),
            resolve_header_refs=False,
            follow_redirects=False,
            capabilities=capabilities,
        )
    return None


@dataclass(frozen=True)
class PluginMCPServerDescriptor:
    installation_id: str
    plugin_name: str
    server_name: str
    runtime_name: str
    transport: str


def build_plugin_mcp_config() -> tuple[MCPConfig, list[PluginMCPServerDescriptor]]:
    servers: dict[str, StdioServerConfig | HttpServerConfig] = {}
    descriptors: list[PluginMCPServerDescriptor] = []
    for installation in list_installations(enabled_only=True):
        inspection = inspect_plugin(
            installation.root,
            data_root=plugin_data_root(installation.id),
        )
        if not inspection.valid:
            continue
        for component in inspection.mcp_servers:
            native = _native_server_config(installation, inspection, component)
            if native is None:
                continue
            runtime_name = _runtime_server_name(installation.id, component.name)
            servers[runtime_name] = native
            descriptors.append(
                PluginMCPServerDescriptor(
                    installation_id=installation.id,
                    plugin_name=installation.name,
                    server_name=component.name,
                    runtime_name=runtime_name,
                    transport=component.transport,
                )
            )
    return MCPConfig(servers=servers), descriptors


def _runtime_signature() -> tuple:
    values: list[object] = [*registry_signature()]
    for installation in list_installations(enabled_only=True):
        values.extend((installation.id, installation.root))
        for filename in ("plugin.json", "mcp.json"):
            try:
                metadata = (Path(installation.root) / filename).stat()
                values.extend((metadata.st_mtime_ns, metadata.st_size))
            except OSError:
                values.extend((0, 0))
        try:
            credential_metadata = (
                plugin_data_root(installation.id) / "credentials.json"
            ).stat()
            values.extend(
                (credential_metadata.st_mtime_ns, credential_metadata.st_size)
            )
        except OSError:
            values.extend((0, 0))
    return tuple(values)


class PluginMCPRuntime:
    """Own plugin-sourced MCP runners without mutating global MCP config."""

    def __init__(self, *, watch_interval: float = 1.0) -> None:
        self._manager = MCPManager(watch_config=False)
        self._watch_interval = watch_interval
        self._watch_task: asyncio.Task[None] | None = None
        self._signature: tuple | None = None
        self._descriptors: list[PluginMCPServerDescriptor] = []
        self._refresh_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            return
        await self.refresh()
        self._watch_task = asyncio.create_task(
            self._watch_loop(), name="plugin-mcp-registry-watcher"
        )

    async def stop(self) -> None:
        task = self._watch_task
        self._watch_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._manager.stop()

    async def refresh(self) -> None:
        async with self._refresh_lock:
            config, descriptors = build_plugin_mcp_config()
            await self._manager.apply_config(config)
            self._descriptors = descriptors
            self._signature = _runtime_signature()
        logger.info("plugin_mcp_refreshed servers={}", list(config.servers))

    async def _watch_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._watch_interval)
                try:
                    if _runtime_signature() != self._signature:
                        await self.refresh()
                except Exception as exc:  # noqa: BLE001
                    # Linked development packages can be observed between two
                    # editor writes. Preserve the last known-good runners and
                    # retry on the next interval instead of killing the watcher.
                    logger.error("plugin_mcp_watch_refresh_failed error={}", exc)
        except asyncio.CancelledError:
            raise

    def get_tools_dict(self) -> dict[str, Tool]:
        return self._manager.get_tools_dict()

    def server_names(self) -> list[str]:
        return self._manager.server_names()

    def get_tools_for_server(self, name: str) -> list[Tool] | None:
        return self._manager.get_tools_for_server(name)

    def get_tools_for_installation(self, installation_id: str) -> list[Tool]:
        """Return all ready tools contributed by one plugin installation."""

        tools: list[Tool] = []
        for descriptor in self._descriptors:
            if descriptor.installation_id != installation_id:
                continue
            tools.extend(self._manager.get_tools_for_server(descriptor.runtime_name) or [])
        return tools

    def list_status(self) -> list[dict[str, object]]:
        by_runtime = {item.runtime_name: item for item in self._descriptors}
        result: list[dict[str, object]] = []
        for status in self._manager.list_status():
            descriptor = by_runtime.get(status.name)
            result.append(
                {
                    "installation_id": descriptor.installation_id
                    if descriptor
                    else None,
                    "plugin_name": descriptor.plugin_name if descriptor else None,
                    "server_name": descriptor.server_name
                    if descriptor
                    else status.name,
                    "runtime_name": status.name,
                    "transport": status.transport,
                    "enabled": status.enabled,
                    "state": status.state,
                    "error": status.error,
                    "tool_names": list(status.tool_names),
                    "started_at": status.started_at,
                }
            )
        return result


plugin_mcp_runtime = PluginMCPRuntime()


def get_mcp_tools_for_server(name: str) -> list[Tool] | None:
    """Resolve an agent MCP grant across global and plugin runtimes."""

    from app.agent.mcp import mcp_manager

    tools = mcp_manager.get_tools_for_server(name)
    return plugin_mcp_runtime.get_tools_for_server(name) if tools is None else tools


def all_mcp_server_names() -> list[str]:
    from app.agent.mcp import mcp_manager

    return sorted({*mcp_manager.server_names(), *plugin_mcp_runtime.server_names()})


__all__ = [
    "PluginMCPRuntime",
    "PluginMCPServerDescriptor",
    "all_mcp_server_names",
    "build_plugin_mcp_config",
    "get_mcp_tools_for_server",
    "plugin_mcp_runtime",
]
