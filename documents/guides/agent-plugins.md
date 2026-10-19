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
- Start a task that matches the Skill description, or type `$skill-name` to use it explicitly. Once the agent reads that Skill's `SKILL.md`, ready MCP tools from the same installation become available for that run, subject to normal permissions.
- Disable the plugin to remove its Skills and reconcile its MCP processes without restarting EvoFlux.

Plugin MCP configuration is adapted in memory. EvoFlux never copies it into the user's global MCP configuration.

## Plugin lifecycle hooks

EvoFlux accepts the `com.evoflux.hooks` extension for static inspection and
Settings precedence. A version 1 declaration has this shape:

```json
{
  "extensions": {
    "com.evoflux.hooks": {
      "version": 1,
      "hooks": [
        {
          "hook_id": "session-bootstrap",
          "event": "session.start",
          "runtime": "python",
          "command": ["./hooks/bootstrap.py"],
          "files": ["./hooks/helper.py"],
          "timeout_seconds": 10,
          "input_fields": ["session_id", "source"],
          "output_fields": ["context"],
          "failure_policy": "fail_open"
        }
      ]
    }
  }
}
```

The supported event names are `session.start`, `session.end`, `prompt.submit`,
`agent.start`, `agent.stop`, `model.before`, `model.after`, `tool.before`,
`tool.after`, `completion.before`, `compact.before`, `compact.after`,
`subagent.start` and `subagent.stop`. Each event has its own input/output
allowlist; `input_fields` and `output_fields` must be explicit. Commands must
begin with a package-relative `./` path. Settings-owned commands resolve under
the EvoFlux config directory.

Plugin enablement and digest-bound hook trust are separate decisions. The
dispatcher is connected to the session, prompt, agent, model, tool, completion,
compaction and member-agent boundaries. The runtime is explicit (`native` or
`python`); the entrypoint and each declared `files` path are hash-bound. Only
those files and the isolated Python standard library are staged for a run. The
Settings config directory is never exposed wholesale. Windows AppContainer +
Windows is the first executable-hook target. Hooks run in an AppContainer with
no capabilities and a constrained Job Object; adversarial smoke coverage checks
filesystem and network denial, staged-file reads, child-process restrictions,
resource limits, cancellation, and output bounds. Linux and macOS remain
fail-closed until equivalent platform tests pass. Saving a definition or
approving a digest cannot bypass that gate. Hook-provided context is passed as
untrusted user context, never system policy.

The Claude marketplace adapter supports one narrow exception: Superpowers'
exact `SessionStart` bootstrap is normalized to a `static_context` action that
reads only `skills/using-superpowers/SKILL.md`. EvoFlux does not copy or execute
Superpowers' Bash/polyglot launcher. Review and trust this static file action
separately; its bounded contents are added once at session start as untrusted
context. Other Claude hook declarations remain unsupported and are reported in
the marketplace preview. The Skill itself stays available when the hook shape
is unsupported, oversized, disabled, or untrusted.

Before trusting a command hook, review its matcher, exact argv and package
path, input/output fields, timeout, failure policy, fixed environment allowlist,
isolation profile, and digest. Static context review instead shows the single
read-only source path, context wrapper, and its separate trust profile. A
`fail_open` declaration does not allow a command hook to bypass the mandatory
isolation gate; if containment is unavailable, dispatch denies the affected
operation.
Agent and subagent stop events include `outcome: completed|cancelled|failed`
and are attempted in a terminal finalizer, including when the run raises.

### Use Agent hooks without editing JSON

Open **Settings → Agent hooks** to see what each installed plugin
workflow does, when it runs, whether it needs review, and whether it is paused
or blocked on this device. **Review workflow** approves one package hook for
its current digest; it does not enable the plugin. You can pause a single
plugin workflow without changing other workflows.

Under **My workflows**, choose **Create workflow**, give your guidance a name,
and write the Markdown you want added when a new session starts. This guided
workflow reads no session data and cannot run commands. Saving it does not
approve it; choose **Review and allow** separately. Editing its content changes
the digest, so the updated version needs review again. Remove deletes that
workflow and its owned guidance file.

Under **Choose when plugin workflows run**, choose whether plugin workflows run
alongside your own, or whether your workflows replace them at selected moments.
Common moments appear first; less common agent and context events are under
**Other moments**. Replacement shows an affected-workflow preview and requires
confirmation. A personal workflow must be approved and active to replace a
plugin workflow; otherwise EvoFlux warns that nothing will run at that moment.
Core permissions and safety checks continue to apply. Technical users can still
open **Advanced: edit hook settings JSON**.

## Develop and debug

Use **Add plugin → Create plugin** to scaffold a package, then edit `plugin.json`, `SKILL.md`, and optional resources in the built-in editor. Enter optional version, author, license, and Skill values; a blank Skill name defaults to the plugin name. EvoFlux does not generate MCP code or install its dependencies. Add `mcp.json` deliberately only after supplying and testing a portable executable or remote endpoint. A linked development directory refreshes in place.

```bash
evoflux plugin inspect ./my-plugin
evoflux plugin link ./my-plugin
evoflux plugin show <installation-id>
```

For the exact package contract, namespace aliases, storage model, runtime boundaries, and failure isolation, see [Portable Agent Plugins in EvoFlux](../architecture/agent-plugins.md).
