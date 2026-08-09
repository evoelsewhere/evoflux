# End-to-end test and debug playbook

Use this reference to design proportionate tests, prove the packaged artifact, and isolate failures by platform layer.

## Contents

- [Minimum evidence matrix](#minimum-evidence-matrix)
- [Canonical local E2E fixture](#canonical-local-e2e-fixture)
- [Suggested repository commands](#suggested-repository-commands)
- [Debug layers](#debug-layers)
- [Regression-test rule](#regression-test-rule)

## Minimum evidence matrix

For a new hybrid Skill + MCP plugin, cover these layers:

| Layer | Minimum proof |
|---|---|
| Package | Source inspection succeeds; expected inventory only; two pack outputs are byte-identical |
| Manifest | Canonical schema, name/version, and extensions validate |
| Skill | Immediate-child discovery, matching frontmatter, correct trigger and stable tool lookup |
| MCP schema | Valid server is accepted; invalid sibling isolation is covered where relevant |
| Server unit | Inputs, success response, bounds, timeout/error mapping, and secret sanitization |
| Credentials | Required/missing state, save/read masking, `0600`, injection, clear/refresh |
| Runtime | Managed install reaches ready; representative tool call traverses actual MCP transport; linked code edits reload |
| Lifecycle | Disable/enable; versioned and same-version update preserve identity/data/state; rejected update rolls back; uninstall policy is explicit |
| Security | No traversal/symlink escape; no secret in status, logs, errors, or tool output |

For Skills-only or MCP-only plugins, omit irrelevant rows but explain the omission. Add contract-specific cases for writes, destructive tools, connection files, or multiple servers.

## Canonical local E2E fixture

Prefer a local fixture over a live third-party service:

1. Start a loopback HTTP fixture that implements the smallest upstream API surface.
2. Create or copy the plugin into a temporary source directory.
3. Run platform inspection and assert expected Skills, servers, warnings, and credential schema.
4. Pack the source twice to distinct outputs, compare their bytes, and install
   one artifact into isolated EvoFlux data, config, and cache roots.
5. Save credentials through the same platform service or API used by Plugin Center.
6. Assert the credential file is `0600` and secret reads are masked.
7. Start or refresh the plugin MCP manager and wait with a bounded timeout for `ready`.
8. Resolve the generated MCP tool by its stable suffix.
9. Call a representative tool and assert the fixture observed the expected bounded request.
10. Inspect status and serialized outputs for absence of the raw secret.
11. For linked sources, change implementation behavior without editing
    `mcp.json`; wait with a bound and prove a new tool call observes the change.
12. Disable and verify runtime/Skill removal; enable and verify restoration if in scope.
13. Exercise versioned and same-version update plus one rejected update; prove
    identity/data/state preservation and rollback.
14. Uninstall in cleanup and explicitly remove isolated test data.

Implement this pattern with a fake upstream endpoint and a real representative tool call through `PluginMCPRuntime`. Do not depend on a live third-party service. There is no general `/api/plugins` endpoint for arbitrary MCP tool invocation; automated E2E tests invoke the plugin runtime in process, while product-level verification can load the plugin Skill in an agent run.

## Suggested repository commands

Inside the EvoFlux repository, start focused:

```bash
uv run pytest --no-cov -q tests/plugin_platform
uv run pytest --no-cov -q tests/api/test_plugin_routes.py
```

Add the relevant file-level tests for changed platform modules and UI tests for Plugin Center changes. Run repository lint/type checks on edited Python paths. Adapt commands to the active repository instructions rather than assuming every plugin uses Python.

For a standalone package, always include platform CLI evidence where available:

```bash
evoflux plugin inspect ./my-plugin
evoflux plugin pack ./my-plugin --output ./dist/my-plugin.evoplugin
```

Do not pass an archive to `plugin inspect`; install it in an isolated profile
and inspect the resulting installation instead.

Use an isolated EvoFlux data directory for destructive lifecycle tests. Do not uninstall or overwrite a user's real installation as a test fixture.

## Debug layers

### Package cannot be inspected or installed

Check, in order:

1. `plugin.json` exists at the normalized package root.
2. JSON is UTF-8, within size limits, and matches the canonical schema identifier.
3. Name/version/author types and EvoFlux extension objects are valid.
4. Archive paths contain no traversal, absolute paths, duplicate case-folded names, or symlinks.
5. File count, expanded size, compressed size, and compression ratio are within limits.
6. The same plugin name/source is not already registered.

Reduce the package to manifest-only. Reintroduce Skills, MCP, and extensions one at a time to identify the failing component boundary.

### Skill is missing

Check that it is exactly `skills/<name>/SKILL.md`, not nested deeper. Confirm frontmatter uses only valid keys, the name matches the directory, description/body are nonempty, and the plugin is enabled. Then inspect precedence: a project/user/admin Skill with the same name shadows a plugin Skill; a plugin Skill shadows a built-in.

If the Skill loads but its tools are absent, verify the MCP server belongs to the same installation and is ready. Loading a Skill grants same-installation ready tools for that run, not failed or globally configured servers.

### MCP declaration is skipped

Separate a top-level `mcp.json` error from a per-server error. Verify only `$schema` and `mcpServers` exist at top level. Check transport type, URL rules, executable form, placeholder positions, resolved cwd containment, environment types, and extension server names.

Legacy `sse` is expected to be skipped. Do not “fix” that behavior by routing it through an unreviewed transport.

### MCP process will not become ready

Run the exact executable with the resolved arguments, cwd, and a redacted environment. Check missing dependencies, execute bits, interpreter availability, protocol logs accidentally written to stdout, imports relative to the wrong cwd, and unwritable data paths.

For linked plugins, wait for reconciliation and compare current validation with last-known-good runtime status. Force a lifecycle refresh by saving credentials or toggling enabled state only after capturing the original failure.

### Credentials remain missing or stale

Verify the manifest field declaration, unique key/env names, supported value type, and required/default semantics. Confirm the value was saved for the correct installation ID and that status was re-fetched after runtime refresh. A Plugin Center card should derive “credentials set/missing” from the current installation credential status, not a cached manifest-only guess.

Check injected values inside the child process only through a redacted diagnostic, never by returning the secret. EvoFlux overlays declared credential env values and then forces `PLUGIN_ROOT` and `PLUGIN_DATA`.

### Tool call fails after ready

Reproduce against a controlled fixture and classify the failure: validation, authentication, authorization, not found, rate limit, upstream 5xx, timeout, response parsing, result bound, or local data error. Preserve the upstream status category but sanitize request headers, tokens, userinfo, response bodies, and filesystem paths.

Assert the error returned by MCP is actionable without exposing raw upstream content.

### Update or uninstall behaves unexpectedly

Managed update requires a managed installation and an incoming package with the same manifest name. Assert installation ID, data directory, and enabled state remain unchanged. Linked plugins update from their source instead.

Uninstall preserves data unless removal is explicit. Treat deletion tests as destructive: resolve an isolated installation and data root before executing them.

## Regression-test rule

Place the regression test at the first owner of the broken invariant:

- validator/installer tests for format and extraction rules;
- runtime tests for reconciliation, environment, watchers, or process isolation;
- credentials tests for persistence/masking/injection;
- API tests for lifecycle refresh and response shape;
- UI tests for status derivation and actions;
- temporary package fixtures for upstream clients and actual tool behavior.

Avoid broad snapshot-only assertions. Assert stable behavior and security boundaries, not generated runtime prefixes or temporary installation paths.
