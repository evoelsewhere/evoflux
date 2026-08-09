"""Jira Data Center MCP entrypoint for the EvoFlux reference plugin."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from backend.evoflux_jira.client import JiraClient
from backend.evoflux_jira.config import ConnectionStore
from backend.evoflux_jira.errors import JiraPluginError

server = FastMCP("jira")
READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


async def _call(connection: str, operation: str, **kwargs: object) -> dict:
    try:
        config = ConnectionStore.from_environment().get(connection)
        async with JiraClient(config) as client:
            handler = getattr(client, operation)
            return await handler(**kwargs)
    except JiraPluginError as exc:
        raise ToolError(json.dumps({"error": exc.as_dict()})) from exc


@server.tool(annotations=READ_ONLY)
async def connection_test(connection: str = "default") -> dict:
    """Verify one saved Jira connection and return sanitized server/user identity."""
    return await _call(connection, "connection_test")


@server.tool(annotations=READ_ONLY)
async def projects_list(connection: str = "default", limit: int = 100) -> dict:
    """List Jira projects visible to the authenticated user."""
    return await _call(connection, "projects_list", limit=limit)


@server.tool(annotations=READ_ONLY)
async def project_permissions_get(
    project_key: str,
    connection: str = "default",
) -> dict:
    """Read the authenticated user's permissions for one Jira project."""
    return await _call(
        connection,
        "project_permissions_get",
        project_key=project_key,
    )


@server.tool(annotations=READ_ONLY)
async def issues_search(
    connection: str = "default",
    jql: str = "",
    project_key: str = "",
    text: str = "",
    status: str = "",
    assignee: str = "",
    priority: str = "",
    issue_type: str = "",
    start_at: int = 0,
    page_size: int = 50,
) -> dict:
    """Search Jira with raw JQL or mutually exclusive structured filters."""
    return await _call(
        connection,
        "issues_search",
        jql=jql,
        project_key=project_key,
        text=text,
        status=status,
        assignee=assignee,
        priority=priority,
        issue_type=issue_type,
        start_at=start_at,
        page_size=page_size,
    )


@server.tool(annotations=READ_ONLY)
async def issue_get(issue_key: str, connection: str = "default") -> dict:
    """Get bounded core fields for one Jira issue key."""
    return await _call(connection, "issue_get", issue_key=issue_key)


if __name__ == "__main__":
    server.run(transport="stdio")
