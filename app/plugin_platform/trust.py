"""Static trust disclosures for an Agent Plugin package."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.plugin_platform.extensions import (
    CREDENTIALS_EXTENSION,
    LEGACY_CREDENTIALS_EXTENSIONS,
    LEGACY_MCP_EXTENSIONS,
    MCP_EXTENSION,
    resolve_extension,
)
from app.plugin_platform.models import (
    PluginManifest,
    PluginMCPComponent,
    PluginSkillComponent,
    PluginTrustCapability,
    PluginTrustCommand,
    PluginTrustRemoteHost,
    PluginTrustReview,
)


def _credential_environment_fields(manifest: PluginManifest) -> set[str]:
    extension = resolve_extension(
        manifest.extensions,
        CREDENTIALS_EXTENSION,
        LEGACY_CREDENTIALS_EXTENSIONS,
    )
    fields = extension.get("fields", []) if isinstance(extension, dict) else []
    if not isinstance(fields, list):
        return set()
    return {
        env
        for field in fields
        if isinstance(field, dict)
        and isinstance((env := field.get("env")), str)
        and env
    }


def _declared_capabilities(manifest: PluginManifest) -> list[PluginTrustCapability]:
    extension = resolve_extension(
        manifest.extensions,
        MCP_EXTENSION,
        LEGACY_MCP_EXTENSIONS,
    )
    servers = extension.get("servers", {}) if isinstance(extension, dict) else {}
    if not isinstance(servers, dict):
        return []
    capabilities: set[tuple[str, str]] = set()
    for server_name, declaration in servers.items():
        raw = (
            declaration.get("capabilities", []) if isinstance(declaration, dict) else []
        )
        if not isinstance(server_name, str) or not isinstance(raw, list):
            continue
        capabilities.update(
            (value.strip(), server_name)
            for value in raw
            if isinstance(value, str) and value.strip()
        )
    return [
        PluginTrustCapability(name=name, source=source)
        for name, source in sorted(capabilities, key=lambda item: (item[1], item[0]))
    ]


def build_trust_review(
    manifest: PluginManifest,
    skills: list[PluginSkillComponent],
    mcp_servers: list[PluginMCPComponent],
) -> PluginTrustReview:
    """Describe code and network access without executing plugin content."""

    commands: list[PluginTrustCommand] = []
    remote_hosts: list[PluginTrustRemoteHost] = []
    environment_fields = _credential_environment_fields(manifest)
    capabilities = [
        PluginTrustCapability(name="agent-skill", source=skill.name)
        for skill in skills
        if skill.valid
    ]
    for server in mcp_servers:
        if not server.valid:
            continue
        capabilities.append(
            PluginTrustCapability(name=f"mcp-{server.transport}", source=server.name)
        )
        config = server.config
        if server.transport == "stdio":
            raw_env = config.get("env", {})
            if isinstance(raw_env, dict):
                environment_fields.update(
                    key for key in raw_env if isinstance(key, str) and key
                )
            executable = config.get("command")
            args = config.get("args", [])
            if isinstance(executable, str) and isinstance(args, list):
                commands.append(
                    PluginTrustCommand(
                        server=server.name,
                        executable=executable,
                        args=[value for value in args if isinstance(value, str)],
                    )
                )
        elif server.transport in {"streamable-http", "sse"}:
            url = config.get("url")
            if isinstance(url, str):
                parsed = urlsplit(url)
                if parsed.netloc:
                    remote_hosts.append(
                        PluginTrustRemoteHost(
                            server=server.name,
                            transport=server.transport,
                            host=parsed.netloc,
                            url=url,
                        )
                    )
    capabilities.extend(_declared_capabilities(manifest))
    return PluginTrustReview(
        executable_commands=commands,
        remote_hosts=remote_hosts,
        environment_fields=sorted(environment_fields),
        capabilities=capabilities,
    )


__all__ = ["build_trust_review"]
