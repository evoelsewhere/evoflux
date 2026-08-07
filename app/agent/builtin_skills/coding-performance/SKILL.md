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

After profiling exposes an exact symbol, use native `code_graph` to bound its
structural context: `callers` for invocation sites, `callees` for delegated
work, and `references` for dispatch/registration uses. Start at depth 1 and do
not infer frequency, timing, allocation, or runtime order from static edges.

Use `freshness_policy="fast"` for the first graph call and normal interactive
navigation. If it returns `fresh`, do not rerun with a stronger policy. If it
returns `partial` and a reported dirty file overlaps the question, use a
targeted source read for a local gap or retry once with `"balanced"` when the
relationships must be recomputed. After an edit that can change relationships,
use `"balanced"` once before relying on the updated structure. Use `"strict"`
only for a final,
high-consequence completeness check when watcher coverage is unavailable or
untrusted; never use it for discovery.

Read [references/code-graph-contract.md](references/code-graph-contract.md)
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

## Deliverable

Report workload and protocol, baseline, attributed bottleneck, change,
before/after distributions, variance, correctness checks, tradeoffs, and the
next limiting resource. Label unmeasured expectations as hypotheses.
