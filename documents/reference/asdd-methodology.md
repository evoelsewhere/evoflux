# ASDD — Agent Specification-Driven Development

Status: implemented

Name: **ASDD — Agent Specification-Driven Development**. Product surface:
**Agent Spec-Driven**. This page is normative: where it and any other document
disagree about the lifecycle, this one wins.

ASDD is two established ideas joined at one seam. **Spec-Driven Development**
says an executable, version-controlled specification — not the code — is the
single source of truth. **Agent-Driven Development** says agent work is
structured into phases with defined inputs, gates and an execution log, so a
result is reproducible rather than lucky. ASDD keeps the specification in the
repository, and runs the agent phases against it.

## The one rule everything else follows from

**A change lives in the repository.**

Not in a database row, not in a chat session, not in a hash someone has to
restate. A change is a directory of Markdown; its phase is a field in that
directory's `proposal.md`; its contract is the delta under
`specs/<capability>/spec.md`; its identity is the directory's name.

This is what makes the rest of the method work. A reviewer reads a change with
`git diff`. Two chats can work on one change, and one chat can move between
changes. A run that dies halfway is recovered by editing a file. Nothing can
fail for a reason the user cannot see in `git status`.

## Layout

```text
<data_directory>/                     # `.evoflux/asdd/config.json` names it
├── project.md                        # this repository's context and rules
├── architecture/                     # process, storage, concurrency, trust
│   └── decisions/NNNN-<slug>.md      # ADR-style durable decisions
├── specs/
│   └── <capability>/spec.md          # the behavior the system guarantees now
├── reference/                        # exact API, configuration, schema, CLI
├── analysis/YYYY-MM-DD-<topic>.md    # dated investigations, never normative
└── changes/
    ├── <change-id>/
    │   ├── proposal.md               # why and what; front matter holds status
    │   ├── design.md                 # cross_layer and critical risk only
    │   ├── tasks.md                  # the checklist agents execute
    │   ├── specs/<capability>/spec.md  # ADDED / MODIFIED / REMOVED Requirements
    │   └── evidence/<id>.md          # what was run, and what it showed
    └── archive/YYYY-MM-DD-<change-id>/
```

Every directory carries a `README.md` stating what belongs in it, what does
not, and how it changes — written where an agent is deciding where to put a
page rather than in a method document it may not have open.

Only `specs/` waits for the archive, because only `specs/` is approved as a
delta. `architecture/`, `architecture/decisions/` and `reference/` are written
by the change that makes them true, in the same diff as the code; `analysis/`
is dated and never corrected in place.

## The grammar

A capability's `spec.md`:

```markdown
## Purpose

One paragraph: what this capability is for.

## Requirements

### Requirement: Slug identity

A change SHALL be identified by its directory name.

#### Scenario: Two chats open the same change

- **WHEN** two Coding chats point at `add-user-auth`
- **THEN** both read and write the same change folder
```

A change's delta for that capability uses the same shape under
`## ADDED Requirements`, `## MODIFIED Requirements` and
`## REMOVED Requirements`, and says only what changes.

Three constraints the archive step enforces:

- `MODIFIED` and `REMOVED` name a requirement the current spec contains,
  character for character.
- `ADDED` names one it does not.
- Every requirement carries at least one scenario with a **WHEN** and a
  **THEN**.

A rename is a `REMOVED` plus an `ADDED`. Nothing models identity across a name
change, because nothing needs to.

## Lifecycle

| `status` | Gate | Who acts |
|---|---|---|
| `drafting` | — | agent writes `proposal.md` |
| `proposed` | **Approve proposal** | user |
| `specifying` | — | agent writes the deltas |
| `specified` | **Approve specs** | user |
| `designing` | — | agent writes `design.md` (risk-gated) |
| `designed` | **Approve design** | user |
| `tasking` | — | agent writes `tasks.md` |
| `tasked` | **Approve tasks** | user |
| `implementing` | — | agent executes tasks |
| `verifying` | — | agent records evidence |
| `ready` | **Archive** | user |
| `archived` | — | — |

Approving tasks is what authorizes product-file changes. Archiving folds the
deltas into `specs/` and retires the folder; it is undone only by another
change.

`risk: trivial` and `risk: standard` skip design. `risk: cross_layer` and
`risk: critical` require a design document and a recorded independent review.

The six ADD phases map onto this directly: SCOPE is the proposal, FRAME is the
deltas, CONSTRAIN is design plus tasks, EXECUTE is implementation, VERIFY is
evidence, CONSOLIDATE is the archive.

## Rules

The normative rules ship with the method and are installed at
`.evoflux/asdd/RULES.md`, beside a `TEMPLATE.md` per phase Skill that states
exactly what that phase produces. In summary:

