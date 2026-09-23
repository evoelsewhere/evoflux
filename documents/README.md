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

## What does not belong here

Adoption is an explicit approved change.

Do not store credentials, absolute machine paths or lock state anywhere under
`documents/`. Contributor, build and release procedure stays wherever the
repository already owns it — `CONTRIBUTING.md`, `AGENTS.md`, the makefile. Link
to it; do not copy it here.
