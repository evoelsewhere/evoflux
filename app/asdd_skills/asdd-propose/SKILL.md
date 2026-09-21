---
name: asdd-propose
description: Draft or redraft the proposal for an ASDD change — why it is needed, what observably changes, and which capabilities it touches. Use when a change is in `drafting` or `proposed`; do not use for specification, planning, implementation or verification.
---

# Propose an ASDD change

You are deciding **what problem this change solves and how far it reaches**.
Not how to build it, and not what the contract will say — those are
`asdd-specify` and `asdd-plan`, and they are better for your having left them
alone.

**IMPORTANT: this phase writes exactly one file** — `proposal.md`, in the
change folder you were given. No product code, no specs, no tasks, no design.
If the work seems obvious enough to just do, that feeling is what the phase
exists to catch: propose it, and the next phase will still be there.

Two things must be true when you stop, and the gate refuses without them: a
**risk tier** and the **capability slugs** this change will carry deltas for.
Everything below serves getting those two right.

---

## Read before you write

In this order, always:

1. `.evoflux/asdd/config.json` — where the catalogue lives (`data_directory`).
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. `<data_directory>/project.md` — this repository's own voice: conventions,
   what a proposal here must always state, what must not break.
4. `<data_directory>/specs/` — what the catalogue already contracts. Read this
   *before* naming a capability, never after.

The repository is the source of truth. Never reconstruct a change's state from
what was said in chat.

Your change is `<data_directory>/changes/<change-id>/`. That folder name is the
change's entire identity — no run id, no revision, no hash, ever.

---

## Check the gate before you spend a turn

| `status` in `proposal.md` | What to do |
|---|---|
| `drafting` | Write the proposal. The normal case. |
| `proposed` | Redraft it, and say what you changed and why. |
| anything later | **Stop.** The proposal was approved; editing it now invalidates a gate the user already cleared. Say so, and name the phase that is actually open. |

---

## You arrive in one of three ways

**A title and two sentences from the create form.** The common case. `## Why`
and `## What Changes` already hold the requester's own words — that is your
brief, not prose to tidy. Everything else is yours to derive.

**A conversation that got concrete.** The user thought out loud and asked to
capture it. Reread for the outcome they actually want, then treat it as the
brief above. Do not widen it while writing it down.

**A redraft.** Something was wrong: the scope, the tier, or a capability. Fix
that, leave the rest, and say in the chat which of the three it was.

---

## Decide the two things the gate needs

### Capabilities

**Reuse before you coin.** If an existing `specs/<capability>/spec.md` already
contracts the behavior this change alters, write the delta against *that*
capability. Two contracts describing one behavior is the failure mode here, and
it stays invisible until someone has to change both.

A new slug is for behavior the catalogue does not cover. When you coin one, the
proposal names the existing capabilities you considered and ruled out — that
sentence is how a reviewer checks your judgment instead of taking it.

### Risk tier

An absent `risk` is not `standard`. It means nobody has tiered this change, and
the gate refuses until someone does.

| Tier | Choose it when | It costs |
|---|---|---|
| `trivial` | One obvious edit, no contract moves | Nothing extra |
| `standard` | Ordinary feature or fix inside one layer | Nothing extra |
| `cross_layer` | Multi-repository, migration, persistence, public compatibility, concurrency | A design document and an independent review |
| `critical` | Security, data loss, trust boundaries, anything hard to reverse | The same, and the user keeps the design gate and the archive |

Do not reach for a high tier to signal that the work matters. The upper two buy
scrutiny and cost the user two extra gates: pick them when the change can hurt,
not when it is merely large.

---

## Work from evidence, not from the prompt

Read the owning source, configuration, migrations and focused tests before you
write `## Impact`. Treat code and tests as current-state evidence; treat plans,
comments and TODOs as somebody's proposal.

Then scan for the ambiguity that would change what gets built: scope, actors
and permissions, state and data, failure and recovery, concurrency, security
and privacy, compatibility, observability, and what "done" means.

Where something there is genuinely unsettled, **ask** — one concise question
with a recommendation, through `ask_user`. Do not interrogate the user about
what you could resolve by reading, and do not guess at an outcome and then
record the guess as though it were the brief.

**If reaching the problem took real work** — a benchmark, a comparison, a
reproduction nobody had managed — that work is its own page at
`analysis/YYYY-MM-DD-<topic>.md`, cited from the proposal in one line. See
`analysis/README.md` for what such a page owes. Do not swallow an investigation
into `## Why`.

---

## Write it

`TEMPLATE.md`, beside this file, is the exact shape of `proposal.md` and the
list of what gets one rejected. Read it before writing; it is what this phase
is graded on.

Set `status: proposed` **last**, once the sections are complete and both `risk`
and `capabilities` are set.

Leave `approvals` alone. Approval is the user's, and writing a timestamp there
forges a gate the product will then honor.

---

## Autopilot

With `autopilot: true` in the change's front matter you may clear this gate
yourself — but only when you would defend the scope to the user:

- **Confident** — write the timestamp under `auto_approvals.proposal` (never
  `approvals`) and set `status: specifying`.
- **Not confident** — an unclear outcome, a capability you are guessing at, a
  tier you are unsure of: write a `hold` naming `gate: proposal` and the
  reason, leave `status` where it is, and say so in the chat.

Stopping is a result. A proposal nobody should have approved costs more than a
turn spent asking.

Set the next status and stop there. The product reads it and starts the next
phase itself — that is what autopilot means now, so there is no hop for you to
make and no Continue for the user to click. A `hold` is what ends the chain.

---

## Tools

- `code_context` — the discovery tool for this phase. One `action="search"` to
  expose a declared identifier, then the exact-symbol action on it;
  `action="callers"` and `action="references"` to size `## Impact`. Depth 1
  unless the question is transitive. Never bulk scan.
  `references/code-context-contract.md` is normative and carries the full rules.
- `ask_user` — for a genuinely ambiguous outcome or tier. Batch the questions;
  give each a recommendation.
- `memory_search` — before coining a capability, check what this repository has
  already decided about the area.
- `shell` — read-only here: `git log`, `git diff`. This phase changes no file
  but the proposal.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them, and do not sweep the tree to guess the toolchain.

---

## Stop, and report

Stop after writing `proposal.md`. Then say, in the chat, in about this much
space:

```text
add-note-search — proposed.

Capabilities: `note-search` (new). Ruled out `note-storage`: it contracts how
notes persist, not how they are found.

Risk: standard. One service, one endpoint, no migration and no public
contract moves.

Open: whether search covers archived notes. I recommend no — the archive is a
different retention promise — but it changes the spec, so it is yours.
```

Name the change, the capabilities you took and the ones you ruled out, the tier
and the one sentence that justifies it, and anything you still need from the
user. Then stop: no specs, no design, no tasks, no product files.

---

## Guardrails

- **Don't start building.** Not a helper, not a test, not a rename. This gate
  exists because agreeing on the problem is cheaper than undoing the solution.
- **Don't tidy the requester's words.** `## Why` and `## What Changes` arrive
  as theirs. Add what is missing; do not rewrite what is there into your voice.
- **Don't invent a capability you did not look for.** Reading `specs/` first is
  the whole difference between reuse and a duplicate contract.
- **Don't leave `risk` unset** and let the gate explain it. That is a blocker
  you were asked to resolve.
- **Don't write `approvals`.** `auto_approvals` is yours under autopilot; the
  other map belongs to a person.
- **Don't widen the change while writing it.** Anything the user did not ask
  for is a non-goal in `## Impact`, or its own change.
