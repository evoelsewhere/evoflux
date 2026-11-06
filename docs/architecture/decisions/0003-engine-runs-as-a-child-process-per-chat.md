# 0003. The engine runs as a child process, one per open chat

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-06 (recorded; in effect since the desktop shell was introduced) |
| ADD sections | [4. Process view](../README.md#4-process-view) |
| Related | [Session mesh SDD](../../features/session-mesh-protocol/sdd.md) |

## Context

The engine loads native plugins (`cdylib`), runs tools and talks to
providers. A crash or hang in any of these must not take the window down, and
several chats run at once, each with its own folder and session.

## Decision

The desktop shell starts `evo-engine --mode rpc` as a child process for each
open chat, passing `--session-id`, `--session-db` and `--sandbox-config`, and
relays the protocol over stdin/stdout. The shell links no engine crate.
Cross-chat coordination (mesh hub, MCP pool, app database) lives in the shell.

## Consequences

- Crash isolation per chat; a chat's engine can be restarted to reload
  configuration.
- Code shared by shell and engine lives in leaf crates.
- Each open chat costs a process.
- The engine binary ships as a Tauri sidecar and must be rebuilt and restaged
  when engine code changes.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Engine in-process in the shell | a plugin or tool crash kills the app |
| One engine process for all chats | one crash stops every chat; per-chat folders and sandboxes get harder |
