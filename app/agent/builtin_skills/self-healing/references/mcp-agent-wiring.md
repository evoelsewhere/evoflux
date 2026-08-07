# MCP attachment contract

MCP server configuration belongs to `$mcp-installer`. This reference covers
only attaching already-configured server tools to an agent.

## Choose one attachment mode

- Add the exact server name to `mcp:` to grant every current and future tool
  exposed by that server.
- Add exact `mcp_<server>_<tool>` entries to `tools:` when selective access is
  required.

Inspect MCP status first and take selective tool names from returned
`tool_names`. Never synthesize them. If the daemon is unavailable, bulk `mcp:`
attachment may still be recorded, but readiness remains unverified.

## Removal order

When decommissioning a server, remove its name from `mcp:` and every matching
selective tool from affected agent files before removing the server
configuration. Otherwise the next-turn rebuild can retain a stale agent config
because the tool no longer exists.

After editing, reread the agent file and verify that unrelated tools, MCP
servers, skills, and prompt text remain unchanged.
