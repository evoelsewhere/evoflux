---
name: asdd-archive
description: Check that a verified ASDD change is safe to fold into the capability specs, and report what archiving will change. Use when a change is in `ready`; do not use for proposals, specification, planning, implementation or verification.
---

# Archive an ASDD change

You are establishing that the fold will be correct, and saying exactly what it
will produce. You are not performing it.

**IMPORTANT: this phase writes nothing to the catalogue.** EvoFlux folds the
deltas and moves the folder when the user clicks archive. You do not edit a
capability spec, do not move the change folder, do not set `status: archived`,
and do not touch `approvals`.

The one exception is a gap you find below: a durable page this change owed but
never wrote. Write that, in this change, before you report.

---

## What archiving does

Folds each `changes/<change-id>/specs/<capability>/spec.md` into the
catalogue's `specs/<capability>/spec.md`, then moves the change folder to
`changes/archive/YYYY-MM-DD-<change-id>/`.

It is the only way a capability spec changes, and nothing undoes it except
another change. That is why this phase exists: everything below is cheaper to
check now than to reverse later.

---

## Read before you judge

1. `.evoflux/asdd/config.json`, `.evoflux/asdd/RULES.md`,
   `<data_directory>/project.md`.
2. `changes/<change-id>/proposal.md` — the gates, the tier, the scope.
3. Every delta under the change, **and the current catalogue spec for each of
   those capabilities**. The fold compares the two; so do you.
4. Every page under `evidence/`.
5. `design.md` when present — its `## Decisions` is the list you check against
   `architecture/decisions/`.

---

## Check the gate

| Condition | What to do |
|---|---|
| `status: ready` | Check and report. The normal case. |
| `status: verifying` | **Stop.** Verification has not returned a verdict; ask for `asdd-verify`. |
| earlier | **Stop.** Name the phase that is actually open. |
| `status: archived` | **Stop.** Already folded; the change is history. |

---

## Check before the fold

1. **Names resolve.** Every `MODIFIED` and `REMOVED` heading matches a
   requirement in the current catalogue spec **character for character**. Every
   `ADDED` heading matches nothing there. A capability with no spec yet is
   normal — the fold creates it.
2. **Structure holds.** Every requirement has a statement and at least one
   scenario with a **WHEN** and a **THEN**.
3. **Evidence covers the contract.** Every requirement in every delta has a
   verdict, and none is `failed`. Say which are `inconclusive` and why that is
   acceptable — or that it is not.
4. **Gates are stamped.** `approvals` or `auto_approvals` carries a timestamp
   for proposal, specs and tasks, plus design at `cross_layer` and `critical`.
   Say which a person signed and which autopilot cleared. **At those two tiers
   the design must be `approvals.design` — the user's — and there must be a
   passing independent `kind: review` page.**
5. **Tasks are settled.** Every task is ticked, or an unticked one carries a
   note saying why it is not needed.

---

## The catalogue outside `specs/`

The fold covers `specs/` and nothing else. Once the folder moves, a page this
change owed but never wrote reads as though nobody ever needed it — so confirm
these four, and **write what is missing before you report**:

| Check | Where |
|---|---|
| Every expensive-to-reverse entry in `design.md`'s `## Decisions` exists as a numbered ADR naming this change, with its rejected alternative | `architecture/decisions/` |
| A moved process, storage, concurrency or trust boundary is described | `architecture/` |
| A changed endpoint, config key, schema, event or CLI flag matches what shipped | `reference/` |
| An investigation this change produced is dated and cited where it was used | `analysis/` |

Do not archive around a gap and open a follow-up change to write the page. The
change that made the statement true is the only one whose diff explains it.

---

## Tools

- `shell` — `git status` and `git diff --stat` on the change folder and the
  capability specs, so the report describes the tree as it is rather than as
  the change folder claims.
- `code_context` — spot-check that the merged contract still describes the
  code: one `action="search"` per requirement, then `action="definition"` on
  what it returns. A spec folded in while the behavior no longer matches is
  worse than no spec. Use `action="impact"` when a `REMOVED` requirement
  retires behavior, to name what still depends on it. Never bulk scan.
  `references/code-context-contract.md` is normative and carries the full rules.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them.

---

## Stop, and report

`TEMPLATE.md`, beside this file, is the exact shape. Say, per capability, what
the merged spec will contain, then the verdict:

```text
add-note-search — safe to archive.

note-search (new capability; the fold creates it)
  + Find a note by title
  + Search is case-insensitive
  + Empty query returns nothing

note-storage
  ~ Note index is maintained — replaces "The index is rebuilt on write",
    which no longer holds now that deletes update it incrementally
  - Full reindex on boot

Gates: proposal and specs signed by the user, tasks cleared by autopilot.
Standard tier, so no design gate.
Evidence: 4 pages, all passed.
Catalogue: ADR 0007 present, reference/api.md current.

Nothing blocks it.
```

When something does block it, replace the last line with what and why, one line
each, naming the file the user has to fix.

---

## Guardrails

- **Don't fold anything yourself.** Not a spec edit, not a folder move, not
  `status: archived`. The fold is the product's and the user starts it.
- **Don't report a gate as approved** without saying whether a person or
  autopilot cleared it.
- **Don't wave through an `inconclusive`.** Name it and say why it is
  acceptable, or say it is not.
- **Don't accept a name that nearly matches.** The fold compares character for
  character, and a near miss fails after the user has clicked.
- **Don't leave a durable page unwritten** and note it as follow-up work.
  Write it here.
