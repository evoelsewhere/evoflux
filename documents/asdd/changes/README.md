# Changes

One directory per proposed change. The directory name is the change's identity —
kebab-case, stable, and the only handle anything uses to refer to it.

```text
changes/
├── <change-id>/
│   ├── proposal.md          # why and what; front matter carries status + approvals
│   ├── design.md            # how; required for cross_layer and critical risk
│   ├── tasks.md             # the checklist agents execute
│   ├── specs/
│   │   └── <capability>/
│   │       └── spec.md      # ADDED / MODIFIED / REMOVED Requirements
│   └── evidence/
│       └── <id>.md          # what was run, and what it showed
└── archive/
    └── YYYY-MM-DD-<change-id>/
```

## Status lives in `proposal.md`

```yaml
---
change: add-user-auth
title: Add user authentication
status: implementing
risk: standard
capabilities: [user-auth]
created: 2026-09-16T08:00:00Z
approvals:
  proposal: 2026-09-16T08:11:00Z
  specs: 2026-09-16T09:02:00Z
  design: null
  tasks: null
---
```

`status` moves through: `drafting` → `proposed` → `specifying` → `specified` →
(`designing` → `designed`, for `cross_layer` and `critical` risk) → `tasking` →
`tasked` → `implementing` → `verifying` → `ready` → `archived`.

Editing this file by hand is legitimate — it is the source of truth. If the
status you write disagrees with what the folder contains, the product says so
and leaves both alone for you to settle.
