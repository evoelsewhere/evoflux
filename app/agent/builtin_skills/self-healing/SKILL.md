---
name: self-healing
description: Update an EvoFlux agent's own explicit configuration on request, including model, fallback model, thinking level, prompt, extra tools, tool opt-outs, skills metadata, MCP attachment, or creation of a user agent file. Use only for deliberate agent-configuration changes; do not use for application source, secrets, provider implementation, MCP installation, or skill/plugin installation.
---

# Update agent configuration

Make surgical edits only under `{EVOFLUX_CONFIG_DIR}/`. Do not load bundled
references when this skill activates. Never edit application code, `.env`,
secrets, built-in tool definitions, or bundled/read-only agent profiles through
this workflow.

## Route the request

- Agent model, thinking, fallback, prompt, `tools`, `tools_opt_out`, `skills`,
  or `mcp` metadata: continue here.
- Install or update an MCP server: load `$mcp-installer` instead.
- Create, import, or update a skill bundle: load `$skill-installer` instead.
- Install a plugin: load `$plugin-installer` instead.

## State machine

### 1. RESOLVE

Resolve the exact writable agent file. Use the current lead when “yourself” is
unambiguous; otherwise inspect `{EVOFLUX_CONFIG_DIR}/agents/` by `role:` and
`name:`. Do not hard-code filenames. Ask only if multiple writable candidates
remain.

### 2. INSPECT

Read the complete current file before proposing a change. Preserve unrelated
frontmatter, prompt text, comments, order, and formatting. If the file does not
exist, treat the request as explicit creation and preserve the invariant that
exactly one configured agent is the lead.

Read [references/agent-config-contract.md](references/agent-config-contract.md)
only when changing a model, thinking level, fallback, prompt, tools,
`tools_opt_out`, skills metadata, or creating a file. Read
[references/mcp-agent-wiring.md](references/mcp-agent-wiring.md) only when
attaching, selecting, or removing MCP tools from an agent.

### 3. VALIDATE

Validate the requested value against runtime-visible state before editing:

- model/provider and advertised thinking levels must exist;
- tool names must come from the current registry;
- skill names must come from the current discovered catalog;
- MCP server/tool names must come from current MCP status when reachable;
- implicit lifecycle/team invariants cannot be opted out;
- never expose or probe more than whether a required credential is configured.

For relative requests such as “think harder” or “respond faster,” move one
advertised thinking rung from the current value. For tone requests, add the
smallest precise prompt instruction that expresses the intent.

### 4. APPLY

Compute one minimal diff. If the user's current message explicitly authorizes
the exact change, apply it without a second approval turn and show the diff in
the same response. If the request is exploratory or the target/value remains a
choice, show the proposed diff and wait.

Use a targeted edit for an existing file and a create operation only for a new
file. Never reserialize the whole frontmatter when a line-level edit preserves
the user's formatting.

### 5. VERIFY

Read the resulting file and confirm the exact requested value, valid YAML, and
preserved invariants. Agent file edits take effect on that agent's next turn;
skill-body edits apply on the next fresh activation; agent-file additions or
removals change team shape and may require runtime restart. Report the actual
case without a generic restart instruction.

## Stop conditions

Stop when the target is exact, the value is registry-valid, the minimal diff is
applied or explicitly awaiting approval, the resulting file is verified, and
activation timing is accurately reported.

## Deliverable

Lead with what changed and which agent it affects. Include the exact file,
minimal diff, validation performed, effective timing, and any unresolved
credential, registry, or runtime requirement.
