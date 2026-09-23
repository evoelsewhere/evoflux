---
name: self-healing
description: Updates an EvoFlux agent's own explicit configuration file, including model, fallback model, thinking level, prompt text, extra tools, tool opt-outs, skills metadata, MCP attachment, or creation of a new user agent file. Use when the user deliberately asks to change how an agent is configured, for example "switch yourself to another model", "think harder by default", "give this agent the web tools", or "attach the github MCP server to the reviewer". Not for application source, secrets or .env, provider implementation, MCP server installation, or skill or plugin installation.
disable-model-invocation: true
---

# Update agent configuration

Make surgical edits only inside the EvoFlux configuration directory (its
absolute path is stated in the Skills section of the system prompt). User agent
files live in its `agents/` subdirectory. Never edit application code, `.env`,
secrets, built-in tool definitions, or bundled/read-only agent profiles through
this workflow.

## Route the request

- Agent model, thinking, fallback, prompt, `tools`, `tools_opt_out`, `skills`,
  or `mcp` metadata: continue here.
- Install or update an MCP server: read the `mcp-installer` skill instead.
- Install a third-party skill bundle: read the `skill-installer` skill instead.
- Author or restructure a skill: read the `skill-creator` skill instead.
- Install a single-file hook plugin: read the `plugin-installer` skill instead.

The locations of those skills are listed in the skills catalog in the system
prompt.

## State machine

### 1. RESOLVE

Resolve the exact writable agent file. Use the current lead when "yourself" is
unambiguous; otherwise inspect the `agents/` subdirectory of the EvoFlux
configuration directory by `role:` and `name:`. Do not hard-code filenames.
Ask only if multiple writable candidates remain.

### 2. INSPECT

Read the complete current file before proposing a change. Preserve unrelated
frontmatter, prompt text, comments, order, and formatting. If the file does not
exist, treat the request as explicit creation and preserve the invariant that
exactly one configured agent is the lead.

Read [references/agent-config-contract.md](references/agent-config-contract.md)
when changing a model, thinking level, fallback, prompt, tools,
`tools_opt_out`, skills metadata, or creating a file. Read
[references/mcp-agent-wiring.md](references/mcp-agent-wiring.md) when
attaching, selecting, or removing MCP tools from an agent.

### 3. VALIDATE

Validate the requested value against runtime-visible state before editing:

- model/provider and advertised thinking levels must exist;
- tool names must come from the current registry;
- skill names must come from the skills catalog in the system prompt;
- MCP server/tool names must come from current MCP status when reachable;
- implicit lifecycle/team invariants cannot be opted out;
- never expose or probe more than whether a required credential is configured.

For relative requests such as "think harder" or "respond faster," move one
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
agent-file additions or removals change team shape and may require runtime
restart. Report the actual case without a generic restart instruction.

## Stop conditions

Stop when the target is exact, the value is registry-valid, the minimal diff is
applied or explicitly awaiting approval, the resulting file is verified, and
activation timing is accurately reported.

## Deliverable

Lead with what changed and which agent it affects. Include the exact file,
minimal diff, validation performed, effective timing, and any unresolved
credential, registry, or runtime requirement.
