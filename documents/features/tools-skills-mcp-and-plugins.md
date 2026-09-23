# Tools, Skills, MCP, and plugins

EvoFlux separates executable capabilities from instruction bundles. Tools are
runtime callables; Skills are lazily loaded instructions/resources that teach an
agent how to use available capabilities; MCP and Agent Plugins extend those
surfaces through explicit host-managed boundaries.

## Native tools

The built-in registry covers:

- filesystem read/search/edit/write/patch/remove;
- shell, Python, managed processes and previews;
- web search/fetch, persistent browser and WebBridge;
- LSP, diagnostics, and code-review actions;
- todos, notes, memory, goals, plans, scheduling and user questions;
- worktrees and team delegation/message/handoff/rework/state;
- deferred-tool loading;
- visualization/widget output and multimodal reads.

Each tool declares a JSON-like argument schema and an async handler. Deferred
tools expose only compact catalogue metadata until selected. Tool execution
passes through argument validation, observation policy, permission/sandbox
checks, output bounding and streaming telemetry.

## Agent Skills

EvoFlux follows Anthropic's Agent Skills architecture; the full contract is
[Agent Skills](../architecture/agent-skills.md).

- A Skill is a directory with `SKILL.md` (YAML `name` + `description`
  frontmatter and Markdown instructions) plus optional reference files,
  `scripts/` and `assets/`.
- Discovery covers project (`.evoflux/skills`, `.agents/skills`,
  `.claude/skills` up to the Git root), user (`{CONFIG_DIR}/skills`,
  `~/.agents/skills`, `~/.claude/skills`), enabled plugin and built-in roots,
  in that precedence order.
- Only each Skill's name, description and `SKILL.md` location are in the
  system prompt. The model reads `SKILL.md` with the `read` tool when a task
  matches, reads referenced files on demand, and runs bundled scripts with
  `shell`. There is no dedicated Skill tool and no router model call.
- Users type `$skill-name` to activate a Skill explicitly; an agent's
  `skills:` field preloads Skills into that agent's system prompt.
- Skills are available in Work and Coding mode alike. Settings lists every
  discovered Skill with its diagnostics, creates and edits user Skills, and
  turns any Skill on or off (`skill-settings.json`).

EvoFlux does not impose an aggregate byte ceiling on Skill bundle resources.
Managed create/update and validation still enforce the per-resource size and
entry-count budgets, reject symlinks and unsafe paths, require regular files,
and keep Settings previews bounded. This relaxation applies only to Skill
bundles; chat attachment and upload limits remain separate and unchanged.

## Global MCP client

Global servers are configured in `{CONFIG_DIR}/mcp.json`. EvoFlux supports
stdio and HTTP transports in the current Settings/API schema and retains
compatibility with supported MCP client transports in the runtime. Environment
references expand from the process or config `.env`; secret values are not
materialized into API responses.

`MCPRuntime` watches configuration, reconciles enabled servers, exposes status
and maps tools into the agent registry. MCP tools use the same permission
system as native tools. OAuth responses are stored in the cache root and are
scoped by server.

The Python runtime currently locks the MCP SDK to `2.2.0` and uses its native
`stdio_client` and `streamable_http_client` transports. Streamable HTTP headers
and OAuth are supplied through the SDK's native `httpx2` client; protocol
handshake versions remain negotiated per server by `ClientSession`.

The runtime is split into explicit boundaries:

```text
MCPRuntime
├── config watcher/reconciler + public registry
├── MCPServerRunner per server
│   └── ClientSession lifecycle and tool projection
└── MCPTransportFactory
    ├── stdio
    └── Streamable HTTP + httpx2 + OAuth
```

Global and plugin MCP runtimes share these components but use separate runtime
instances and configuration scopes. `MCPManager` remains as a compatibility
facade for existing integrations.

## Agent Plugins

Portable Agent Plugins use a root `plugin.json`, immediate-child `skills/` and
optional `mcp.json`. Plugin Center and CLI support inspect, scaffold, import,
install, development-link, update, pack, enable/disable and uninstall.

Plugin Center's Create flow defaults a blank starter Skill name to the plugin
name, so a new scaffold contributes a discoverable workflow instead of only a
manifest. EvoFlux does not generate an MCP server: `mcp.json` is added only by
an author who supplies a portable executable or remote endpoint. Static
validation does not install dependencies or prove process readiness.

New installations are disabled until the user reviews executable commands,
remote hosts, environment-field names and declared capabilities. Plugin
credentials and data live outside the package and survive in-place updates.
Plugin MCP servers run in an installation-scoped manager and are never copied
into global `mcp.json`.

Plugin packages cannot inject frontend code or bypass permissions. Portable
stdio and Streamable HTTP servers execute; legacy SSE declarations are
validated/reported but not started by the plugin runtime.

See [Agent Plugin architecture](../architecture/agent-plugins.md) and the
[operator guide](../guides/agent-plugins.md).

## Legacy Python hooks

Trusted local Python hook plugins under the configured plugin directories are a
separate, host-code extension mechanism. They are not portable Agent Plugins
and have a stronger trust requirement because they execute in the application
process.

## Source and tests

Primary code: `app/agent/tools/`, `app/agent/skills/`, `app/agent/mcp/`,
`app/plugin_platform/`, Skill/MCP/Plugin API routes, Settings editors and Plugin
Center.

Focused coverage exists under `tests/agent/tools`, `tests/agent/skills`,
`tests/agent/mcp`, `tests/plugin_platform`, API route tests and frontend Skill,
MCP and Plugin Center tests.
