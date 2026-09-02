---
name: coding-observability
description: Use this skill to add or redesign logs, metrics, traces, or alerts for a code path — deciding what to instrument and why, structured-logging shape, correlation IDs, RED/USE signal selection, or alert thresholds. It requires naming the on-call question the telemetry answers before adding it; do not use it for functional correctness work with no diagnostic-visibility gap, or for measuring a single already-identified performance bottleneck.
---

# Instrument code for observability

Telemetry without a question behind it is noise, not signal: name what an
operator would need to know before adding a log, metric, trace, or alert.
Do not load bundled references when this skill activates.

## Name the question first

1. State two to four concrete on-call or debugging questions this telemetry
   must answer (e.g. "is this queue backing up," "which tenant is causing
   the error spike"). Reject an instrumentation request with no question
   behind it; ask what it is meant to diagnose.
2. Choose the signal that answers each question: logs for what happened at a
   point in time, metrics for how often/how fast in aggregate, traces for
   where time went across a call chain. Do not default to logging
   everything.
3. Read [references/signal-selection.md](references/signal-selection.md) for
   RED/USE selection, correlation-ID placement, cardinality limits, and
   alert design.

When the owning boundary for a signal is not yet an exact symbol, call
`code_context` with `action="search"` once using the operation or error
text. Skip search when the exact symbol is already known.

For an exact symbol being instrumented, use `code_context` to confirm its
direct `callers` (who triggers it) and `callees` (what it depends on) so the
correlation ID or span is attached at the actual request boundary, not an
internal helper. Start at depth 1. Once the boundary is known, make the graph
the next structural observation instead of continuing broad discovery.

Keep `refresh=true` for the first indexed query and after edits. Use
`refresh=false` only for an immediate follow-up that intentionally reuses the
same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only after a result exposes ambiguity, cross-repository scope, or another
static fallback gap.

## Instrument

Use stable, named event identifiers rather than interpolated free-text
messages so logs stay queryable as the message wording changes. Generate a
correlation ID at the boundary that owns the request and propagate it through
every downstream call and log line. Never attach a high-cardinality value —
user ID, raw URL, request ID — as a metric label; put it in a log or trace
instead, and keep metric labels bounded to a known, small set of values.

For an alert, target a symptom a user or SLA actually feels (error rate,
latency, saturation), not an internal cause like CPU or memory alone — those
belong on a dashboard. Attach a runbook link to every alert and keep only two
severities in practice (page-now vs. ticket-later) to avoid alert fatigue
from finer gradations nobody honors.

## Verify the telemetry works

Force the failure or condition the new signal is meant to catch in a
non-production environment and confirm the log/metric/alert actually fires
with the expected shape. An alert that has never fired in a drill is
unverified, not trustworthy.

## Execution discipline and instrumentation stop

Confirm the owning boundary once; batch independent reads. Use
`code_context`, `read`, `grep`, and `glob` for source; do not use shell
`cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread source or
bypass an observation receipt. Reserve shell for formatter, lint/type,
build, and verification commands.

Stop once every named on-call question has a signal, the signal is verified
to fire, and any alert has a runbook link. Do not instrument adjacent code
paths the request did not name.

## Deliverable

State the on-call questions answered, the signals added (with cardinality
and correlation-ID placement), any alert and its runbook link, and how the
telemetry was verified to fire.
