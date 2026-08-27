---
name: easd-specify
description: Draft or revise a reviewable EASD specification from repository evidence. Use for an EASD run in Intent or authoring/review state; do not use for implementation or ordinary planning outside EASD.
---

# Specify an EASD run

## Repository contract

Read `.evoflux/easd/config.json` and its `rules_file` before phase work. Treat
the injected EASD context as the authoritative current Run; when the owning
runtime is accessible, corroborate it under `runtime_directory`. An isolated
worktree intentionally has no checkout-local runtime copy. Read the tracked
knowledge-base `index.yaml`,
`specs/`, `features/`, `architecture/`, and `reference/` plus any existing
project documentation named by repository instructions. Do not copy or move
existing docs into EASD implicitly. Repository documents are the shared source
of truth. Stop on a missing tracked contract, stale hash, generation conflict,
or unavailable injected runtime; never reconstruct authority from chat memory
or a stale database-only projection.

Turn persisted Intent into a grounded contract that the user can review. This
skill supplies procedure, not lifecycle authority: repository authorization,
run state, submission, and acceptance remain enforced by EvoFlux.

## State gate

Re-read the persisted run state and latest visible revision from current EASD
context on every invocation; do not continue from chat memory alone. `intent`
may be explored but must enter authoring before submission. `authoring` permits
one typed draft submission. In `draft`, show proposed changes against the current
revision and leave replacement/new-revision control to the user. An accepted or
active run belongs to planning or execution, not this Skill.

## Work from evidence

1. Read the run Intent and every applicable `AGENTS.md` in the authorized
   repository scope.
2. Inspect current feature, architecture, and reference docs, then the owning
   source, configuration, migrations, and focused tests. Treat plans as
   proposals and code/tests as current-state evidence when reverse-engineering.
   Keep multi-repository provenance explicit as `repository:path` and never
   infer a path from conversation shorthand.
3. Scan for high-impact ambiguity in scope, actors/permissions, state and data,
   critical journeys, loading/error/recovery, concurrency, security/privacy,
   integration, compatibility, observability, and completion signals. Ask a
   concise clarifying question before selecting an option that can change
   product behavior; do not interrogate the user about low-impact details.
4. Produce a provider-neutral specification with outcome, goals, non-goals,
   source references, repository-qualified impact targets, constraints,
   compatibility/security boundaries, risk tier, planned verification commands,
   and stable observable ACs with per-AC evidence policies. Recommend `direct`
   only for a low-risk single-boundary change; otherwise recommend `planned`
   and cite the conditions requiring Plan. The user reviews this choice with
   the Spec.
5. Make provenance and uncertainty visible. Do not invent files, commands,
   behavior, or confidence unsupported by the inspected repository.
6. Self-review the draft for contradictions, placeholders, untestable language,
   uncovered critical flows, scope drift, and ACs without concrete evidence.
   For every applicable flow, cover happy behavior plus relevant error,
   authorization, domain-invariant, recovery/concurrency, and cross-context
   behavior. Fix those gaps before submission or expose them as unresolved
   questions; do not add irrelevant scenarios merely to fill a checklist.

### Verification command grammar

Every planned verification command is executed without a shell. Use one
argv-style command per line with an approved executable available on `PATH` or
an approved repository wrapper. Commands must not contain shell composition,
redirection, or control operators: `&&`, `||`, `;`, `|`, `>`, or `<`.

Prefer canonical test/build entry points, for example:

```text
python -m pytest tests/test_simple.py
uv run pytest --no-cov -q tests/api/test_feature.py
bun run typecheck
cargo test
```

Do not submit inline interpreter snippets such as `python -c "...; ..."`, shell
pipelines, redirected output, command chains, or quoted shell scripts as Proof
commands. If behavior needs a custom probe, add or identify a focused repository
test and invoke it through a canonical test command.

## Submit for human review

When the run is in authoring state and the lead has the typed
`easd_submit_specification` tool, submit the exact run ID, complete specification,
grounding summary, and honest confidence. Stop after persistence is confirmed.
Report the returned revision ID/hash as the durable review target; do not treat
the draft's presence or the agent's message as user acceptance. The draft stays
Run-local; explicit user acceptance publishes its hash-identical immutable copy
into the common `specs/` catalogue.

Never approve or activate the specification, begin implementation, or call
convergence. If the tool is unavailable or rejects the draft, report the exact
gap instead of bypassing the EASD lifecycle through files, shell, or direct API
calls.
