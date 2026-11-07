# 0006. Design documentation follows ADD, SDD and ADR

| | |
| --- | --- |
| Status | Superseded by [0011](0011-features-follow-spec-driven-development.md) |
| Date | 2026-11-06 |
| ADD sections | [11. Architecture decisions](../README.md#11-architecture-decisions) |
| Related | [docs/README.md](../../README.md) |

## Context

Design notes lived in `docs/design/*.md` and `docs/notifications.md` with no
common structure. Status paragraphs piled up at the top of each note, current
behaviour was mixed with plans and history, and there was no system-level
document for new features to fit into.

## Decision

- One living **ADD** (`docs/architecture/README.md`) describes the system.
- **ADRs** (`docs/architecture/decisions/`) record architecture decisions.
- Each feature has an **SDD** (`docs/features/<slug>/sdd.md`) from
  `docs/templates/sdd.md`, accepted before code and kept current as the
  feature ships and changes.
- The rules are in `docs/README.md`; `AGENTS.md` points to them.

## Consequences

- Existing notes moved to `docs/features/<slug>/sdd.md` with a header table;
  their bodies keep the older layout until next edited, then move to the
  template.
- Code comments link `docs/features/<slug>/sdd.md`.
- Architecture-level changes need an ADR and an ADD edit in the same commit.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep free-form design notes | no predictable place for requirements, interfaces or verification |
| One big design document | merge conflicts; features cannot be reviewed on their own |
