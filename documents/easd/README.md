# Evo Agent Specs repository store

This directory is the version-controlled source of truth for EASD runs owned by
this repository. Commit Intent, immutable Spec/Plan revisions, lifecycle events,
mission snapshots, review/verification evidence, deviations, and convergence.

## Document skeleton

`<data_directory>` is this directory. It defaults to `documents/easd` and is
resolved from `.evoflux/easd/config.json`.

```text
<repository>/
├── .evoflux/
│   ├── easd/
│   │   ├── config.json
│   │   ├── RULES.md
│   │   ├── .gitignore
│   │   └── .local/                     # ignored, rebuildable
│   └── skills/
│       └── easd-{specify,plan,implement,review,verify}/
│           ├── SKILL.md
│           └── .evoflux.json
└── <data_directory>/
    ├── README.md
    ├── templates/
    │   ├── intent.yaml
    │   ├── specification.yaml
    │   ├── plan.yaml
    │   ├── run.yaml
    │   ├── mission.yaml
    │   ├── review.yaml
    │   ├── verification.yaml
    │   ├── evidence.yaml
    │   ├── deviation.yaml
    │   └── event.yaml
    └── runs/
        └── <slug>--<run-uuid>/
            ├── run.yaml                # mutable CAS lifecycle projection
            ├── intent.yaml
            ├── specifications/0001.yaml
            ├── plans/0001.yaml         # planned flow only
            ├── missions/<mission-uuid>.yaml
            ├── reviews/<evidence-uuid>.yaml
            ├── verifications/<evidence-uuid>.yaml
            ├── evidence/<evidence-uuid>.yaml
            ├── deviations/<deviation-uuid>.yaml
            ├── events/<sequence>-<event-uuid>.yaml
            └── convergence.yaml        # only after Converge
```

Later Spec/Plan revisions increment the zero-padded filename (`0002.yaml`,
`0003.yaml`, ...). Direct flow leaves `plans/` empty. Imported full drafts may
omit `intent.yaml`; phase-specific artifact directories remain empty until that
phase produces records.

Accepted Spec/Plan revisions and `convergence.yaml` are immutable. Events and
evidence are append-only. `run.yaml`, mission snapshots, and open deviations
use document hashes for compare-and-swap updates so collaborators never silently
overwrite newer repository state.

Do not store machine-specific session IDs, locks, credentials, or absolute paths
here. Rebuildable local state belongs under `.evoflux/easd/.local/`.
