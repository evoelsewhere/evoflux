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

When the failure location or exact identifier is unknown, call `code_search`
once with the literal error, configuration key, runtime term, or code fragment.
Use its repository-qualified source range to identify a declared symbol. If the
exact symbol is already visible, skip `code_search`; it is discovery, not
structural proof.

Once source evidence reveals an exact function, method, class, or qualified
symbol, use native `code_graph` to test the relevant structural hypothesis:
`callers` for inbound paths, `callees` for downstream calls, `references` for
non-call uses, or `neighborhood` for the immediate boundary. Start at depth 1.
Static edges narrow the causal path but do not prove runtime order, state, or a
race; preserve the reproduction as the final causal test.

After an exact symbol and structural hypothesis exist, make `code_graph` the
next structural observation. Do not continue broad grep or reread source that
the graph returns. Runtime reproduction may still come first when it is the
cheapest test that can falsify the current causal hypothesis.

Use `freshness_policy="fast"` for the first graph call and normal interactive
navigation. If it returns `fresh`, do not rerun with a stronger policy. If it
returns `partial` and a reported dirty file overlaps the question, use a
targeted source read for a local gap or retry once with `"balanced"` when the
relationships must be recomputed. After an edit that can change relationships,
use `"balanced"` once before relying on the updated structure. Use `"strict"`
only for a final, high-consequence completeness check when watcher coverage is unavailable or
untrusted; never use it for discovery.

Read [references/code-graph-contract.md](references/code-graph-contract.md)
only after a graph result exposes ambiguity, cross-repository scope,
freshness/dirty-file limits, or truncation.

## Fix and prove

Fix the invariant at the boundary that owns it. Avoid retries, broad catches,
longer timeouts, fallback defaults, and extra null guards unless evidence shows
that behavior is the intended contract.

Add a regression test that fails for the original reason before the fix and
passes after it. Rerun the original reproduction plus the narrow affected
suite. For races or flakes, repeat enough times to exercise the timing window
and explain why the new synchronization removes it.

## Deliverable

Report:

- reproduction and affected environment;
- root cause and the evidence that eliminated alternatives;
- the owning invariant and exact fix;
- regression coverage and commands actually run;
- any unverified environment-specific assumption.

If the user asked only for diagnosis, stop before mutation and provide a
concrete fix direction instead.
