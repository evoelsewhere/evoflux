# <Feature name> — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | YYYY-MM-DD |
| ADD sections | [<section>](../../architecture/README.md#<anchor>) |
| ADRs | [NNNN <title>](../../architecture/decisions/NNNN-<slug>.md) or none |

<!--
The plan says HOW the accepted spec is built: where it fits in the
architecture, which code it touches, the interfaces and data it adds.
Every design choice traces to a requirement in spec.md (FR-n / NFR-n);
anything the spec does not ask for does not belong here.
Copy to docs/features/<slug>/plan.md. Keep every numbered section; write
"n/a — <reason>" where one does not apply. Rules: docs/README.md.
Delete this comment.
-->

## 1. Context and constraints

What exists today that this builds on (with paths), external constraints
(APIs, OS behaviour, licences), and research that shaped the plan.

## 2. Architecture check

Check the plan against the project's standing rules — `AGENTS.md`
("Architecture rules") and the [ADD](../../architecture/README.md). Every
row is `ok`, `n/a`, or a deviation with the ADR that allows it.

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | … |
| Layers point down; library crates stay free of engine/desktop concerns | ok | … |
| Protocol changes update `evo-protocol`, the engine and the desktop together | n/a | … |
| Models come from models.dev; no hardcoded model facts | n/a | … |
| Real engine in the app; settings and credentials reload live | ok | … |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | … |
| Desktop UI structure and `DESIGN.md` | n/a | … |

## 3. Design

### 3.1 Overview

The shape in one diagram (Mermaid or ASCII) and a paragraph.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-…/src/…` | … | FR-1 |
| engine | `crates/evo-engine/src/…` | … | |
| protocol | `crates/evo-protocol/src/…` | … | |
| desktop shell | `apps/desktop/src-tauri/src/…` | … | |
| desktop UI | `apps/desktop/src/features/…` | … | |

### 3.3 Interfaces

Protocol commands/events, mesh ops, Tauri commands/events, agent tool schemas,
RPC methods, plugin ABI. Write the shapes out (JSON / Rust / TS). State how
older engines or clients behave.

### 3.4 Data and storage

Tables and migrations (`crates/evo-store/src/migrations/NNNN_….sql`), files
under `~/.evo/agent/` or the project's `.evo/`, in-memory state and its
lifetime.

### 3.5 Behaviour

Main flows, states and transitions, ordering and concurrency. A sequence
diagram for anything crossing a process.

### 3.6 Errors and edge cases

Failure modes and what the person and the agent see for each: cancellation,
engine crash or restart, offline, missing permission, large inputs.

### 3.7 Security and trust

Untrusted inputs, permission prompts, sandbox rules, credentials, project
trust, what the model can and cannot do with this feature.

### 3.8 Configuration

Settings keys (name, type, default, where stored), whether a change applies
live or on engine restart, and the UI that edits it.

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| … | … |

## 5. As-built notes

Where the implementation differs from the plan above and why. Empty until
the status is `In progress`.
