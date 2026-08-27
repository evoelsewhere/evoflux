# Use Agent Plugins with EvoFlux

EvoFlux is a desktop client for portable [Agent Plugins 1.0](https://agent-plugins.org/specification). It loads Agent Skills and runs MCP servers declared with stdio or Streamable HTTP. Legacy SSE declarations are validated and reported but are not started.

## Requirements

- Install a current EvoFlux desktop release from the [EvoFlux releases page](https://github.com/evoelsewhere/evoflux/releases/latest).
- Obtain an unpacked Agent Plugin directory or a `.zip`/`.evoplugin` archive from a source you trust.
- The package must contain a root `plugin.json`. Agent Skills belong directly below `skills/`; portable MCP servers belong in root `mcp.json`.

An `.evoplugin` file is only a deterministic ZIP distribution of the standard directory. It does not replace the Agent Plugins manifest.

## Install in Plugin Center

1. Open **Plugins** from either the Work or Coding sidebar.
2. Choose **Add plugin → Import package** for an archive, or **Link development folder** for an unpacked local directory.
3. Review the package inspection. Invalid package-level fields prevent installation; an invalid Skill or MCP entry is isolated to that component.
4. Review the enable disclosure. EvoFlux shows every declared executable and argument list, remote host, environment-field name, Agent Skill/MCP transport, and declared EvoFlux MCP capability. Secret, header, and environment values are not displayed.
5. Choose **Keep disabled** if anything is unexpected. Use **Actions → Edit plugin** to inspect files and **Actions → Credentials** to configure host-managed fields.
6. Toggle the plugin on and choose **Trust and enable** when the package and its access are acceptable.

New imports and links are disabled until this review completes. Enabling makes valid Skills discoverable and starts valid MCP server declarations; it does not bypass EvoFlux tool permissions.

## Install from the CLI

Validate before copying or linking anything:

```bash
evoflux plugin inspect ./my-plugin
evoflux plugin pack ./my-plugin
evoflux plugin install ./my-plugin.evoplugin
```

`install` and `link` default to disabled. Record the installation ID from the command output, inspect the static trust summary, and then enable deliberately:

```bash
evoflux plugin show <installation-id>
evoflux plugin enable <installation-id>
```

The `inspection.trust` object lists `executable_commands`, `remote_hosts`, `environment_fields`, and `capabilities`. Automation that has an independent trust gate may pass `--enabled` to `install` or `link`.

## Configure credentials

Agent Plugins 1.0 does not standardize credentials. A plugin may declare EvoFlux's canonical `org.evoelsewhere.evoflux.credentials` extension. Open **Actions → Credentials** and save the requested values. EvoFlux stores them outside the package, masks secret fields in responses, and injects declared variables only into that installation's stdio MCP process.

The older `evoflux.credentials` alias remains readable for existing packages. New packages should use the canonical reverse-domain namespace. Streamable HTTP headers remain literal package configuration and do not receive stored credential values.

## Confirm Skills and MCP

- Open **Settings → Skills** to confirm enabled plugin Skills are discoverable.
- Open **Settings → MCP servers** to confirm plugin servers carry a `plugin` badge and reach `ready` or expose a bounded startup error.
- Start a task that matches the Skill description or explicitly select the Skill. Loading that Skill makes ready MCP tools from the same installation available for that run, subject to normal permissions.
- Disable the plugin to remove its Skills and reconcile its MCP processes without restarting EvoFlux.

Plugin MCP configuration is adapted in memory. EvoFlux never copies it into the user's global MCP configuration.

## Develop and debug

Use **Add plugin → Create plugin** to scaffold a package, then edit `plugin.json`, `SKILL.md`, and optional resources in the built-in editor. Enter optional version, author, license, and Skill values; a blank Skill name defaults to the plugin name. EvoFlux does not generate MCP code or install its dependencies. Add `mcp.json` deliberately only after supplying and testing a portable executable or remote endpoint. A linked development directory refreshes in place.

```bash
evoflux plugin inspect ./my-plugin
evoflux plugin link ./my-plugin
evoflux plugin show <installation-id>
```

For the exact package contract, namespace aliases, storage model, runtime boundaries, and failure isolation, see [Portable Agent Plugins in EvoFlux](../architecture/agent-plugins.md).
