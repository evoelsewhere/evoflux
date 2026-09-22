from __future__ import annotations

from app.plugin_platform.models import PluginRunContext
from app.plugin_platform.runtime import PluginMCPServerDescriptor


def test_mcp_descriptor_retains_installation_profiles_credentials_and_context() -> None:
    context = PluginRunContext(
        installation_id="a" * 32,
        content_sha256="b" * 64,
        workspace_id="workspace-a",
        tenant="tenant-a",
        environment="production",
        run_id="run-1",
        operation="jira.read",
        policy_version="1",
        policy_allowed=True,
    )
    descriptor = PluginMCPServerDescriptor(
        installation_id=context.installation_id,
        plugin_name="management-report-kit",
        server_name="jira",
        runtime_name="plugin_a_jira_12345678",
        transport="streamable-http",
        content_sha256=context.content_sha256,
        connection_profile_ids=("jira-read",),
        credential_refs=("jira_token",),
        run_context=context,
    )

    assert descriptor.run_context is context
    assert descriptor.connection_profile_ids == ("jira-read",)
    assert descriptor.credential_refs == ("jira_token",)
