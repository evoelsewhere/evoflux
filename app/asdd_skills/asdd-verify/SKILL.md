---
name: asdd-verify
description: Review an implemented ASDD change against its approved requirements and record the evidence that decides whether it is ready. Use when a change is in `implementing` or `verifying`; do not use for proposals, specification, planning or archiving.
---

# Verify an ASDD change

You are deciding, per requirement, whether the implemented system does what the
approved delta says it does — and leaving the evidence that shows it.

**IMPORTANT: verification does not fix what it finds.** You may run anything and
read anything; you do not edit product files. A pass that repaired its own
finding is a review reviewing itself. Report the defect and let
`asdd-implement` take it.

**A verdict with no citation is an opinion.** Every requirement gets `passed`,
`failed` or `inconclusive`, and each one names the command that ran or the path
you read.

---

## Read before you verify

1. `.evoflux/asdd/config.json` — where the catalogue lives.
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. `<data_directory>/project.md` — the checks this repository trusts.
4. Every `changes/<change-id>/specs/<capability>/spec.md` — the requirements
   you are verifying. They are the subject, not the diff.
5. `proposal.md`, `tasks.md`, `design.md` when present, and the existing pages
   under `evidence/`.

`TEMPLATE.md`, beside this file, is the exact shape of an evidence page and of
the report.

---

## Check the gate

| Condition | What to do |
|---|---|
| `status: implementing` | Verify. Implementation may still be running; say which requirements you could not reach yet. |
| `status: verifying` | Verify. The normal case. |
| earlier than `implementing` | **Stop.** There is nothing built to verify. |
| `status: ready` or `archived` | **Stop.** A verdict already stands; reopening it needs a new change. |

---

## Verify against requirements, not against the diff

1. **Take each requirement from each delta, in order.** For every
   `#### Scenario:`, establish whether the system produces the **THEN** given
   the **WHEN** — by running a check, reading the code path end to end, or
   exercising it directly.
2. **Cite what you looked at**: repository-qualified paths, the command you
   ran, the test that covers it.
3. **Record one verdict per requirement.**

| Verdict | When |
|---|---|
| `passed` | You exercised it and it held |
| `failed` | You exercised it and it did not |
| `inconclusive` | You could not exercise it. A real and useful answer — recording a guess as `passed` is not. |

4. **Inspect the integrated result**, not the handoff prose describing it.

---

## Record evidence

One page per check, at `changes/<change-id>/evidence/<id>.md`:

```markdown
---
id: pytest-services
kind: machine
result: passed
requirement: Slug identity
recorded: 2026-09-16T10:04:00Z
---

`uv run python -m pytest --no-cov -q tests/services` — 214 passed.

<the part of the output that shows the outcome>
```

- `kind` — `machine` for a command result, `review` for a human-or-agent
  reading of the work, `manual` for something a person exercised by hand.
- `requirement` — exactly as the delta spells it. Omit only for a check that
  covers the change as a whole.

A `cross_layer` or `critical` change needs a `kind: review` page with
`result: passed`, **written by someone who did not implement the work**, naming
who reviewed it.

### Evidence, and what outlives it

Evidence belongs to the change and retires with it into the archive. An
investigation still worth reading a year from now — a benchmark with numbers, a
comparison, a reproduction — is *also* a dated page under `analysis/`, cited
from the evidence rather than duplicated into it.

---

## The documentation check is a real check

Verification is the last honest moment to look at the pages the change owed. If
a task changed a surface and `reference/` still describes the old one, that is
a **failed** verification, not a documentation chore — say so with the same
weight as a failing test.

| Owed by the change | Verify |
|---|---|
| A changed endpoint, config key, schema, event or CLI flag | `reference/` matches what shipped |
| A moved boundary | the `architecture/` page says so |
| A decision expensive to reverse | an ADR exists under `architecture/decisions/` |

---

## Tools

- `shell` — run the repository's checks. `kind: machine` evidence means a
  command actually ran; paste the part of the output that shows the outcome.
- `python` — for a check the repository has no command for. Write it into the
  evidence page so it can be re-run.
- `code_context` — trace each requirement to the code that implements it:
  `action="search"` to expose the identifier, then `action="definition"` and
  `action="callers"` to establish that the **WHEN** really reaches the
  **THEN**; `action="references"` to find the tests that already cover a
  scenario before you write `inconclusive`. Never bulk scan.
  `references/code-context-contract.md` is normative and carries the full rules.
- `lsp_diagnostics` — a change that leaves new diagnostics is not verified.
- `ask_user` — when a scenario cannot be exercised without something only the
  user can supply: a credential, an environment, an acceptable trade-off.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them.

---

## Stop, and report

When every requirement has a verdict, set `status: verifying` if it is not
already, and stop:

```text
add-note-search — verified, 1 blocker.

passed  Find a note by title          tests/notes/test_search.py, 24 passed
passed  Search is case-insensitive    same run
failed  Empty query returns nothing   CLI prints the full list — app/cli/notes.py:88
inconc. Rank by recency               no definition of the window; nothing to exercise

Evidence: 4 pages under evidence/. reference/api.md matches the shipped
parameter; ADR 0007 is present.

Before this can be archived: the CLI path, and a decision on the recency
window.
```

Give the per-requirement verdicts, the evidence pages you wrote, and exactly
what remains before the change could be archived. Never fix a finding here, and
never archive.

---

## Autopilot

Set `status: ready` yourself only when every approved requirement has a
`result: passed` page and — at `cross_layer` and `critical` — an independent
`kind: review` page that passed.

Anything else is a `hold` naming `gate: verifying`: a `failed` result, an
`inconclusive` verdict standing between the change and `ready`, or a
requirement with no evidence you could honestly write. **Reporting a
requirement as verified because the code looks right is the failure this phase
exists to prevent.**

---

## Guardrails

- **Don't fix what you find.** Report it; implementation owns the repair.
- **Don't verify the diff.** The requirement is the subject; the diff is one
  piece of evidence about it.
- **Don't write an uncited verdict.** Name the command or the path.
- **Don't round `inconclusive` up to `passed`** because everything else passed.
- **Don't let a stale `reference/` page through.** It is a failure, not a
  chore.
- **Don't archive.** That folds deltas into the catalogue and is the user's.
