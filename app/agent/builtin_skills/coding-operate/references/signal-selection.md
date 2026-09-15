# Observability signal selection

Read this reference when choosing between logs, metrics, and traces, or when
designing an alert.

## RED and USE

- **RED** (rate, errors, duration) — for a request-driven service or
  endpoint.
- **USE** (utilization, saturation, errors) — for a finite resource: a queue,
  connection pool, disk, or worker pool.

## Cardinality

Never use a user ID, raw URL, session ID, or other high-cardinality value as
a metric label — each unique value creates a new time series, and an
unbounded label set is a cardinality bomb that degrades or breaks the metrics
backend. Bucket or drop such values from labels; keep them in logs/traces
instead where per-instance detail belongs.

## Correlation IDs

Generate the ID once at the boundary that owns the request (the entry
point), not at each internal layer. Propagate it through every downstream
call, queue message, and log line so one request's full path can be
reconstructed from the ID alone.

## Alert design

- Alert on a symptom the user or SLA feels (latency, error rate,
  saturation), not a cause alone (CPU, memory) — causes belong on a
  dashboard someone checks when a symptom alert fires.
- Keep to two severities in practice: page now, or ticket for later. More
  gradations tend to be ignored under real on-call load.
- Every alert needs a runbook link and must be test-fired at least once
  before being trusted in production.
