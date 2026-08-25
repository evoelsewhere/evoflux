# Evo Agent Specs knowledge base

This directory is the repository-local, version-controlled EASD knowledge base.
It combines living product contracts with Run execution evidence without
relocating or copying documentation that the repository already owns elsewhere.

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
├── images/                        # media referenced by Markdown
├── templates/                     # current EASD artifact shapes
└── runs/                          # active/completed change ledgers
    └── <slug>--<run-uuid>/
        ├── run.yaml
        ├── intent.yaml
        ├── specifications/        # draft + immutable accepted Run snapshots
        ├── plans/
        ├── missions/
        ├── reviews/
        ├── verifications/
        ├── evidence/
        ├── deviations/
        ├── events/
        └── convergence.yaml
```

## Authority

- `specs/` is the discoverable catalogue of accepted behavior-first contracts.
- `features/`, `architecture/`, and `reference/` describe current shipped state
  and are reconciled when a Run changes those boundaries.
- `runs/` owns change-specific Intent, Plan, missions, evidence and convergence.
- `records/` is historical and never overrides current Specs or current-state
  documents.
- `templates/` defines shapes; template presence is not proof of implementation.

Draft Specs stay Run-local. User acceptance publishes a hash-identical immutable
copy into `specs/`; the Run snapshot remains audit evidence. Existing project
documentation outside this directory remains authoritative until maintainers
explicitly adopt or link it.

Do not store credentials, absolute machine paths, session bindings or locks
here. Rebuildable local state belongs under `.evoflux/easd/.local/`.
