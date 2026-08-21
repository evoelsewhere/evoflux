---
name: coding-performance
description: Use this skill to diagnose and improve measured latency, throughput, memory, allocation, I/O, query cost, bundle size, or resource consumption for a representative workload. It requires a baseline, bottleneck attribution, and before/after proof; do not use it for generic cleanup, correctness failures without a performance metric, or speculative micro-optimization.
---

# Improve code performance

Optimize a measured bottleneck while preserving correctness and shifting no
unacceptable cost elsewhere.
Do not load bundled references when this skill activates.

## Define the experiment

1. Specify workload, data scale, concurrency, environment, warmup, cache state,
   user-visible metric, baseline distribution, target, and correctness
   invariants.
2. Reproduce under representative release conditions. Separate application
   cost from network, dependency, background-load, and measurement noise.
3. Read [references/measurement-protocol.md](references/measurement-protocol.md)
   before comparing results when samples are noisy, caching matters, tail
   latency is material, memory grows over time, or environments differ.

## Attribute before editing

Profile the workload and identify the exact call path, query, allocation,
transfer, render, lock, serialization step, or external wait that owns the
material cost. A hot function is not necessarily the optimization boundary;
confirm how often it runs and whether its work is avoidable.

If profiling exposes only a query label, trace name, route, allocation text, or
source fragment, call `code_context` with `action="search"` once to locate the owning declaration. Skip
search when the profiler already reports an exact declared symbol.

After profiling exposes an exact symbol, use `code_context` to bound its
structural context: `callers` for invocation sites, `callees` for delegated
work, and `references` for dispatch/registration uses. Start at depth 1 and do
not infer frequency, timing, allocation, or runtime order from static edges.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only after a graph result exposes ambiguity, cross-repository traversal, or
index limitations. Once profiling selects the exact symbol, make the graph the
next structural observation; do not return to broad source discovery first.

Form one bottleneck hypothesis and choose the smallest change that could
falsify it. Prefer eliminating work, improving algorithmic complexity, reducing
round trips, batching, indexing, bounded caching, or reducing allocation over
opaque micro-optimizations.

## Evaluate the trade

Compare before and after with the same protocol. Include p50/p95/p99 as
relevant, throughput, memory peak or growth, CPU, I/O, payload size, and error
rate. Test concurrency, cold/warm behavior, cache invalidation, and worst-case
inputs where the change can alter them.

Reject improvements that depend on unmatched environments, one noisy sample,
debug builds, relaxed correctness, unbounded memory, stale data, or cost merely
moved to another service or lifecycle phase.

Add a stable benchmark or regression threshold only when it can remain
representative and deterministic enough to maintain.

## Execution discipline and measurement stop

Do not survey source before the baseline/profiler identifies a material owner.
After it does, batch independent graph queries and reads. Use `code_context`,
`read`, `grep`, and `glob` for source; do not use shell `cat`, `sed`, `head`,
`tail`, `nl`, `rg`, or `find` to reread source or bypass an observation receipt.
Reserve shell for benchmarks, profilers, formatter, tests, builds, and runtime
commands. Await long commands with `process(action="wait", wait_seconds=60)`.

One baseline, one bottleneck hypothesis, and one coherent change form the normal
loop. Compare with the same protocol. When correctness guards pass and the
target is met—or the hypothesis is falsified—stop and report; do not search for
the next optimization unless requested. A noisy or failed measurement reopens
only the experiment variable that invalidated it.

## Deliverable

Report workload and protocol, baseline, attributed bottleneck, change,
before/after distributions, variance, correctness checks, tradeoffs, and the
next limiting resource. Label unmeasured expectations as hypotheses.
