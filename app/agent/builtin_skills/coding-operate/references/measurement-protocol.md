# Performance measurement protocol

Use this protocol whenever before/after results could be distorted by noise,
warmup, caching, or environment drift.

## Record before running

- Commit/build mode and relevant configuration
- Hardware or runtime allocation
- Dataset size and shape
- Concurrency and request mix
- Warmup and cache state
- Run duration, sample count, and repetitions
- Primary metric and correctness guard
- Known external dependencies and background load

## Compare

Use identical inputs and settings. Prefer distributions over a single mean.
Report absolute and relative change with sample counts; retain raw observations
when practical. Restart or alternate variants when order effects matter.

For memory, distinguish retained growth from temporary peak allocation. For
queries, include result cardinality and query plan. For bundles, measure both
transfer and parse/execute effects. For caches, account for hit rate,
invalidation cost, staleness, and memory bound.

## Regression threshold

Set a threshold wider than normal variance but tighter than user-impacting
regression. Document the environment where it is valid. Do not put unstable
microbenchmarks in a blocking suite merely to preserve a one-time result.
