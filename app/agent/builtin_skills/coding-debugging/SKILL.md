---
name: coding-debugging
description: Use this skill when a test, build, runtime path, integration, or concurrent workflow fails and the responsible condition is unknown. It is for reproducing symptoms, isolating a cause, fixing it when authorized, and proving the regression; do not use it for general code exploration, proactive review, or an already-understood mechanical edit.
---

# Debug a code failure

Treat debugging as a causal investigation. A passing build after an edit is not
proof unless the edit explains the original symptom.
Do not load bundled references when this skill activates.

## Establish the failure contract

Record the exact input, environment, expected result, observed result, and
earliest known failing boundary. Preserve the original error, stack, status,
timing, or corrupted value. Distinguish a product failure from an incorrect
test expectation or environment mismatch.

## Reproduce and narrow

1. Reproduce with the smallest deterministic command or interaction that still
   fails. If reproduction is blocked, identify the missing state or evidence.
2. Compare one dimension at a time: input, configuration, version, process,
   timing, identity, or dependency.
3. Trace backward from the first bad observation through state transitions and
   exact symbol relationships. Use literal discovery for errors, configuration,
   generated values, and registration keys.
4. Form one falsifiable hypothesis. Run the cheapest check that could disprove
   it before editing production code.
5. Keep a short hypothesis ledger when more than two plausible causes survive.
   Read [references/hypothesis-led-debugging.md](references/hypothesis-led-debugging.md)
   for the ledger format, failure classes, and causal-proof standard.

## Navigate structural evidence

When the failure location or exact identifier is unknown, call `code_context` with `action="search"`
once with the literal error, configuration key, runtime term, or code fragment.
Use its repository-qualified source range to identify a declared symbol. If the
exact symbol is already visible, skip `code_context` with `action="search"`; it is discovery, not
structural proof.

Once source evidence reveals an exact function, method, class, or qualified
symbol, use `code_context` to test the relevant structural hypothesis:
`callers` for inbound paths, `callees` for downstream calls, `references` for
non-call uses, or `neighborhood` for the immediate boundary. Start at depth 1.
Static edges narrow the causal path but do not prove runtime order, state, or a
race; preserve the reproduction as the final causal test.

After an exact symbol and structural hypothesis exist, make `code_context` the
next structural observation. Do not continue broad grep or reread source that
the graph returns. Runtime reproduction may still come first when it is the
cheapest test that can falsify the current causal hypothesis.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only after a graph result exposes ambiguity, cross-repository scope,
index limitations or truncation.

## Fix and prove

Fix the invariant at the boundary that owns it. Avoid retries, broad catches,
longer timeouts, fallback defaults, and extra null guards unless evidence shows
that behavior is the intended contract.

Add a regression test that fails for the original reason before the fix and
passes after it. Rerun the original reproduction plus the narrow affected
suite. For races or flakes, repeat enough times to exercise the timing window
and explain why the new synchronization removes it.

## Execution discipline and stop gate

Batch independent graph queries and source reads. Use `code_context`, `read`,
`grep`, and `glob` for source; do not use shell `cat`, `sed`, `head`, `tail`,
`nl`, `rg`, or `find` to reread source or bypass a revision-aware observation
receipt. Reserve shell for reproduction, formatter, test, diagnostics, and
runtime commands. If one returns a process handle, prefer
`process(action="wait", wait_seconds=60)` over repeated short polls.

Once one falsifiable hypothesis explains the first bad state and its cheapest
disproof supports it, stop broad discovery. After the original reproduction
and regression proof pass, stop; do not investigate adjacent failures unless
they contradict the causal claim. On command failure, inspect only the exact
diagnostic boundary and rerun that same command after one coherent correction.

## Deliverable

Report:

- reproduction and affected environment;
- root cause and the evidence that eliminated alternatives;
- the owning invariant and exact fix;
- regression coverage and commands actually run;
- any unverified environment-specific assumption.

If the user asked only for diagnosis, stop before mutation and provide a
concrete fix direction instead.
