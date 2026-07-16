---
name: aim-kb-conventions
description: Conventions for reading and writing an AIM migration project's knowledge-base (KB) repo. Use when writing to, or citing from, modules/, business-rules/, mapping/, decisions/, or any other part of an AIM project's KB. Use when joining an AIM project as a new contributor and needing to know where things live.
---

# AIM knowledge-base conventions

## Overview

An AIM project's knowledge base is a git repository, not a database table and not a chat transcript — it is simultaneously the team's shared understanding of the migration, the audit trail, and a deliverable handed to the customer at the end of the engagement. Multiple people (and multiple agent sessions) write to it concurrently, on their own machines, converging through ordinary git operations. Following these conventions is what keeps that convergence conflict-free instead of chaotic.

## When to Use

- Writing any document into an AIM project's KB repo (module docs, business rules, mappings, ADRs, run reports).
- Reading the KB to understand current project state, conventions, or prior decisions before doing new work.
- Onboarding to an AIM project you didn't set up — the KB should be self-explanatory from `INDEX.md` and `aim.yaml`.

## When NOT to Use

**When NOT to use:** for target or base source code itself — those are ordinary git repos with their own conventions (framework/language idioms, not KB structure). Also not for session-scoped scratch notes that don't need to survive beyond the current turn — the KB is for durable project knowledge, not working notes.

## Layout and where things go

- `aim.yaml` — the project manifest: rulebook id/version, and which repos play which role (source, target, kb) by a shared identity (remote URL or logical name), not by any one machine's local path. Read this first when joining a project.
- `modules/<module>/<unit>.md` — one file per migration unit, namespaced by module so multi-repo estates don't collide. Frontmatter carries the unit's live state (`phase`, `wave`, `assignee`) — this is what makes the KB the source of truth for project state rather than a side artifact.
- `business-rules/BR-<MOD>-####.md` — one rule per file, `status: candidate` until an SME confirms it. Never cite a candidate rule as if it were confirmed.
- `data-dictionary/`, `interfaces/` — shared reference material, written once and updated as understanding improves, not duplicated per unit.
- `target-conventions.md`, `ui-conventions.md` — project-level decisions made once by `aim-target-architect`, cited by every unit's mapping rather than re-decided per unit.
- `mapping/<unit>.md`, `decisions/ADR-###.md` — design decisions, with ADRs used for anything that deviates from the obvious mapping or from legacy behavior.
- `golden/units/<unit>/cases/<case-id>/`, `runs/<unit>/<run-id>/` — golden-master cases and compare run reports; these are the evidence trail equivalence claims rest on.

## Contribution conventions (multiple people, one repo)

- **Claim a unit before working on it** by setting `assignee` in its frontmatter — one commit, visible to everyone else after their next pull. Two people editing the same unit's file concurrently is a coordination miss, not a tooling problem to route around.
- **Prefix IDs by module** (business rules, and any other ID space that might be touched from more than one repo) so parallel work never collides on an identifier.
- **Confirmation is a PR review**, not a chat message — an SME confirming a business rule, or an architect approving `ui-conventions.md`, should do it by reviewing the actual file change in the KB repo, so the audit trail (who approved what, when) is the git history itself.
- **Pull before you plan, push when you're done** — the KB is the shared state; anything that only lives in your local working copy hasn't actually happened yet from the rest of the team's point of view.

## Verification

Before writing to the KB: does this belong in an existing file (updating in place) or does it need a new one following the naming convention above? Does a business rule or design decision you're citing actually have `status: confirmed` (or an approved ADR), not just a candidate you assumed was fine? If you're about to duplicate something that should be a project-level convention (a UI pattern, a mapping rule) into a per-unit file instead of citing the shared doc, stop and fix that first — duplication here is exactly how migrations end up inconsistent across units.
