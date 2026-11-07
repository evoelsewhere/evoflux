# 0001. The desktop app is the only front end

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| ADD sections | [3. Architectural drivers](../README.md#3-architectural-drivers), [4. Process view](../README.md#4-process-view) |
| Related | [0003](0003-engine-runs-as-a-child-process-per-chat.md) |

## Context

evo started as a terminal CLI with a TUI, then grew a desktop app. Keeping
both meant every feature had two front ends, CLI concerns leaked into the
library crates, and the desktop could not rely on features the terminal could
not show (side panels, browser, approvals as cards).

## Decision

The CLI and TUI are dropped. evo is a headless engine (`evo-engine`), a wire
protocol (`evo-protocol`) and a desktop shell (`apps/desktop`). New work goes
into one of those three.

## Consequences

- Features are designed for the desktop UI; the engine stays headless and
  scriptable over the protocol.
- Library crates must not grow terminal or CLI concerns.
- Docs that still describe `evo` CLI commands or the TUI are stale and are
  rewritten when touched.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep CLI and desktop in parity | doubles the work for every feature; holds the desktop back |
| Keep the CLI as a thin protocol client | no current need; can be rebuilt on `evo-protocol` later |
