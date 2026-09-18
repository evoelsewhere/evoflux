---
name: asdd-verify
description: Review an implemented ASDD change against its approved requirements and record the evidence that decides whether it is ready. Use when a change is in `implementing` or `verifying`; do not use for proposals, specification, planning or archiving.
---

# Verify an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and `project.md`
in the resolved `data_directory`. Read the change's `proposal.md`, every
`specs/<capability>/spec.md` under the change, `tasks.md`, `design.md` when
present, and the existing pages under `evidence/`.

## State gate

Work when `proposal.md` reads `status: implementing` or `status: verifying`.
Verification is read-only for product files: you may run commands and read
anything, but you do not fix what you find. Reporting a defect and repairing it
in the same pass is how a review ends up reviewing itself.

## Verify against requirements, not against the diff

1. Take each requirement from each delta, in order. For every `#### Scenario:`,
   establish whether the implemented system actually produces the **THEN** given
   the **WHEN** — by running a check, reading the code path end to end, or
   exercising it directly.
2. Cite what you looked at: repository-qualified paths, the command you ran, the
   test that covers it. A verdict with no citation is an opinion.
3. Report `passed`, `failed` or `inconclusive` per requirement. `inconclusive`
   is a real and useful answer; recording a guess as `passed` is not.
4. Inspect the integrated result, not the handoff prose that describes it.

## Record evidence

Write one page per check under `changes/<change-id>/evidence/<id>.md`:

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

- `kind` is `machine` for a command result, `review` for a human-or-agent reading
  of the work, `manual` for something a person exercised by hand.
- `result` is `passed`, `failed` or `inconclusive`.
- `requirement` names the requirement, exactly as the delta spells it. Omit it
  only for a check that covers the change as a whole.

A `cross_layer` or `critical` change needs a `kind: review` page with
`result: passed` written by someone who did not implement the work. Record who
reviewed it in the body.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Trace each requirement to the code that implements it: `action="search"` to
  expose the identifier, then `action="definition"` and `action="callers"` to
  establish that the **WHEN** really reaches the **THEN**.
- Use `action="references"` to find the tests that already cover a scenario
  before writing a verdict of `inconclusive`.
- A verdict cites what you read or ran. An uncited verdict is an opinion.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

When every requirement has a verdict, set `status: verifying` if it is not
already, and stop. Report the per-requirement verdicts, the evidence pages you
wrote, and exactly what remains before this change could be archived. Do not fix
findings, do not set `status: ready`, and do not archive — those are the user's.
