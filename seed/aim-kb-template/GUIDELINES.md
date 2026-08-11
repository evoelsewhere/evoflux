# AIM KB operating guidelines

## Purpose

The KB is not a scratchpad. It is the reviewable evidence trail that connects:

```text
legacy source -> understood behavior -> confirmed rule -> target mapping
              -> target revision -> verification -> compare -> cutover
```

Chat transcripts and local database rows are projections or debug context. The
files in this repository are the durable project record.

## Repository ownership

- `aim.yaml` identifies the rulebook and source/target repositories.
- `modules/` owns migration-unit documentation and current unit state.
- `business-rules/` owns one business rule per file.
- `mapping/` owns approved target designs and verification commands.
- `golden/` owns trusted inputs, expected outputs, and provenance.
- `runs/` owns immutable run metadata and reports.
- `state/` is generated for transitions, claims/evidence projections,
  traceability links, reconciliation records, and cutover checklists.
- `rulebook/` owns this engagement's pinned stack-specific content.

## State changes

Never hand-edit a unit phase to move work forward. AIM workflow tool nodes own
phase transitions and write append-only evidence references under `state/`.

For a legacy KB created before state schema 2, use Mission Control's explicit
**Reconcile state** action. It records an accepted baseline; it does not invent
missing history.

## Unit documents

Unit paths are `modules/<module>/<unit>.md`. Frontmatter is machine-readable;
the body is the human explanation. Keep these fields stable:

```yaml
kind: program
phase: inventory
wave: 0
assignee: null
source_paths: []
target_paths: []
depends_on: []
complexity: {}
revision: 0
last_transition_id: null
```

Document purpose, control flow, interfaces, side effects, error behavior, and
ambiguities. Dependencies must be understood before their callers.

## Business rules

Use one file per rule: `business-rules/BR-<MODULE>-####.md`. A rule remains
`candidate` until an SME confirms it through the project's review process.
Mappings must not silently treat candidate rules as approved requirements.

Every accepted difference must cite a confirmed rule or an ADR.

## Target design and verification

Store target mappings at `mapping/<module>/<unit>.md`. Conversion verification
is deterministic: provide one of the supported command files, preferably:

```text
mapping/<module>/<unit>.verify.command
```

The command runs from the target repository with these environment variables:

- `AIM_UNIT`
- `AIM_KB_ROOT`
- `AIM_TARGET_ROOT`
- `AIM_WORKFLOW_EXECUTION_ID`

Exit non-zero on failure. Do not hide failed checks in log text.

## Golden cases

Golden cases live at:

```text
golden/units/<module>/<unit>/cases/<case-set>/
  input/
  expected/
  meta.yaml
  legacy.command
  target.command
```

`meta.yaml` must declare honest provenance: `captured`, `prod_log_replay`, or
`synthesized`. Synthesized expected output requires `sme_sign_off` before AIM
will use it for certification.

Commands receive portable `AIM_*` environment variables from the rulebook
runner adapter and must produce at least one output file.

## Rulebook changes

Read [rulebook/GUIDELINES.md](rulebook/GUIDELINES.md) before modifying
stack-specific content. Treat a project rulebook change like a code change:

1. explain the project requirement the change addresses;
2. bump the project rulebook version when behavior changes;
3. review mappings, canonicalizers, runners, and overlays together;
4. rerun affected golden cases;
5. commit the rulebook change with its reports and ADR where applicable.

EvoFlux never replaces or upgrades this rulebook from outside the KB.

## Collaboration

- Claim work through AIM; `assignee` text alone is not a realtime lock.
- Use a shared database when several EvoFlux instances need atomic claims.
- Pull before starting work and push KB artifacts at workflow boundaries.
- Resolve conflicts as project decisions. Do not overwrite another member's
  unit state to make the board look current.
- Keep raw actuals under `.aim-actuals/`; they are reproducible and ignored.

## Cutover

Equivalence is necessary but not sufficient. A wave cannot cut over until all
units are equivalent or already cut over and the file-backed checklist confirms
deployment, data reconciliation, rollback, monitoring, and an approver.

## Review checklist

- Is every advanced unit backed by a transition event?
- Do mappings cite confirmed rules and target conventions?
- Do conversion attempts have deterministic verification evidence?
- Are golden provenance and canonicalizer profiles explicit?
- Can run/link projections be rebuilt from the KB?
- Are accepted differences cited and human-reviewed?
- Is the active rulebook committed in `rulebook/`?