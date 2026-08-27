# Evo Agent Specs knowledge base

This directory is the repository-local, version-controlled EASD knowledge base.
It contains accepted and explicitly adopted contracts without relocating or
copying documentation that the repository already owns elsewhere. Operational
Run data is local and ignored under `.evoflux/easd/.local/runs/`.

## Structure

```text
<data_directory>/
├── README.md
├── index.yaml
├── specs/                         # accepted normative behavior contracts
├── features/                      # current implemented product behavior
├── architecture/
│   └── decisions/                 # ADR-style durable decisions
├── reference/                     # exact API/config/schema/CLI contracts
├── guides/                        # task-oriented user/operator workflows
├── development/                   # contributor/build/test/release procedures
├── records/
│   ├── analysis/                  # dated audits
│   ├── research/                  # prior art and investigations
│   ├── plans/                     # proposed or historical designs
│   └── releases/                  # release/submission evidence
└── images/                        # media referenced by Markdown

.evoflux/easd/.local/
├── templates/                     # bundled runtime artifact shapes
└── runs/                          # ignored operational ledgers
    └── <slug>--<run-uuid>/        # Intent, Plan, missions, evidence, events
```

## Authority

- `specs/` is the discoverable catalogue of accepted behavior-first contracts.
- `features/`, `architecture/`, and `reference/` describe current shipped state
  and are reconciled when a Run changes those boundaries.
- `.evoflux/easd/.local/runs/` owns change-specific Intent, Plan, missions,
  evidence and convergence and is not a Git collaboration transport.
- `records/` is historical and never overrides current Specs or current-state
  documents.
- Bundled local templates define shapes; template presence is not proof of
  implementation.

Draft Specs stay Run-local. User acceptance publishes a hash-identical immutable
copy into `specs/`; the Run snapshot remains audit evidence. Existing project
documentation outside this directory remains authoritative until maintainers
explicitly adopt or link it.

Do not store credentials, absolute machine paths, session bindings or locks
here. Rebuildable local state belongs under `.evoflux/easd/.local/`.
