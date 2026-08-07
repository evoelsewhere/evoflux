---
name: coding-debugging
description: Use this skill when a test, build, runtime path, integration, or concurrent workflow fails and the responsible condition is unknown. It is for reproducing symptoms, isolating a cause, fixing it when authorized, and proving the regression; do not use it for general code exploration, proactive review, or an already-understood mechanical edit.
---

# Debug a code failure

Treat debugging as a causal investigation. A passing build after an edit is not
proof unless the edit explains the original symptom.

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