1. The repository is the source of truth.
2. Identity is a slug, and only a slug.
3. Specification precedes code.
4. Fix the spec, not the code — before approval; after approval, the reverse.
5. Humans own the gates, and autopilot does not forge their signature.
6. Under autopilot, stopping is a first-class outcome.
7. Ask; do not defer.
8. A delta says what changes, not everything.
9. Every requirement carries at least one scenario.
10. Reuse a capability before coining one.
11. Evidence before ready — one page per requirement, not one per change.
12. Review is mandatory; independence scales with risk.
13. Archive is the only way a spec changes.
14. Correct a contradiction; do not route around it.
15. Preserve trust boundaries.
16. Do not migrate knowledge implicitly.

## Autopilot

By default a change stops at every gate and waits for a person. Setting
`autopilot: true` in `proposal.md` hands that judgment to the agent: it carries
the change to the next phase when it would have told you the artifact was fine,
and stops when it would not.

Two front-matter fields keep that honest.

```yaml
autopilot: true
approvals:
  proposal: '2026-09-17T08:00:00Z'   # a person signed this
  specs: null
auto_approvals:
  specs: '2026-09-17T08:05:00Z'      # autopilot cleared this
hold:
  gate: design
  reason: The delta removes a requirement two other capabilities cite.
  raised: '2026-09-17T08:10:00Z'
```

`approvals` is the user's signature and only the approve endpoint writes it.
`auto_approvals` is what autopilot cleared on its own judgment. Both open a
gate; only one is a signature, and the panel draws them differently so a
reader deciding whether to archive can tell which is which. Separating them is
what stops an agent from having to write into the map it is told not to touch
in order to make progress.

`hold` is how an agent says a gate needs a person after all. It names the gate
and the reason, leaves `status` where it is, and the panel shows it above
everything else on the rail. Approving clears it. A hold suspends autopilot
everywhere, not only at the gate it was raised on.

Autopilot carries the build phases too. Implementation and verification are not
gates — there is nothing to sign — so the agent simply finishes the phase and
sets `status` to the next one: `implementing` to `verifying` once every task is
ticked, `verifying` to `ready` once every approved requirement has passing
evidence. The rail leads with **Continue** throughout and keeps the manual
actions beside it, because autopilot is a default rather than a lock.

It stops at `ready`. Archiving folds the deltas into the capability specs and is
undone only by another change, so it stays a click a person makes at every risk
tier.

Two gates are never autopilot's to give even in principle. A `cross_layer` or
`critical` change keeps `design` and the archive for the user — those are exactly the tiers that
exist to force a person to look, and `archive_blockers` refuses a change whose
design was cleared by autopilot rather than signed. The policy is one table,
`AUTOPILOT_HUMAN_ONLY` in `app/services/asdd_lifecycle.py`.

## What ASDD deliberately does not have

**No content hashes.** The previous method required every operation to restate a
sha256 of current state — to accept a revision, to delegate a mission, to record
evidence. It made concurrent edits detectable, and it made ordinary work fail
with conflicts the user could not act on. Verification still content-addresses
its own result cache (`artifact_hash`), but nothing asks a person or an agent to
carry a hash.

**No session binding.** A run used to be owned by one chat, enforced by a foreign
key and a unique index. One chat could hold one run; resuming elsewhere needed a
forced rebind. Now a chat is a place work happens, and any chat can run any
phase of any change.

**No typed submission tools.** An agent writes Markdown with the ordinary file
tools. There is no `submit_specification` call whose payload could disagree with
what is on disk.

**No optimistic concurrency.** Two agents writing one file will overwrite each
other; a per-repository lock serializes the product's own writes, and `git diff`
shows what happened. This is the trade the method accepts in exchange for the
three properties above.

## Hand editing

Editing `proposal.md` by hand is legitimate — the file is the source of truth. If
the `status` written there disagrees with what the folder contains, the product
reports the contradiction on the change's action rail and changes neither side.
Fixing it is a repository edit, like any other.

## Open questions

A design's `## Open questions` section means unresolved, not deferred. The
design gate refuses a `design.md` that still lists any, and the blocker names
them.

The phase is expected to resolve them with `ask_user` — batched, each with a
recommendation — and record the answers under `## Decisions` in the user's own
terms. Anything the user puts out of scope leaves the design entirely and
becomes a follow-up change named in the proposal's non-goals. Under
`autopilot: true`, an unanswered question is a `hold`, never a guess written
down as though it had been decided.

## Skills

Setup installs six phase Skills into `.evoflux/skills/`:

| Skill | Phase | Produces |
|---|---|---|
| `asdd-propose` | scope | `proposal.md` |
| `asdd-specify` | frame | `specs/<capability>/spec.md` |
| `asdd-plan` | constrain | `design.md`, `tasks.md` |
| `asdd-implement` | execute | the approved tasks |
| `asdd-verify` | verify | `evidence/<id>.md` |
| `asdd-archive` | consolidate | an archive readiness report |

## Prior art

The file model — `specs/` as current truth, `changes/` as deltas, an archive
that folds one into the other — follows [OpenSpec](https://github.com/Fission-AI/OpenSpec).
The phase cycle and the execution-log discipline follow
[Agent-Driven Development](https://github.com/Pyro-IV/Agent-Driven-Development).
The UI-driven rail and the human approval gates are EvoFlux's own.
