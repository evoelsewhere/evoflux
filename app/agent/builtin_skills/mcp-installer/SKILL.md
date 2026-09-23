---
name: mcp-installer
description: Installs, inspects, updates, restarts, authenticates, or removes EvoFlux Model Context Protocol (MCP) servers in mcp.json and wires their tools to a selected agent. Use when the user explicitly asks to add an MCP server, connect an HTTP or stdio MCP endpoint, fix MCP OAuth, restart a runner, or remove a server. Not for calling an already configured integration, authoring a new MCP server, or installing a plugin or skill.
disable-model-invocation: true
---

# Manage MCP servers

Use the bundled helper `scripts/mcp_apply.py` for every daemon and
configuration operation. It uses only the Python standard library. Resolve its
absolute path from this skill's directory (the parent of this `SKILL.md`) and
run it with the `shell` tool:

```bash
python scripts/mcp_apply.py <operation> [args]
```

Use `python3` instead of `python` only when `python` is not on `PATH`. Do not
construct raw daemon requests or edit `mcp.json` by hand while the helper can
perform the operation. Run `python scripts/mcp_apply.py --help` only when the
exact subcommand or argument is not already known.

`mcp.json` lives in the EvoFlux configuration directory; agent files live in
its `agents/` subdirectory. Both absolute paths follow from the EvoFlux
configuration directory stated in the Skills section of the system prompt.

## State machine

### 1. RESOLVE

Identify the exact server name, transport (`http` or `stdio`), endpoint or
command, required arguments, environment variable names, target agent, and
whether all or selected tools should be wired. Inspect current state first:

```bash
python scripts/mcp_apply.py status [name]
```

Do not invent package names, endpoints, headers, OAuth mode, commands, tool
names, or agent targets. Ask only for a missing value that cannot be derived
from the provided server documentation or current configuration.

### 2. SAFETY

Use `${ENV_VAR}` references for secrets. Never print, request in chat, embed in
command history, or persist a raw API token when an environment reference or
OAuth flow is available. Direct confidential OAuth credentials, when required
by the helper, must be stored through its supported credential flow rather
than written into `mcp.json`.

Resolve relative filesystem arguments to absolute paths because stdio runners
do not inherit the user's interactive working directory. Inspect existing
agent references before removing or renaming a server.

### 3. MUTATE

Choose exactly one operation and run it once:

```text
add NAME --http URL [--header KEY=VALUE] [--oauth ...]
add NAME --stdio COMMAND --args ... [--env KEY=VALUE]
update NAME <transport options>
restart NAME
connect-oauth NAME
remove NAME
apply
```

Invoke it as `python scripts/mcp_apply.py <operation> ...`. Treat exit codes as
follows:

- `0`: configuration applied, or safely written while the daemon was offline;
- `1`: validation/API error; correct the reported input before retrying;
- `2`: runner error or authentication required; inspect status and fix that
  condition;
- `3`: readiness wait timed out; report the current state instead of looping.

Do not retry a state-changing operation after an ambiguous result until status
shows whether it already applied.

### 4. WIRE

Installation is incomplete until the requested agent can use the tools. Read
the target agent file and make one minimal frontmatter edit:

- add the server name to `mcp:` for all current and future server tools; or
- add exact returned `mcp_<server>_<tool>` names to `tools:` for selective
  access.

Never guess selective tool names. Preserve existing frontmatter and code-owned
defaults. When removing a server, remove its `mcp:` and selective `tools:`
references from every affected agent **before** running `remove`, preventing a
stale next-turn configuration.

### 5. VERIFY

Run:

```bash
python scripts/mcp_apply.py wait NAME --timeout 30
python scripts/mcp_apply.py status NAME
```

Confirm the expected runner state and returned tool names, then reread the
target agent frontmatter. If the daemon is offline but the helper safely wrote
configuration, report that readiness remains unverified and that the running
desktop app hot-applies the written `mcp.json` when it is next reachable. Do not
claim the MCP server is usable from a successful file edit alone.

## Stop conditions

Stop when the exact configuration is present, secrets are referenced safely,
the runner state is known, requested agent wiring is verified, and no stale
agent reference remains after removal.

## Deliverable

Report server name, transport, final state, target agent and wiring mode,
available tool names when known, operations actually completed, and any OAuth,
credential, daemon, or readiness action still required.
