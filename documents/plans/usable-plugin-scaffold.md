# Code-aligned Agent Plugin scaffold

Status: implemented

## Problem and outcome

The built-in `plugin-development` Skill presents one example tree containing
root `server.py` and package-local `tests/` as the EvoFlux plugin layout. The
code has two separate contracts instead:

1. managed portable packages use root `plugin.json`, direct-child
   `skills/<name>/SKILL.md`, and optional root `mcp.json`;
2. trusted in-process hooks are flat `.py` files discovered from
   `settings.plugin_dirs()` and loaded by `app/agent/plugins/loader.py`.

The optional managed-package MCP scaffold compounds the ambiguity by generating
`python server.py` that passes static validation but depends on an interpreter
and `mcp` package that EvoFlux does not provision.

The outcome is a code-aligned authoring workflow: Plugin Center creates a
usable Skills package by default, the Skill no longer advertises implementation
files as fixed layout, and automatic MCP generation is rejected until a
separate portable runtime contract is accepted.

## Goals

- Derive authoring layout from the actual validator, skill discovery, MCP
  adapter, and trusted-hook loader.
- Make Plugin Center create a direct-child Skill by default.
- Expose existing optional manifest metadata and Skill fields in the Create UI.
- Prevent the API/service from producing an MCP package that cannot start on a
  clean desktop.
- Prove create, inspect, pack, install, enable, and Skill discovery.
- Test an ordinary end-user prompt in the running app without prescribing file
  names or layout.

## Non-goals

- Implementing the deferred bundled-Python client extension.
- Installing plugin dependencies or creating virtual environments.
- Changing the existing portable `plugin.json`/`mcp.json` schemas.
- Converting trusted in-process hook plugins into managed packages.
- Requiring every valid package to contain a Skill or MCP server.

## User flows and states

1. In Plugin Center, the user enters a parent folder and plugin name. Optional
   version, author, license, description, and Skill name are available.
2. A blank Skill name resolves to the plugin name before the request.
3. EvoFlux creates `plugin.json` and `skills/<name>/SKILL.md`, validates them,
   and opens the editor.
4. The author may add `mcp.json` later only after supplying a package-owned
   executable, a verified external command, or a supported remote endpoint.
5. A request to auto-generate MCP files is rejected before creating a target
   directory, with an actionable portability explanation.
6. A trusted lifecycle hook request is routed to the separate flat `.py`
   contract and is never represented with the managed-package tree.

## Requirements and acceptance criteria

- **AC-1:** Plugin Center Create with required fields sends `skill_name` equal
  to the trimmed plugin name and the package contains
  `skills/<name>/SKILL.md`.
- **AC-2:** Optional version, author, license, description, and explicit Skill
  name are forwarded through the existing create API.
- **AC-3:** The built-in Skill documents only fixed portable paths
  (`plugin.json`, direct-child Skills, optional `mcp.json`) and states that MCP
  implementation files are chosen by the declared command; it does not require
  root `server.py` or package-local `tests/`.
- **AC-4:** The built-in Skill distinguishes managed packages from trusted flat
  `.py` hook/provider plugins using the actual loader contracts.
- **AC-5:** Passing `mcp_name` to the scaffold service fails before filesystem
  creation; the public create API no longer advertises that field.
- **AC-6:** A default Skills scaffold survives inspect, deterministic pack,
  managed install, enable, and plugin Skill discovery.
- **AC-7:** Feature/architecture/operator docs and all Help locales match the
  implemented authoring and dependency boundary.
- **AC-8:** In a running EvoFlux app, an end-user-style prompt creates a package
  that satisfies AC-1 and AC-6 without being told the layout.

## API, event, tool, and UI contracts

`POST /api/plugins/create` retains destination, name, description, version,
author, license, and `skill_name`. The unusable `mcp_name` field is removed.
Direct service callers receive `PluginInstallError` if they pass it during the
compatibility window.

No SSE/event shape changes. Plugin Center defaults an empty Skill name to the
plugin name and opens the existing workspace editor after successful creation.

## Data model, migration, and retention

Not applicable. No database, registry, installation, or retention schema
changes.

## Permissions, security, privacy, and trust

Managed packages remain disabled until trust review when imported. Skill-only
scaffolding executes no plugin code. Trusted `.py` hooks remain in-process,
digest-trusted, and outside Plugin Center; the authoring Skill must not blur
that stronger trust boundary.

## Concurrency, failure, recovery, and idempotency

Create continues to reject existing destinations. Unsupported automatic MCP
creation fails before the directory is made, so retrying with a Skills-only
request is safe. Existing component failure isolation is unchanged.

## Observability and diagnostics

Static inspection continues to report package and component diagnostics.
Unsupported MCP scaffolding returns an explicit error stating that EvoFlux does
not guarantee an executable or install dependencies. Runtime status remains
the proof for manually authored MCP servers.

## Compatibility, rollout, and rollback

Existing installed/linked packages and manually authored `mcp.json` files are
unchanged. Only new scaffold requests are affected. The removed API field had
generated a package that was structurally valid but not reliably runnable;
direct service rejection keeps the failure explicit for internal callers.

## Verification matrix

| AC | Implementation owner | Evidence |
|---|---|---|
| AC-1, AC-2 | Plugin Center + create API/service | Component and API lifecycle tests |
| AC-3, AC-4 | `plugin-development` Skill/references | Contract assertions and code inspection |
| AC-5 | create schema/service | Negative service/API test; target remains absent |
| AC-6 | installer/registry/skill discovery | Pack/install/discovery lifecycle test |
| AC-7 | feature, architecture, guide, Help | focused doc inspection + frontend gates |
| AC-8 | running EvoFlux | browser prompt plus package inspection |

## Ownership and source map

- Portable validator/scaffold: `app/plugin_platform/`
- Plugin Skill discovery: `app/plugin_platform/skills.py`
- Trusted hook contract: `app/agent/plugins/loader.py`
- Create API: `app/api/routes/plugins.py`, `app/api/schemas/plugins.py`
- Plugin Center: `web/src/components/PluginCenterPanel.tsx`
- Authoring workflow: `app/agent/builtin_skills/plugin-development/`
- Current docs: `documents/features/tools-skills-mcp-and-plugins.md`,
  `documents/architecture/agent-plugins.md`, `documents/guides/agent-plugins.md`
- Tests: `tests/plugin_platform/`, `tests/api/test_plugin_routes.py`, and
  `web/src/__tests__/components/PluginCenterPanel.test.tsx`
