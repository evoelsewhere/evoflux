# Portable Agent Plugins in EvoFlux

EvoFlux implements the local portable core of [Agent Plugins 1.0](https://agent-plugins.org/specification). Managed Agent Plugins are separate from trusted legacy Python hooks in `app/agent/plugins`.

## Package contract

```text
example-plugin/
├── plugin.json
├── skills/
│   └── release-audit/
│       ├── SKILL.md
│       ├── scripts/
│       └── references/
└── mcp.json
```

`plugin.json` must target `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`. Skills are discovered only from immediate child directories of `skills/`. `mcp.json` is optional and may contain stdio, Streamable HTTP, or legacy SSE entries; EvoFlux executes stdio and Streamable HTTP and reports/skips SSE.

An `.evoplugin` file is a deterministic ZIP wrapper around this directory. It adds no alternate manifest or runtime semantics.

## User workflows

Open **Plugins** beneath Scheduler in either Work or Coding mode. Plugin Center supports:

- import a local `.evoplugin` or ZIP;
- link an unpacked development directory without copying it;
- validate a directory without installing it;
- scaffold a plugin with an optional starter Skill;
- enable, disable, pack, and uninstall an installation.

Equivalent CLI commands:

```bash
evoflux plugin create ./my-plugin --name my-plugin --skill release-audit
evoflux plugin inspect ./my-plugin
evoflux plugin link ./my-plugin
evoflux plugin pack ./my-plugin
evoflux plugin install ./my-plugin-unversioned.evoplugin
evoflux plugin list
evoflux plugin show <installation-id>
evoflux plugin disable <installation-id>
evoflux plugin enable <installation-id>
evoflux plugin uninstall <installation-id>
```

The lifecycle API is mounted at `/api/plugins`; its OpenAPI schema is the source of truth for request and response fields.

## Runtime and precedence

Plugin Skills join the normal metadata-only catalog and load progressively through the existing Skill tool. Precedence is:

1. project, user, and administrator roots;
2. enabled Agent Plugin installations;
3. EvoFlux built-ins.

Plugin MCP configuration is adapted in memory into a separate manager. It is never copied to or merged into the user's global `{CONFIG_DIR}/mcp.json`. Runtime server names are exposed by Plugin Center/API and can be granted through an agent's existing `mcp` configuration. Plugin MCP tools also remain subject to the normal tool and permission pipeline; installation alone does not grant every agent every tool.

For stdio servers, EvoFlux creates a persistent installation-scoped data directory and injects absolute `PLUGIN_ROOT` and `PLUGIN_DATA`. Only those exact placeholders are expanded, once, in `args`, `env` values, and `cwd`. Remote configured headers remain literal, and redirects are disabled to avoid forwarding them to a different origin.

## Storage

```text
{DATA_DIR}/agent-plugins/
├── registry.json
├── installed/<installation-id>/<version-or-digest>/
└── data/<installation-id>/

{CACHE_DIR}/agent-plugins/staging/
```

Registry writes are atomic. Managed archive extraction rejects traversal, duplicate/case-fold-colliding paths, symlinks, oversized packages, and suspicious compression ratios. Developer links may contain only links that resolve inside the plugin root. Uninstall preserves `PLUGIN_DATA` by default; CLI/API callers can explicitly remove it.

## Failure isolation

- Fatal manifest failures reject the package and prevent component discovery.
- Unknown manifest root fields and a non-object `extensions` value are reported, ignored, and do not reject an otherwise valid package.
- An invalid Skill skips only that Skill.
- Invalid top-level `mcp.json` disables only that plugin's MCP components.
- An invalid or failed MCP server skips only that server.
- Disabling a plugin removes its Skills and reconciles/stops its MCP runners without restarting EvoFlux.

## Deferred product layer

Agent Plugins 1.0 does not standardize registries, Git install, updates, signatures, permissions, secrets, connections, storage APIs, or custom UI. EvoFlux currently does not claim those capabilities for managed plugins. They belong in a versioned EvoFlux client extension with signed provenance and a sandboxed UI bridge; see the adoption analysis and plugin-platform plan.
