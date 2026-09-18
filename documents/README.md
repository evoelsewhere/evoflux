# EvoFlux documentation

This directory is the single documentation root for the product and its
contributors. Two things live here with different owners.

## Written by people

```text
documents/
├── features/       # current implemented product behavior
├── architecture/   # process, storage, concurrency, trust and system boundaries
│   └── decisions/  # ADR-style durable decisions
├── reference/      # exact API, configuration, schema and CLI contracts
├── guides/         # task-oriented walkthroughs
├── development/    # contributor and release procedure
├── analysis/ research/ plans/ releases/   # dated, historical
└── images/
```

`features/`, `architecture/` and `reference/` describe what ships today. The
dated directories are historical and never override them.

## Owned by Agent Spec-Driven

```text
documents/asdd/
├── project.md                   # this repository's context and rules for agents
├── specs/
│   └── <capability>/spec.md     # the behavior the system guarantees now
└── changes/
    ├── <change-id>/             # one proposed change, with its own folder
    └── archive/YYYY-MM-DD-<change-id>/
```

This subtree is the ASDD catalogue. `specs/` is normative: when code and a
capability spec disagree, the code is wrong until a change says otherwise.
A spec changes only when a change is archived — never by hand.

See [ASDD methodology](reference/asdd-methodology.md) for the lifecycle and
[Agent Spec-Driven](features/agent-specs.md) for the product surface.

## What does not belong here

ASDD setup never moves or copies existing documentation into `documents/asdd/`.
Adoption is an explicit approved change.

Do not store credentials, absolute machine paths or lock state anywhere under
`documents/`. Contributor, build and release procedure stays wherever the
repository already owns it — `CONTRIBUTING.md`, `AGENTS.md`, the makefile. Link
to it; do not copy it here.
