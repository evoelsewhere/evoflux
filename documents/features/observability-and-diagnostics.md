# Observability and diagnostics

EvoFlux exposes user-facing activity in the transcript and operator-facing
health, logs, metrics, traces and audits. Local observability is inspectable and
bounded by retention settings.

## Live activity

The session SSE stream carries structured events for model deltas, reasoning,
tool calls/results, agent status, delegations, todos, handoffs, usage, plan and
permission requests, questions, goals, workflows, queues, compaction and final
completion/error. The React team store projects these into transcript blocks,
Activity/Monitor views and progress controls.

### Live turn status

A streaming turn carries one status line above it, and a finished turn carries
one meta run in its footer. Both print the same three facts — elapsed time,
turn tokens, estimated USD — through shared formatters, so the numbers do not
reformat themselves when the turn ends.

The status line also names what the agent is doing, derived from the turn's
own blocks rather than from a phase flag: an open tool call names the tool and
its target ("Editing main.rs"), a growing thinking or text block reads as
reasoning or answering, and a finished tool with nothing streamed after it
means the provider has the turn again ("Waiting for <model>"). The
`agent_status` phase (`ingress` vs `model_calling`) is the fallback used only
before the first block arrives, because it is emitted once per turn and cannot
distinguish the model calls inside a tool loop.

The line sits below the turn's output, in the slot the footer takes once the
turn finishes, and there is exactly one of it per view for the whole turn. A
turn is not one continuous working run — an activation ends, the stream
flushes, and the next activation starts — so the line outlives the working
flag by a short hold. Without it the line blinked out for over a second in the
middle of a single answer and came back with a restarted clock; the elapsed
now measures from the earliest start observed while the line is up.

Turn tokens are authoritative only per completed model call, which the usage
event publishes. Between those events the line extends the last measured total
with a character-length estimate so the counter keeps moving through a long
call; the next usage event assigns over the estimate.

Session-specific JSONL logs provide a local evidence trail per agent. Sensitive
values are sanitized before tool/provider errors are logged or streamed.

### Diagnostics actions

A check may carry an `action` alongside its hint, and the row renders it as a
button rather than describing a fix the user has to perform by hand. The
backend owns the wording, including the confirmation, so the dialog can say
what will actually happen to that particular installation.

`db_reclaim` frees SQLite's unused pages. A database on `auto_vacuum=
INCREMENTAL` has its free list trimmed in place. One created before that
pragma cannot switch without a full `VACUUM`, so the action performs both
once and every later reclaim takes the cheap path; that branch first checks
there is disk space for the rewrite, and is refused while an agent is working
because the rewrite holds a write lock for its duration. `VACUUM` is atomic —
an interrupted run leaves the original file intact.

## OpenTelemetry

The sidecar records spans for agent runs, model calls, tools and relevant
services. The local exporter writes hourly span and daily metric JSONL
partitions below the state root. Retention runs as an optional background
service and the process flushes on shutdown.

The observability service queries span partitions through DuckDB without a
separate telemetry database. It provides:

- aggregates over 1–90 days;
- newest-first paginated agent-run traces;
- complete time-ordered span trees for a trace;
- latency, token, model, tool and error summaries;
- sampling ratio metadata without pretending sampled counts are exact totals.

The `/telemetry` UI renders summary, model/tool breakdowns, trace tables and a
waterfall/detail view.

Prompt-cache reporting treats provider usage as four disjoint billing classes:
ordinary input, cache reads, cache writes and output. The Models view shows read
and write tokens separately, derives ordinary input as
`total input - reads - writes`, and bounds historical hit rates at 100% even if
an older provider adapter recorded inconsistent totals. Missing cache-write
attributes in historical span partitions aggregate as zero.

Estimated USD is best-effort and requires a fully qualified `provider:model`
with matching registry prices. Subscription/local providers do not expose
token spend as actual invoice cost, so their token usage remains visible while
estimated USD is omitted.

## Prometheus and HTTP metrics

`GET /metrics` is the unprefixed Prometheus scrape target. Middleware measures
end-to-end HTTP requests, including rejects by inner auth/size/security layers.
Agent/team/database/code-index paths add focused counters and histograms where
operator action is useful.

## Health and diagnostics

| Endpoint/surface | Purpose |
|---|---|
| `/api/health/live` | Process is running and can answer HTTP |
| `/api/health/ready` | Critical dependencies/schema are usable |
| `/api/health/diagnostics` | Bounded health component detail |
| `/api/diagnostics` | Version, runtime paths, platform, desktop mode and service configuration |
| `evoflux doctor` | Local install/config/provider checks; CI-friendly exit status |
| `evoflux health` | Background server/process and HTTP health summary |
| Settings → Diagnostics | User-facing runtime and connection investigation |

Health checks avoid exposing credential values. Optional integrations report
degraded/unavailable status without being treated as critical sidecar failure.

## Domain-specific audit

WebBridge keeps a bounded command audit ring; Git jobs retain bounded status and
sanitized output; workflow execution/node rows and goal state provide durable
automation evidence; Conductor records resource drift and delivery state.

## Source and tests

Primary code: `app/core/otel.py`, `otel_retention.py`, `metrics.py`, logging and
JSONL helpers; observability/diagnostics/health services and routes; telemetry
React routes; session/activity stores and components.

Focused tests cover OTEL hooks/retention/tiering, metrics middleware,
observability aggregation/routes, health/diagnostics, session logs, provider
usage and frontend telemetry/activity projections.
