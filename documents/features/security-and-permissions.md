# Security and permissions

EvoFlux treats model output, tool observations, browser content, plugin content
and imported documents as untrusted. The harness, not the model, enforces
authorization and scope.

## Tool permission engine

Rules map `(tool glob, argument/path pattern)` to `allow`, `deny` or `ask`.
Evaluation is last-match-wins so a later specific rule can override a broad
default. When nothing matches, the result is `ask`. Read-only inspection,
bookkeeping and team-coordination tools have safe defaults that can still be
overridden by later rules.

Session permission modes resolve `ask` as follows:

| Mode | Behavior |
|---|---|
| `ask` | Pause and publish a permission request |
| `accept-edits` | Auto-allow edit/write/patch; ask for other unresolved calls |
| `plan` | Auto-allow tool layer after explicit plan gating |
| `auto` | Auto-allow unresolved calls within remaining sandbox/policy checks |
| `bypass` | Skip permission-rule evaluation; intended only for explicitly trusted use |

User replies can allow once, add a session-scoped always rule, or reject. A mode
change resolves pending requests that the new mode permits. Permission modes do
not bypass filesystem sandboxing, browser policies, provider capability checks,
workflow approval or Conductor enforcement.

## Filesystem and shell sandbox

The active Work session or authorized Coding repository defines the accessible
root. EvoFlux data/state/cache roots are denied. Path validation rejects
traversal and symlink escapes. `sandbox.yaml` adds configurable denied glob
patterns and initially protects `.env` files.

Shell commands are tokenized for denied-path checks, receive a controlled
environment and hide internal `EVOFLUX_*` variables. Worktrees may live beside
the repository or in user data according to Settings. Destructive actions still
require the applicable permission decision.

## Outbound protection

Outbound redaction scans provider/tool-bound data for configured secrets and
PII. Policy can be `off`, `redact` or `block`, with standard/strict PII modes.
Secret sources include the process environment and config `.env`; reports
identify categories without echoing secret values.

## API and desktop authentication

Bundled desktop sessions use a random per-launch token injected only into
same-origin API requests. External/LAN operation can use a configured access
key. Health behavior is split into live, ready and bounded diagnostics.
Middleware also enforces request-size limits, security headers and configured
CORS origins.

## Integration boundaries

- MCP tools inherit normal permissions; plugin MCP runs in an isolated manager.
- Portable plugins are disabled until trust review and cannot inject host UI or
  code; legacy Python hooks require explicit local trust.
- Git credentials are host-scoped, transiently injected and redacted.
- Code-review connections default to TLS verification and bounded provider
  hosts/media.
- Browser and WebBridge have independent domain/action/sharing policies.
- Workflow direct tool execution requires hash-bound approval and remains pinned
  to its workspace sandbox.
- Memory and Dream treat source text as data, reject secrets and preserve scope.

## Conductor

Conductor is an optional organization control plane. It can enroll an
installation, synchronize signed/versioned managed resources, report drift and
deliver policy-scoped telemetry. `report` mode surfaces drift without blocking;
`enforce` applies governed resource policy. Credentials live outside normal
settings payloads, and managed provenance is displayed in Settings.

## Source and tests

Primary code: `app/agent/permission.py`, `sandbox.py`, `sandbox_config.py`,
`outbound_redaction.py`, `app/core/desktop_auth.py`, security middleware,
plugin/WebBridge/Git policy modules and `app/conductor/`.

Security-focused coverage includes permission modes/rules, sandbox traversal and
read-only behavior, shell environment, outbound redaction, desktop auth,
middleware, plugin trust, Git credentials, WebBridge policy and Conductor
governance.
