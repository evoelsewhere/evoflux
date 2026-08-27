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
- code context, LSP and code-review actions;
- todos, notes, memory, goals, plans, scheduling and user questions;
- worktrees and team delegation/message/handoff/rework/state;
- Skill and deferred-tool loading;
- visualization/widget output and multimodal reads.

Each tool declares a JSON-like argument schema and an async handler. Deferred
tools expose only compact catalogue metadata until selected. Tool execution
passes through argument validation, observation policy, permission/sandbox
checks, output bounding and streaming telemetry.

## Agent Skills

Skills are directories containing `SKILL.md` plus optional scripts, references
and assets. Discovery includes built-in, user, project, plugin and managed
sources. Stable source identity and precedence prevent a lower-priority bundle
from silently replacing an activated higher-priority Skill.

Only a bounded metadata catalogue is injected eagerly. A Skill body and its
resources load after exact explicit or router-based activation. Runtime
settings are stored as an overlay keyed to the discovered variant; EvoFlux does
not rewrite built-in, managed, symlinked, project or plugin files.

Mode scope (`work`, `coding`, or both), explicit-only behavior, required tools,
runtime dependencies and diagnostics are resolved before activation. Settings
can create/edit user Skills and enable, disable or configure variants.

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

The MCP manager watches configuration, starts/restarts enabled servers, exposes
status and maps tools into the agent registry. MCP tools use the same permission
system as native tools. OAuth responses are stored in the cache root and are
scoped by server.

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
