# <Feature name>

| | |
| --- | --- |
| Status | Draft |
| Area | <engine · protocol · desktop shell · desktop UI · crate `evo-…`> |
| Created | YYYY-MM-DD |
| Updated | YYYY-MM-DD |
| ADD sections | [<section>](../../architecture/README.md#<anchor>) |
| ADRs | [NNNN <title>](../../architecture/decisions/NNNN-<slug>.md) or none |
| Related | [<other feature>](../<slug>/sdd.md) or none |

<!--
How to use: copy to docs/features/<slug>/sdd.md and add a row to
docs/features/README.md. Keep every numbered section; write
"n/a — <reason>" where one does not apply. Rules: docs/README.md.
Delete this comment.
-->

## 1. Summary

Two to five sentences: what the feature does for the person using evo, and
why it is needed now.

## 2. Scope

### 2.1 Goals

- …

### 2.2 Non-goals

- … (what this feature deliberately does not do, and where that lives instead)

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | … | Given …, when …, then … |

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Performance / platform / offline / limits … | … |

## 4. Context and constraints

What exists today that this builds on (with paths), the ADD rules and ADRs it
must respect, and external constraints (APIs, OS behaviour, licences).

## 5. Design

### 5.1 Overview

The shape in one diagram (Mermaid or ASCII) and a paragraph.

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| crate | `crates/evo-…/src/…` | … |
| engine | `crates/evo-engine/src/…` | … |
| protocol | `crates/evo-protocol/src/…` | … |
| desktop shell | `apps/desktop/src-tauri/src/…` | … |
| desktop UI | `apps/desktop/src/features/…` | … |

### 5.3 Interfaces

Protocol commands/events, mesh ops, Tauri commands/events, agent tool schemas,
RPC methods, plugin ABI. Write the shapes out (JSON / Rust / TS). State how
older engines or clients behave.

### 5.4 Data and storage

Tables and migrations (`crates/evo-store/src/migrations/NNNN_….sql`), files
under `~/.evo/agent/` or the project's `.evo/`, in-memory state and its
lifetime.

### 5.5 Behaviour

Main flows, states and transitions, ordering and concurrency. A sequence
diagram for anything crossing a process.

### 5.6 Errors and edge cases

Failure modes and what the user and the agent see for each: cancellation,
engine crash or restart, offline, missing permission, large inputs.

### 5.7 Security and trust

Untrusted inputs, permission prompts, sandbox rules, credentials, project
trust, what the model can and cannot do with this feature.

### 5.8 Configuration

Settings keys (name, type, default, where stored), whether a change applies
live or on engine restart, and the UI that edits it.

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| … | … |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | … | … | … |

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-… <name>` / manual check in the running app | not run · passed (YYYY-MM-DD) |

## 9. Open questions

1. … (each with the proposed answer; resolved ones move into the design)

## 10. As-built notes

Where the implementation differs from the design above and why. Empty until
`In progress`.

## 11. History

- YYYY-MM-DD — Draft.
