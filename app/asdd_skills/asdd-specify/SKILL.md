---
name: asdd-specify
description: Write the capability deltas for an approved ASDD proposal — the ADDED, MODIFIED and REMOVED requirements that state what the system will guarantee. Use when a change is in `specifying` or `specified`; do not use for proposals, planning, implementation or verification.
---

# Specify an ASDD change

You are writing **what the system will guarantee**, as requirements someone can
verify. Not how it will be built — that is `asdd-plan` — and not how it is
called, which is `reference/`.

**IMPORTANT: a delta says what changes, nothing else.** You write
`changes/<change-id>/specs/<capability>/spec.md`, one per capability the
proposal names. Never edit a capability's canonical `specs/<capability>/spec.md`
— archiving folds your delta into it, and that is the only way it changes.

The archive step re-checks everything below against the current spec. A name
that does not match then is a change nobody can fold, so honor it now.

---

## Read before you write

1. `.evoflux/asdd/config.json` — where the catalogue lives.
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. `<data_directory>/project.md` — domain vocabulary, and the scenarios this
   repository says must always be covered.
4. `changes/<change-id>/proposal.md` — the approved scope. It is the brief.
5. `specs/<capability>/spec.md` for **every** capability the proposal names —
   the exact current text. You are writing against it, not beside it.

---

## Check the gate before you spend a turn

| Condition | What to do |
|---|---|
| `status: specifying` | Write the deltas. The normal case. |
| `status: specified` | Revise them, and say what changed. |
| No `approvals.proposal` **and** no `auto_approvals.proposal` | **Stop.** The scope is still moving; every requirement you write would be guesswork. |
| `status: drafting` or `proposed` | **Stop.** The proposal phase is open, not this one. |
| anything past `designing` | **Stop.** The specs were approved; a new contract is a new change. |

---

## One delta per capability

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

`TEMPLATE.md`, beside this file, is the full shape and the rejection list.

### Naming rules the archive enforces

| Situation | Where it goes |
|---|---|
| The name exists in the current spec, and its obligation changes | `## MODIFIED` — heading matched **character for character** |
| The name does not exist in the current spec | `## ADDED` |
| The obligation goes away entirely | `## REMOVED` — heading matched exactly |
| A requirement is renamed | `## REMOVED` the old name **and** `## ADDED` the new one |

One name appears in exactly one section. Omit a section rather than leaving it
empty.

---

## What makes a requirement verifiable

- **One obligation each**, written `The system SHALL <observable behavior>`.
  Behavior an outside observer cannot detect is not a requirement.
- **At least one `#### Scenario:`**, with a `- **WHEN**` and a `- **THEN**`.
  Use `- **AND**` for extra conditions. A requirement with no scenario is an
  intention, and the gate refuses it.
- **The repository's own words.** Name domain vocabulary as the code spells it;
  a requirement that invents a synonym cannot be traced to what implements it.
- **The scenarios `project.md` demands** — commonly migration, rollback and
  failure for anything operational.

### Behavior, not surface

A requirement says what is guaranteed; the field names, flags, defaults, status
codes and payload shapes a caller types belong in `reference/`. Freezing a wire
format into a behavioral contract makes two documents that drift with nothing
saying which one is wrong.

```markdown
THEN the request is rejected and the reason names the offending field   ← yes
THEN the API returns 422 with {"detail": "capability_required"}         ← no
```

When the change alters such a surface, the plan carries a task to update the
reference page in this same change. See rule 18.

### Do not restate what you are not changing

A delta that repeats the whole spec hides the change inside its own context.
That is the single thing this format exists to prevent.

---

## Autopilot

With `autopilot: true` you may clear this gate once every named capability has
a delta and every requirement carries a scenario:

- **Confident** — write `auto_approvals.specs` (never `approvals`) and set the
  next status: `designing` for `cross_layer` and `critical`, `tasking`
  otherwise.
- **Write a `hold` naming `gate: specs`** when a delta removes or weakens a
  requirement other capabilities rely on, or when the behavior you had to
  invent is not clearly implied by the proposal. Leave `status` where it is and
  say so in the chat.

Set the next status and stop there. The product reads it and starts the next
phase itself — that is what autopilot means now, so there is no hop for you to
make and no Continue for the user to click. A `hold` is what ends the chain.

---

## Tools

- `code_context` — ground each requirement in a real declaration: one
  `action="search"` to expose the identifier, then `action="definition"` on it;
  `action="callers"` to find who depends on the behavior you are contracting,
  because that is where a scenario has to hold. Depth 1 unless the question is
  transitive. Never bulk scan. `references/code-context-contract.md` is
  normative and carries the full rules.
- `ask_user` — when a behavior has two defensible contracts and the proposal
  chooses neither. Asking beats writing a requirement you guessed at; removing
  that guess is the whole point of this phase.
- `shell` — read-only: read the current `specs/<capability>/spec.md` before any
  `MODIFIED` or `REMOVED`, so the name you cite is the name that exists.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them.

---

## Stop, and report

Set `status: specified` when every named capability has a delta, then stop:

```text
add-note-search — specified.

`note-search` (new): 3 added — Find a note by title, Search is
case-insensitive, Empty query returns nothing.

`note-storage`: 1 modified — Note index is maintained. Kept the name
character for character; the obligation now covers deletes.

Could not specify: what "recently opened" means for ranking. The proposal
implies recency but nothing defines the window, so it is not in the delta.
```

Name each capability, what was added, modified and removed, and anything in the
proposal you could not turn into a verifiable requirement. Then stop: no
design, no tasks, no product files.

---

## Guardrails

- **Don't edit a canonical spec.** `specs/<capability>/spec.md` changes by
  archiving a delta, never by hand — rule 13.
- **Don't guess a name.** Copy `MODIFIED` and `REMOVED` headings out of the
  current spec; the archive compares them character for character.
- **Don't write a requirement with no scenario.** The gate refuses it, and it
  would not be verifiable anyway.
- **Don't put a wire format in a scenario.** That belongs in `reference/`.
- **Don't restate unchanged requirements** to make the delta look complete.
- **Don't write `approvals`.** `auto_approvals` is yours under autopilot; the
  other map belongs to a person.
