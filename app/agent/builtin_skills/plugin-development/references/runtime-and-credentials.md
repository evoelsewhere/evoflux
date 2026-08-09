# MCP runtime, credentials, and data

Use this reference whenever a plugin declares MCP servers, credential fields, installation data, runtime capabilities, or tool calls.

## `mcp.json`

Use the canonical schema and only `$schema` plus `mcpServers` at the top level:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "release-api": {
      "type": "stdio",
      "command": "python",
      "args": ["${PLUGIN_ROOT}/server.py"],
      "env": {
        "RELEASE_CACHE": "${PLUGIN_DATA}/cache.json"
      },
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

Supported declarations:

- `stdio`: local executable with `command`, argument array, optional environment, and optional working directory;
- `streamable-http`: remote MCP URL with literal optional headers;
- legacy `sse`: schema-valid for portability but skipped by the EvoFlux runtime.

For stdio, `command` is either a bare executable resolved by the process environment or a `./relative` executable inside the plugin. Never use a shell command string. Keep protocol output clean; send diagnostics to stderr.

For remote MCP:

- require HTTPS for non-loopback hosts;
- reject URL userinfo and fragments;
- do not depend on redirects because the runtime disables them;
- treat declared headers as literal package data, never as a secret-reference mechanism.

## Placeholder rules

EvoFlux performs a single substitution pass for:

- `${PLUGIN_ROOT}` — immutable installed or linked package root;
- `${PLUGIN_DATA}` — mutable installation-scoped data root.

Substitution is supported in stdio `args`, `env` values, and `cwd`. Do not use placeholders in `command`, remote URLs, or remote headers. A resolved relative working directory must remain inside the plugin root; a `${PLUGIN_DATA}` working directory must remain inside the data root.

Do not rely on nested or recursive expansion. Pass distinct values as separate arguments instead of constructing a shell expression.

## Credentials extension

Declare configurable values in `plugin.json`:

```json
{
  "extensions": {
    "evoflux.credentials": {
      "fields": [
        {
          "key": "base_url",
          "label": "API base URL",
          "type": "url",
          "env": "RELEASE_API_URL",
          "required": true,
          "placeholder": "https://api.example.com"
        },
        {
          "key": "api_token",
          "label": "API token",
          "type": "secret",
          "env": "RELEASE_API_TOKEN",
          "required": true,
          "description": "Token used only by this plugin process."
        },
        {
          "key": "verify_ssl",
          "label": "Verify TLS certificates",
          "type": "boolean",
          "env": "RELEASE_VERIFY_SSL",
          "required": false,
          "default": true
        }
      ]
    }
  }
}
```

Allowed field types are `text`, `secret`, `url`, and `boolean`. Field keys and `env` names must be unique. Do not use the reserved environment variables `PATH`, `PLUGIN_ROOT`, or `PLUGIN_DATA`. Credential values are strings or booleans and the serialized file is limited to 256 KiB.

EvoFlux stores values at `data/<installation-id>/credentials.json` with mode `0600`, masks secret fields on read, and injects only declared fields into plugin stdio processes. Credential values overlay `mcp.json` environment entries; EvoFlux then forces the correct `PLUGIN_ROOT` and `PLUGIN_DATA` values.

Saving or clearing credentials refreshes the MCP runtime. A required-field warning can coexist with a valid package; readiness depends on the server's actual startup and behavior. Never log credential values, embed them in tool errors, return them through MCP, commit them to the package, or request them in chat.

## Capabilities and permissions

Declare current server capabilities separately from credentials:

```json
{
  "extensions": {
    "evoflux.mcp": {
      "servers": {
        "release-api": {
          "capabilities": ["webbridge-safe"]
        }
      }
    }
  }
}
```

`webbridge-safe` explicitly keeps a non-browser plugin server available in a WebBridge-tagged conversation. Servers without it stay hidden there so an undeclared MCP browser cannot bypass the selected browser surface. Declare it only after verifying the server is safe and useful in that context.

Capability declarations do not bypass permissions. Installation does not globally grant all plugin tools. Loading a plugin Skill makes ready MCP tools from the same installation available for that run, while the normal permission pipeline still governs tool calls.

## Runtime identity and tool lookup

EvoFlux adapts plugin MCP declarations into a separate in-memory runtime manager; it never writes them into global MCP configuration. Runtime names include installation and server-derived hashes, so they are intentionally unstable across installations.

Skill instructions must identify tools by stable suffix and semantics, for example: “select the available namespaced tool ending in `release_api_status_get`.” Never hardcode the generated prefix.

Runtime behavior:

- enabled valid servers are reconciled at startup and after lifecycle mutations;
- linked source trees are watched approximately once per second;
- transient invalid linked edits retain the last-known-good runner;
- a disabled plugin has no discoverable Skills and no running servers;
- status may be `ready`, `starting`, `error`, `disabled`, or skipped depending on the declaration and state.

When debugging a linked package, compare the current validation result with the runtime status; they may briefly describe different generations by design.

## Server implementation discipline

Keep the MCP process portable and bounded:

- validate inputs before network or file access;
- set explicit network timeouts;
- bound result counts and response sizes;
- model pagination rather than silently downloading everything;
- translate upstream failures into concise sanitized errors;
- distinguish authentication, authorization, not-found, rate-limit, and transport failures without echoing secrets;
- use tool annotations for read-only, destructive, idempotent, and open-world behavior when supported;
- create data directories safely and use restrictive file permissions for sensitive state.

EvoFlux currently does not define a manifest hook that creates a virtual environment or installs package dependencies. Before choosing an entrypoint, verify that its interpreter and imported libraries exist in every target runtime, or bundle a self-contained executable/runtime inside the portable package. Do not assume a developer's active virtual environment will exist for a managed installation. Record any unavoidable runtime prerequisite in the plugin README and test it from a clean managed install.
