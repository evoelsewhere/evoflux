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

**When NOT to use:** for target or base source code itself — those are ordinary git repos with their own conventions. Also not for session-scoped scratch notes that don't need to survive beyond the current turn — the KB is for durable project knowledge.

## Layout and where things go

- `aim.yaml` — project manifest: rulebook id/version, `compare_default_profile`, and which repos play which role (source, target, kb) by shared identity (remote URL or logical name), never a machine-local path. Read this first when joining.
- `modules/<module>/<unit>.md` — one file per migration unit, namespaced by module so multi-repo estates don't collide.
- `inventory/units.md` — the human-readable inventory table the appraiser maintains (one row per unit: kind, wave, complexity, deps).
- `business-rules/BR-<MOD>-####.md` — one rule per file, `status: candidate` until an SME confirms it. Never cite a candidate as confirmed.
- `data-dictionary/`, `interfaces/` — shared reference material, written once and updated in place, not duplicated per unit.
- `target-conventions.md`, `ui-conventions.md` — project-level decisions made once by `aim-target-architect`, cited by every mapping.
- `mapping/<unit>.md`, `decisions/ADR-###.md` — per-unit target designs and ADRs for anything deviating from the obvious mapping or from legacy behavior.
- `golden/units/<module>/<name>/cases/<case-set>/` — golden-master cases (inputs + `expected/` outputs + `meta.yaml` provenance).
- `runs/<module>/<name>/<run-id>/report.{json,md}` — compare reports; `aim_compare` writes them here automatically.
- `.aim-actuals/<module>/<name>/<case-set>/` — target-side outputs waiting to be compared (gitignored working area; the default `actual_dir` of `aim_compare`).

## The unit frontmatter contract (system of record)

The frontmatter of `modules/<module>/<unit>.md` IS the unit's live state — the `aim_units` DB table is only a local index rebuilt from it (the Reindex button / reindex service re-derives rows after a `git pull`). Exact fields:

```yaml
kind: program            # required — from the rulebook manifest's unit_kinds
phase: inventory         # inventory|understood|designed|converted|equivalent|cutover
wave: 0                  # int or absent
assignee: hung           # claim marker, or absent
source_paths: [cbl/PAY01.cbl]
target_paths: [src/main/java/.../Pay01.java]
depends_on: [core-batch/DATEUTIL]   # unit keys, 'module/name'
complexity: { score: medium, loc: 812, indicators: [sql, file-io] }
```

**Update state through the `aim_units` tool, not by hand-editing frontmatter** — `action=set_phase` merges only the fields you pass and preserves the doc body, then mirrors to the index in the same call. Hand-edit only the body (the prose below the frontmatter). If you pulled someone else's KB commits, run reindex so the local table catches up.

## Contribution conventions (multiple people, one repo)

- **Claim a unit before working on it** — `aim_units action=set_phase unit=... assignee=<you>`; one commit, visible to everyone after their next pull.
- **Prefix IDs by module** (`BR-<MOD>-####` and any other shared ID space) so parallel work never collides.
- **Confirmation is a PR review**, not a chat message — an SME confirming a rule or an architect approving `ui-conventions.md` reviews the actual file change, so the audit trail is the git history itself.
- **Pull before you plan, push when you're done** — anything only in your working copy hasn't happened yet from the team's point of view.

## Verification

Before writing to the KB: does this belong in an existing file (update in place) or a new one following the naming above? Does every rule or decision you cite actually have `status: confirmed` (or an approved ADR)? Are you about to duplicate a project-level convention into a per-unit file instead of citing the shared doc? If you changed state, did it go through `aim_units` so the frontmatter and the index moved together?
