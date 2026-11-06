# 0005. The app always runs the real engine; configuration reloads live

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-06 |
| ADD sections | [4. Process view](../README.md#4-process-view), [9. Cross-cutting concepts](../README.md#9-cross-cutting-concepts) |
| Related | [0003](0003-engine-runs-as-a-child-process-per-chat.md) |

## Context

A mocked engine in the desktop hid real protocol and timing problems, and
asking people to restart the app after connecting a provider was confusing.

## Decision

The desktop always talks to a real `evo-engine`; there is no mock mode.
Credential, settings and customization changes take effect without restarting
the app: idle engines are restarted with the new configuration and running
ones pick it up on their next start.

## Consequences

- Development and verification run the real engine (stage the sidecar first).
- Fakes (`faux` provider, in-memory environments) are for crate tests only.
- A feature that changes configuration states how running engines pick it up
  (SDD section 5.8).

## Alternatives considered

| Option | Why not |
| --- | --- |
| Mock engine for UI work | drifts from the real protocol; bugs found late |
| Restart the app on config change | disruptive; loses running chats |
