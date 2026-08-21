---
name: coding-testing
description: Use this skill to design or repair a test strategy around observable contracts, failure modes, flakes, integration boundaries, cross-version compatibility, or end-to-end proof. It selects the cheapest reliable test level and controls nondeterminism; do not use it merely to run an existing test command or to weaken assertions until a suite passes.
---

# Test a code system

Build proof around failures the system must detect. Coverage percentage is a
signal, not the test strategy.
Do not load bundled references when this skill activates.

## Define the proof obligation

1. State the contract, observable outcome, boundary owner, and failure modes.
2. Identify which dependencies are part of the behavior and which can be
   replaced without invalidating the proof.
3. Map each risk to the cheapest level that can observe it: unit, component,
   contract, integration, end-to-end, property, load, or manual runtime check.
4. Read [references/test-level-selection.md](references/test-level-selection.md)
   when choosing between adjacent levels, testing independently deployed
   consumers, or replacing a flaky high-level test.

When the behavior under test has no exact declaration yet, call `code_context` with `action="search"`
once with the observable contract, error text, route, or code fragment. Use the
result to choose the symbol and test boundary; skip search when the exact symbol
is already known.

For an exact symbol under test, use `code_context` to identify direct
`callers`, `references`, and outbound `callees` that define the observable
contract or require compatibility coverage. Use `impact` only for a named
transitive risk and start at depth 1. Graph edges choose test boundaries; they
do not prove runtime ordering, concurrency, reflection, or environment state.
Once the proof obligation selects an exact symbol, make the graph the next
structural observation instead of continuing broad discovery.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read
[references/code-context-contract.md](references/code-context-contract.md) only
after a result exposes ambiguity, cross-repository coverage, or another static
fallback gap.

## Design resilient tests

Prefer public behavior and stable seams over private calls. Make fixtures
minimal, explicit, and semantically meaningful. Control time, randomness,
identity, concurrency, network, filesystem, and external services at the
boundary that owns them—not at every layer.

Cover applicable cases:

- successful behavior and important variants;
- boundary values and invalid input;
- authorization and isolation failures;
- partial failure, retry, cancellation, and recovery;
- ordering, duplicate delivery, and concurrency;
- regression input for each known defect;
- old/new contract pairings during migration.

Avoid snapshots when focused semantic assertions express the contract more
clearly. Do not mock away the interaction under test or assert implementation
trivia solely to increase line coverage.

## Handle flakes

Reproduce repeatedly, record the failure signature, and classify shared state,
clock, ordering, resource, environment, or assertion instability. Remove the
nondeterminism or wait on an observable condition. Retries may measure a flake
temporarily but are not its fix.

## Execution discipline and proof stop

Choose one proof obligation and the cheapest sufficient level before surveying
fixtures. Search/read one nearest existing seam, then batch independent source
and test observations. Use `code_context`, `read`, `grep`, and `glob` for source;
do not use shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread
source or bypass an observation receipt. Reserve shell for test, formatter,
lint/type, build, repetition, and runtime commands. Await long commands with
`process(action="wait", wait_seconds=60)`.

When the focused proof fails, use its exact diagnostic to correct one fixture,
boundary, or assertion and rerun the same command. Once the focused proof and
the required affected suite pass, stop; do not add adjacent cases that do not
map to the stated failure modes.

## Verify and report

Run the narrow test first, then the affected suite. Prove the regression test
fails for the intended reason before the implementation fix when practical.
Report what is exercised for real, what is simulated, commands and repetition
counts, and what still requires a production-like environment.
