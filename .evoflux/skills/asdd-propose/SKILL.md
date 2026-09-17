---
name: asdd-propose
description: Draft or redraft the proposal for an ASDD change — why it is needed, what observably changes, and which capabilities it touches. Use when a change is in `drafting` or `proposed`; do not use for specification, planning, implementation or verification.
---

# Propose an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and the
`project.md` in the resolved `data_directory`. Read `specs/` to learn what the
catalogue already contracts, and the change folder you were given. Repository
files are the source of truth; never reconstruct a change's state from chat
memory.

You are given a `change-id`. Everything you write goes in
`<data_directory>/changes/<change-id>/`. That folder name is the change's whole
identity — do not invent a run id, a revision number or a hash for it.

## State gate

Work only when `proposal.md` reads `status: drafting` or `status: proposed`. A
change past `specifying` has an approved proposal; changing it now would
invalidate an approval the user already gave, so stop and say so instead.

## Work from evidence

1. Read every applicable `AGENTS.md` in the authorized repository scope, then
   the owning source, configuration, migrations and focused tests. Treat code
   and tests as current-state evidence; treat plans and comments as proposals.
2. Read `specs/` before naming a capability. **Reuse an existing capability
   whenever this change alters behavior that capability already contracts** —
   that produces another revision of one contract instead of two contracts
   describing the same thing. Coin a new slug only for behavior the catalogue
   does not cover, and say which existing capabilities you ruled out.
3. Scan for ambiguity that could change product behavior: scope, actors and
   permissions, state and data, failure and recovery, concurrency, security and
   privacy, compatibility, observability, and what "done" means. Ask one concise
   clarifying question rather than guessing. Do not interrogate the user about
   low-impact details.

## Write the proposal

Write `changes/<change-id>/proposal.md` with these sections, keeping its front
matter intact except for the fields named below:

- `## Why` — the problem in the user's terms, and the cost of doing nothing.
- `## What Changes` — one bullet per observable change; mark breaking changes.
- `## Capabilities` — `### New Capabilities` and `### Modified Capabilities`,
  each entry a slug and one sentence.
- `## Impact` — code, data and operations touched, plus explicit non-goals.

In the front matter, set:

- `title` — a short imperative name for the change.
- `capabilities` — every capability slug the change will carry a delta for.
- `risk` — `trivial`, `standard`, `cross_layer` or `critical`. Choose
  `cross_layer` or `critical` for multi-repository, security, migration,
  persistence, public-compatibility or concurrency work; those tiers require a
  design document and an independent review, so do not reach for them to signal
  effort.
- `status: proposed` — last, once the sections above are complete.

Leave `approvals` alone. Approval is the user's, and writing a timestamp there
yourself forges a gate the product will then honor.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Turn each behavior the request names into one `action="search"` call, then
  promote the returned declared identifier. Prose is never an exact-symbol query.
- Size the change with `action="callers"` and `action="references"` before
  writing the Impact section. Every claim needs a resolved relationship behind
  it, not an assumption about layout.
- Ambiguity is evidence: two definitions for one name is exactly the kind of
  finding worth a clarifying question before you choose behavior.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

Stop after writing the file. Report the change id, the capabilities you named
and the ones you ruled out, the risk tier and why, and any question you still
need answered. Do not write specs, design or tasks, and do not touch product
files.
