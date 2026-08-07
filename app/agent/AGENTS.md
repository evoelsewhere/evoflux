# app/agent/ — Agent Instructions

Agent runtime: loops, providers, tools, teams, MCP, permissions, prompts, and runtime config loading.

## Where to look first

```
loader.py              Agent `.md` frontmatter schema and validation
drift.py               Hot-reload detection for edited agent files
builtin_prompts.py     Code-owned base prompts for first-party agents
agent_loop/            Core turn loop, tool execution, streaming, retries
providers/             LLM provider implementations and routing
schemas/               Chat/event/provider wire types
tools/                 Built-in tool registry and implementations
mcp/                   MCP config, manager, installer/runtime integration
mode/team/             Multi-agent teams, roster, mailbox, todo flow
plugins/               User plugin loading and role context
permission.py          Tool permission decisions
sandbox*.py            Shell/filesystem sandbox behavior
```

## Common feature checks

- Agent config/frontmatter change: update the config compiler, seed agents if needed, and `documents/architecture/application-harness.md`.
- Tool change: check `tools/registry.py`, the tool implementation, permission/sandbox behavior, and UI rendering if the result shape changes.
- Skill visibility change: keep portable bundle defaults separate from the user-owned `skill-settings.json` overlay. Runtime preferences are keyed to the exact discovered variant, apply before mode-aware collision selection, and must never rewrite built-in, administrator, symlinked, or project bundle files.
- Coding navigation change: keep the built-in `code_graph` tool schema, service boundary, renderer, telemetry, tests, and the exact-symbol contracts embedded in Coding skills aligned. Do not create a separate graph-routing skill or inject graph prose at mode level. `code_graph` accepts a known raw symbol and structural operation; it must never become natural-language retrieval.
- Team behavior change: check `mode/team/`, `services/team_manager.py`, API routes, and SSE event consumers in `web/src/stores/`.
- Provider change: add/adjust tests under `tests/agent/providers/` and avoid leaking provider-specific shapes into generic schemas.

## Commands

```bash
uv run pytest --no-cov -q tests/agent
uv run ruff check app/agent tests/agent
uv run ty check app/
```

## Gotchas

- First-party profile frontmatter is additive on top of code-owned defaults.
- `team_message` and `todo_manage` are injected; do not ask users to list them manually.
- Keep prompt bodies tool-agnostic because runtime capabilities can change.
- Streaming loops must catch provider/tool chunk errors and emit recoverable events where possible.
