---
name: easd-implement
description: Implement bounded work for an active EASD run under its accepted specification and AC ownership. Use only when EASD has authorized implementation; do not use while the run is Intent, authoring, draft, or merely accepted.
---

# Implement an active EASD run

## Repository contract

Read `.evoflux/easd/config.json` and its `rules_file` before phase work. Treat
the injected EASD context as the authoritative current Run; when the owning
runtime is accessible, corroborate it under `runtime_directory`. An isolated
worktree intentionally has no checkout-local runtime copy. Resolve the accepted
Spec through the common `specs/` index and confirm it matches the Run snapshot. Use `features/`,
`architecture/`, and `reference/` only for living knowledge the accepted change
actually affects; existing external docs remain in place. Repository documents
are the shared source of truth. Stop on a missing tracked contract, stale hash,
generation conflict, or unavailable injected runtime; never reconstruct
authority from chat memory or a stale database-only projection. For `planned`,
bind work to the accepted Plan mission. For `direct`, bind only to accepted
Spec/AC/scope and never invent a Plan identity.

Implement only the active accepted contract and the mission or ownership scope
assigned to this agent. EvoFlux runtime checks remain authoritative even when
this skill is active.

## State gate

Before each implementation or resumed turn, re-read the injected run ID,
`active` status, accepted Spec hash, delivery flow, and mission contract. For
planned flow, also re-read the accepted Plan hash/mission and stop if either is
absent or stale. For direct flow, stop if any Plan identity is claimed. Stop if
the mission was cancelled/reworked or durable context is unavailable. Record
the dirty-worktree baseline so user/peer changes are not claimed as this output.

## Execution discipline

1. Confirm the injected run ID, spec hash, owned ACs, target repositories and
   paths, dependencies, constraints, and evidence policy before mutation.
2. Read the nearest applicable `AGENTS.md` and existing implementation/tests.
   Preserve unrelated and concurrent work in the shared repository.
3. Make the smallest coherent change that satisfies the owned ACs. Keep public
   contracts, persistence, security, and compatibility aligned across affected
   layers.
4. For an observable behavior change or bug, add the focused regression first
   when practical and confirm it fails for the expected missing behavior. Make
   the minimal implementation, confirm the regression passes, then refactor only
   while it stays green. When test-first is inapplicable, record the alternate
   baseline/evidence instead of pretending a red-green cycle occurred.
5. Run the focused accepted verification commands that are safe and available,
   plus boundary-specific regression checks required by repository instructions.
   Prefer canonical commands from `AGENTS.md`, project manifests/task runners,
   CI, and existing test configuration over invented shell pipelines. Read the
   fresh output and exit status before making any pass claim; an unavailable or
   unknown required command is an evidence gap, not an implicit pass.
6. Report changed paths, checks and exact outcomes, evidence gaps, and each owned
   AC result. A task checkbox, handoff, or agent confidence is progress—not
   trusted evidence—and must not be presented as convergence.

## Code graph navigation

Implementation uses `code_context` to check a change before and after making it,
inside the accepted Impact targets.

- Before altering a signature, run `action="callers"` on it. Every call site is
  either inside the accepted targets or a deviation you must report.
- Before changing behavior a function relies on, run `action="callees"` to see
  what you are actually depending on.
- After each edit run the next query with `refresh=true`; use `refresh=false`
  only for an immediate follow-up that intentionally reuses the same index
  version.
- Before handoff, run `action="references"` on every symbol you touched and
  confirm nothing outside the accepted targets moved. This is the cheapest way
  to catch silent scope expansion while it is still fixable.
- `code_context` is never the evidence. It tells you where to look; the
  CompletionContract from a real verification command is what proves the work.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Handoff contract

For a final delegated result, use `team_handoff` and cover every owned AC exactly
once in `criteria_results` with `passed`, `failed`, or `inconclusive` plus a
specific summary. Include only persisted evidence IDs actually returned by the
runtime; never invent them. Put exact commands/results and changed paths in the
verification/evidence fields, and list every scope/spec drift in `deviations`.
Use a partial handoff when work remains rather than marking an incomplete result
final.

If implementation discovery conflicts with accepted intent, crosses assigned
scope, or requires another owner, stop that slice and report a deviation. Do not
edit the accepted specification, broaden permissions, or claim convergence to
make the implementation appear complete.
