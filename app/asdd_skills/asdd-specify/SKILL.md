---
name: asdd-specify
description: Write the capability deltas for an approved ASDD proposal — the ADDED, MODIFIED and REMOVED requirements that state what the system will guarantee. Use when a change is in `specifying` or `specified`; do not use for proposals, planning, implementation or verification.
---

# Specify an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and `project.md`
in the resolved `data_directory`. Read the approved
`changes/<change-id>/proposal.md` and, for every capability it names, the
current `specs/<capability>/spec.md` when one exists. Repository files are the
source of truth.

`TEMPLATE.md`, beside this file, is the exact shape of a delta and what gets one rejected.

Work only when `proposal.md` reads `status: specifying` or `status: specified`,
and only when `approvals.proposal` or `auto_approvals.proposal` carries a
timestamp. Without one of those the scope is still moving and any requirement
you write is guesswork.

With `autopilot: true`, you may clear the specs gate the same way once every
capability the proposal names has a delta and every requirement carries a
scenario: write `auto_approvals.specs` and set the next status — `designing`
for `cross_layer` and `critical`, `tasking` otherwise. Never write `approvals`.
Write a `hold` naming `gate: specs` instead whenever a delta removes or
weakens a requirement other capabilities rely on, or the behaviour you had to
invent is not clearly implied by the proposal.

## Write one delta per capability

For each capability in the proposal's `capabilities`, write
`changes/<change-id>/specs/<capability>/spec.md`. A delta states only what
changes:

```markdown
## ADDED Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at `add-user-auth`
- **THEN** both read and write the same change folder

## MODIFIED Requirements

### Requirement: <the exact name in the current spec>

<the full replacement statement, not a description of the edit>

#### Scenario: <what is exercised>

- **WHEN** <trigger>
- **THEN** <observable result>

## REMOVED Requirements

### Requirement: <the exact name in the current spec>
```

Rules the archive step will enforce, so honor them now:

- A `MODIFIED` or `REMOVED` heading must match a requirement name in the current
  spec **character for character**. If it does not exist, it belongs under
  `ADDED`.
- An `ADDED` heading must not match a name the current spec already has.
- A rename is a `REMOVED` of the old name plus an `ADDED` of the new one.
- The same requirement name appears in exactly one section.
- Omit a section entirely rather than leaving it empty.

## Write requirements that can be verified

- One requirement states one obligation, in the form `The system SHALL <observable
  behavior>`. Behavior an outside observer cannot detect is not a requirement.
- Every requirement carries at least one `#### Scenario:` with a `- **WHEN**`
  and a `- **THEN**` bullet. Use `- **AND**` for additional conditions.
- Cover the scenarios this repository's `project.md` says must always be
  covered — commonly migration, rollback and failure for anything operational.
- Name domain vocabulary exactly as the repository uses it. A requirement that
  invents a synonym cannot be traced to the code that implements it.

Do not restate requirements the change leaves alone. A delta that repeats the
whole spec hides the change inside its own context, which is the one thing this
format exists to prevent.

## Tools

- `code_context` — read the code a requirement will constrain before writing
  it; see `references/code-context-contract.md`.
- `ask_user` — when a behaviour has two defensible contracts and the proposal
  does not choose. Writing a requirement you guessed at is worse than asking:
  the whole phase exists to remove that guess.
- `shell` — read-only: read the current `specs/<capability>/spec.md` before a
  `MODIFIED` or `REMOVED`, so the name you cite is the name that exists.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Ground each requirement in a real declaration: one `action="search"` to expose
  the identifier, then `action="definition"` on it. A requirement written from a
  filename survives no review.
- Use `action="callers"` to learn who depends on the behavior you are
  contracting; those callers are where a scenario has to hold.
- Name domain vocabulary as the code spells it, so a requirement can be traced
  to the symbol that implements it.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

When every named capability has a delta, set `status: specified` in
`proposal.md` and stop. Report each capability, the requirements added, modified
and removed, and anything in the proposal you could not turn into a verifiable
requirement. Do not write design or tasks, and do not touch product files.
