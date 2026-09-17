# Output template — asdd-propose

`changes/<change-id>/proposal.md`. The product writes `change`, `title` and
`created`, and seeds `## Why` and `## What Changes` from the create form. You
set `risk`, `capabilities` and `status`; never `approvals`.

`risk` is usually absent on arrival. Absent is not `standard` — it means nobody
has tiered the change, and the proposal gate refuses until one is set.

```markdown
---
change: add-note-search
title: Add note search
status: proposed
risk: standard
capabilities:
- note-search
created: '2026-09-17T08:00:00Z'
approvals:
  proposal: null
  specs: null
  design: null
  tasks: null
---

## Why

The problem in the user's terms, and what goes wrong if nothing changes. Not
"we should add search" — who cannot do what today, and what it costs them.

## What Changes

- One bullet per observable change. Mark breaking changes explicitly.

## Capabilities

### New Capabilities

- `note-search`: one sentence naming the behavior this capability owns.

### Modified Capabilities

- `note-storage`: what about its existing contract changes.

## Impact

- Code, data and operations this touches.
- Non-goals: what this change deliberately does not do, including anything the
  user ruled out of scope.
```

## Rejected if

- `risk` is missing — the gate refuses, naming the four tiers.
- `## Why` restates the title, or paraphrases the requester's problem without
  adding what it costs them.
- A capability is invented when `specs/` already contracts the behavior.
- `## Impact` has no non-goals — every real change has a boundary.
