# Retire the non-executable `terminal_run` agent tool

Status: implemented

## Problem and outcome

The built-in registry advertises `terminal_run` as a lead-only command executor
for the user's visible terminal, but every invocation returns a refusal and tells
the agent to use `shell`. This costs an unnecessary deferred-tool activation
round, misstates current product behavior, and is covered only by registration
tests.

The accepted outcome is to stop advertising `terminal_run` until a separately
specified permission-compliant live-terminal execution design exists. The
desktop terminal service remains unchanged.

## Goals

- Remove `terminal_run` from the built-in agent tool registry and catalogue.
- Remove the dead tool implementation while preserving the terminal service.
- Add registry invariants that detect duplicate built-in keys, names, and
  callable implementations.
- Make current feature documentation match executable behavior.

## Non-goals

- Do not add agent access to the user's live PTY.
- Do not change `shell`, `process`, terminal UI, or terminal service behavior.
- Do not rename or consolidate other overlapping tools.
- Do not change MCP or plugin tool naming.

## User flows and states

- A lead searching deferred tools no longer sees `terminal_run`.
- Command execution continues through `shell`; long-running commands continue
  through `process`.
- Existing user-authored agent configuration that names `terminal_run` is
  tolerated by the existing unknown-tool soft-skip path and emits the existing
  warning rather than preventing the agent from loading.
- The visible terminal remains available for direct user interaction.

## Requirements and acceptance criteria

- **AC-1:** Given the default built-in registry, when it is constructed, then
  `terminal_run` is absent while `shell` and `process` remain registered.
- **AC-2:** Given any built-in registry entry, its registry key equals
  `Tool.name`, and no two built-in entries share the same callable
  implementation.
- **AC-3:** Given a work or coding lead's tier grant, `terminal_run` is absent.
- **AC-4:** Given current product documentation, native command capabilities
  mention shell, Python, and managed processes without claiming agent control of
  the visible terminal.
- **AC-5:** Focused registry, loader, tier-policy, shell, process, and terminal
  service tests pass without changing terminal service behavior.

## API, event, tool, and UI contracts

The agent tool catalogue returned by the existing agents API no longer contains
`terminal_run`. No HTTP, SSE, provider, or terminal-service wire shape changes.
The `shell` and `process` schemas remain byte-for-byte unchanged.

## Data model, migration, and retention

No schema or data migration is required. Agent Markdown files are not rewritten.
Unknown configured tools already degrade through loader warning and soft-skip
behavior.

## Permissions, security, privacy, and trust

Removing the tool closes a misleading route to a host PTY that cannot comply
with the per-command environment and permission controls. No permission is
broadened. A future live-terminal agent feature requires a separate accepted
specification covering PTY ownership, confirmation, environment inheritance,
output capture, interruption, and audit.

## Concurrency, failure, recovery, and idempotency

Registry construction remains deterministic. Repeated loads produce the same
tool set. A stale configured `terminal_run` entry is skipped on every load
without mutating the source file. Recovery is to use `shell` or remove the stale
configuration entry.

## Observability and diagnostics

The existing `agent_unknown_tool` warning identifies stale user configuration.
No new telemetry is required. Registry invariant tests provide build-time
diagnostics for accidental duplicate registration.

## Compatibility, rollout, and rollback

This removes a non-executable deferred tool and therefore does not remove a
working command path. Rollout is an ordinary application update. Rollback
restores the tool module and registry entry, although doing so should require a
working implementation or corrected documentation.

## Verification matrix

| Acceptance criterion | Implementation owner | Evidence |
|---|---|---|
| AC-1 | `app/agent/loader.py` | registry unit test and agents API catalogue test |
| AC-2 | Built-in registry contract | `tests/agent/tools/test_registry.py` |
| AC-3 | Tier compiler | focused tier-policy tests |
| AC-4 | `documents/features/tools-skills-mcp-and-plugins.md` | documentation inspection |
| AC-5 | Agent tools and terminal service | focused pytest suite plus Ruff, ty, and `git diff --check` |

## Ownership and source map

- `app/agent/loader.py` — default built-in registry.
- `app/agent/tools/builtin/terminal.py` — dead agent tool implementation to
  remove; this is separate from the terminal service.
- `app/services/terminal_service.py` — user-facing terminal lifecycle,
  unchanged.
- `tests/agent/tools/test_registry.py` — registry invariants.
- `tests/services/test_terminal_service.py` — terminal service behavior.
- `tests/agent/mode/team/test_tier_policy.py` — mode/role grants.
- `documents/features/tools-skills-mcp-and-plugins.md` — current native-tool
  contract.
