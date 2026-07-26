# Performance checklist

Read this file after measuring a reproducible bottleneck.

## Establish evidence

- Record workload, environment, dataset size, and baseline metrics.
- Profile before changing code; retain the trace or benchmark command.
- Choose a user-facing target such as latency, throughput, memory, or bundle size.

## Backend

- Check query counts, missing indexes, N+1 access, and unbounded result sets.
- Bound concurrency, retries, payload size, and cache lifetime.
- Move CPU-heavy work off latency-sensitive async loops.
- Confirm improvements under representative data, not toy fixtures.

## Frontend

- Inspect network waterfalls and JavaScript bundle composition.
- Measure LCP, INP, and CLS in a real browser.
- Remove unnecessary render work before adding memoization.
- Lazy-load code and media only where the loading transition remains usable.

## Regression guard

- Compare the same benchmark before and after.
- Add a test, budget, or dashboard threshold for the improved metric.
- Record correctness tradeoffs and invalidate caches explicitly.
- Revert optimizations that do not produce a meaningful measured gain.
