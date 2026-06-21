---
title: OpenTelemetry Observability
description: OTel traces, metrics, export-time sampling tiers, span hierarchy for single and multi-agent runs, /telemetry UI.
status: stable
updated: 2026-04-21
---

# OpenTelemetry Observability

EvoFlux emits OpenTelemetry traces and metrics from every agent run — single-agent and team — following the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

---

## Files

| File | Purpose |
|------|---------|
| `app/core/otel.py` | SDK bootstrap — `setup_otel`, `shutdown_otel`, `get_tracer`, `get_meter`; `_FilteringJsonlSpanExporter` implements the export-time sampling tiers. |
| `app/core/jsonl_writer.py` | `JsonlBatchWriter` — bounded queue, hourly/daily partitioning, drop-on-backpressure |
| `app/agent/hooks/otel.py` | `OpenTelemetryHook` — emits spans + metrics via hook lifecycle |
| `app/agent/hooks/summarization.py` | `SummarizationHook` — emits `summarization` + `summarization_llm_call` spans directly |
| `app/services/title_service.py` | `generate_and_save_title` — emits `title_generation` span directly |
| `app/services/observability_service.py` | DuckDB query layer over the JSONL partitions — powers the HTTP API |
| `app/api/routes/observability.py` | `GET /api/observability/summary`, `/traces`, `/traces/{trace_id}` |
| `web/src/routes/telemetry.tsx` | `/telemetry` page — aggregates, trace list, waterfall, span-detail panel |
| `manual/otel_inspect.py` | *(removed)* CLI tool to query spans and metrics from JSONL files |

---

## Output files

When no `OTEL_EXPORTER_OTLP_ENDPOINT` is set (default), spans and metrics are written to hourly/daily partitions under `{EVOFLUX_STATE_DIR}/otel/` (defaults to `.EvoFlux/state/otel/`):

```
.EvoFlux/state/otel/spans/YYYY-MM-DD-HH.jsonl    ← hourly partition, one JSON object per span
.EvoFlux/state/otel/metrics/YYYY-MM-DD.jsonl     ← daily partition, one JSON object per 60-second export cycle
```

Partitioning is done by `JsonlBatchWriter` (see `app/core/jsonl_writer.py`); spans are written through a bounded queue with drop-on-backpressure counted in the `EVOFLUX_otel_spans_dropped_total` Prometheus metric. `EVOFLUX_STATE_DIR` overrides the root (e.g. `EVOFLUX_STATE_DIR=/var/lib/EvoFlux/state`).

Both files are JSONL — one record per line, readable with `jq`, `grep`, or `jq`-based queries.

---

## Sampling — export-time tiering

Head sampling is `ALWAYS_ON` so every span reaches the exporter. Cardinality is controlled **at export time** by `_FilteringJsonlSpanExporter` in `app/core/otel.py`, which applies three tiers in order:

1. **Error spans** — `status.status_code == ERROR` → always exported.
2. **Slow spans** — duration ≥ `OTEL_SLOW_SPAN_MS` (default **1000 ms**) → always exported.
3. **Ratio sampling** — deterministic per-trace: keep the trace iff the low 64 bits of `trace_id` fall below `OTEL_SPAN_SAMPLE_RATIO × 2⁶⁴`.

| Env var | Default | Effect |
|---------|---------|--------|
| `OTEL_SPAN_SAMPLE_RATIO` | `1.0` | Fraction of traces to keep when Tier 1/2 don't apply. Default `1.0` = keep every span, which is the right choice for on-machine single-user systems. Lower only if span volume becomes unmanageable. Invalid strings and values outside `[0.0, 1.0]` clamp to the default. |
| `OTEL_SLOW_SPAN_MS` | `1000` | Spans at or above this duration always export, bypassing Tier 3. Useful to keep the ratio low while still capturing every slow operation. |

### Why the default changed to 1.0

Earlier versions defaulted `OTEL_SPAN_SAMPLE_RATIO` to `0.1`. For on-machine use this was too aggressive: every fast `execute_tool` span (`ls`, `date`, `write`, `team_message` — typically <20 ms) failed the slow check, and 90% of traces failed the ratio check, so the waterfall view showed LLM calls only. With the default now `1.0`, every tool invocation appears in the UI. Lower the ratio explicitly only if span volume becomes unmanageable.

### UI behaviour when sampling is enabled

The `/telemetry` page reads `OTEL_SPAN_SAMPLE_RATIO` via `GET /api/observability/summary` and renders a warning banner ("Spans are sampled at N%. Figures for non-error, non-slow spans are approximate.") whenever the ratio is less than 1.0. The banner disappears at the default.

---

## Span hierarchy

### Single-agent

```
agent_run {agent_name}        parent_id=null   ← full turn, before_agent…after_agent
  ├── chat {model}            parent_id=root   ← each LLM call, wrap_model_call
  ├── execute_tool {name}     parent_id=root   ← each tool call, wrap_tool_call
  └── summarization           parent_id=root   ← marked in before_model, executed in wrap_model_call when threshold hit
        └── summarization_llm_call             ← the actual LLM call inside the hook
```

`summarization` and `summarization_llm_call` are emitted directly by `SummarizationHook`, not via `OpenTelemetryHook`. `title_generation` is emitted independently by `title_service.generate_and_save_title` (spawned as a fire-and-forget task by `TitleGenerationHook.before_agent()`, so its span has no agent parent). Both direct LLM paths set `gen_ai.operation.name`, provider/model, and usage/cost attributes when the provider adapter returns usage metadata:

```
title_generation              parent_id=null   ← concurrent with agent_run, first turn only
```

Session model overrides apply to lead title generation and summarization. If a session is using `googlegenai:gemini-3.1-flash-lite`, direct title/summarization spans should report `gen_ai.provider.name=googlegenai` and `gen_ai.request.model=gemini-3.1-flash-lite` instead of the agent's default model.

### Team (multi-agent)

All members of the same team run share one `trace_id` derived from `lead_session_id`.

```
agent_run orchestrator         parent_id=null   ← lead span (root)
  ├── chat {model}
  └── execute_tool team_message

agent_run explorer            parent_id=lead   ← child of lead span
  └── chat {model}

agent_run executor            parent_id=lead   ← child of lead span
  └── chat {model}

agent_run coder               parent_id=lead   ← child of lead span (coding mode)
  └── chat {model}
```

### Multi-turn

`lead_session_id` and `member_session_id` are stable across turns within the same conversation. Turns are differentiated by `run_id` (a fresh `uuid7` per `agent.run()` call).

```
trace_id = stable per conversation  (anchored to lead_session_id / session_id)
  turn 1: run_id = uuid-1
  turn 2: run_id = uuid-2
  turn 3: run_id = uuid-3
```

---

## Span attributes

### `agent_run {agent_name}` (root)

| Attribute | Value |
|-----------|-------|
| `gen_ai.agent.name` | agent name from config |
| `gen_ai.provider.name` | provider prefix from `model_id` (e.g. `openai`) |
| `gen_ai.request.model` | model name from `model_id` (e.g. `gpt-4o`) |
| `gen_ai.conversation.id` | `ctx.session_id` — stable per conversation |
| `run_id` | `ctx.run_id` — unique per turn |
| `gen_ai.usage.input_tokens` | total prompt tokens for the run (set on close) |
| `gen_ai.usage.output_tokens` | total completion tokens for the run (set on close) |

### `chat {model}` (LLM call)

| Attribute | Value |
|-----------|-------|
| `gen_ai.operation.name` | `"chat"` |
| `gen_ai.provider.name` | provider name |
| `gen_ai.request.model` | requested model |
| `gen_ai.response.model` | model actually used (if provider returns it) |
| `gen_ai.conversation.id` | session_id |
| `gen_ai.request.message_count` | number of messages sent to LLM |
| `gen_ai.usage.input_tokens` | prompt tokens for this call |
| `gen_ai.usage.output_tokens` | completion tokens for this call |
| `gen_ai.usage.cache_read.input_tokens` | cached tokens (if provider reports it) |
| `gen_ai.usage.estimated_cost_usd` | estimated call cost when registry pricing and usage tokens are available |
| `gen_ai.usage.reasoning_tokens` | thoughts / reasoning tokens (reasoning models only — gpt-5, gemini-thinking) |
| `gen_ai.usage.tool_use_tokens` | tool-use tokens (reasoning models that bill tool dispatch separately) |
| `error.type` | exception class name (only on error) |

Token and cost attributes are populated by shared usage helpers from the `AssistantMessage.extra["usage"]` dict. Normal streamed chat responses get that dict from `Agent._stream_and_assemble`; direct title-generation and summarization calls reuse the same shape when provider adapters expose non-streaming/streaming usage metadata. Cost is estimated from model-registry pricing and omitted when pricing is unknown. `None`-valued keys are stripped inside `observability_service.get_trace` before reaching the API response (DuckDB's `read_json(..., union_by_name=true)` would otherwise surface every attribute key on every span row as `None`, so the span-detail panel would show empty em-dashes for unrelated keys).

## Dashboard Aggregates

`GET /api/observability/summary` powers the `/telemetry` overview. The UI intentionally keeps the top-level view narrow:

- Usage cards: input tokens, output tokens, cache hit percentage, estimated cost, and errors.
- Provider:model table: calls, input/output, cache hit, and cost per model.
- Cache hit/miss table: hit tokens, miss tokens, hit rate, cost, and provider:model per operation step (`chat`, `title_generation`, `summarization`, and other `gen_ai.operation.name` values).
- Recent traces: scroll-paginated `agent_run` rows from `GET /api/observability/traces`, with row-click drilldown into the waterfall.

Root `agent_run` usage is excluded from token/cost aggregates to avoid double-counting child LLM spans.

### `execute_tool {name}` (tool call)

| Attribute | Value |
|-----------|-------|
| `gen_ai.operation.name` | `"execute_tool"` |
| `gen_ai.tool.name` | tool function name |
| `gen_ai.tool.call.id` | `tool_call_id` from provider |
| `gen_ai.agent.name` | agent that invoked the tool |
| `gen_ai.conversation.id` | session_id |
| `tool.result.length` | char length of the result string |
| `error.type` | exception class name (only on error) |

### `summarization` (context compression)

Emitted by `SummarizationHook._summarise()` when the prompt token threshold is crossed.

| Attribute | Value |
|-----------|-------|
| `gen_ai.agent.name` | agent name |
| `gen_ai.conversation.id` | session_id |
| `run_id` | unique per turn |
| `summarization.prompt_tokens` | `state.usage.last_prompt_tokens` at trigger time |
| `summarization.threshold` | configured token threshold |
| `summarization.messages_to_summarise` | number of messages being compressed |
| `summarization.keep_last_assistants` | configured keep window |
| `summarization.summary_length` | char length of generated summary text |
| `summarization.kept` | number of messages kept verbatim |
| `summarization.skipped` | reason string if no LLM call was made (e.g. `"no_messages"`) |
| `error.type` | exception class name (only on error) |

### `summarization_llm_call` (summarizer LLM)

Child span of `summarization`, emitted by `SummarizationHook._call_llm()`.

| Attribute | Value |
|-----------|-------|
| `summarization.llm_duration_s` | elapsed seconds for the streaming LLM call |
| `summarization.response_length` | char length of the raw LLM response |
| `error.type` | exception class name (only on error) |

### `title_generation` (session title)

Emitted by `title_service.generate_and_save_title()`. Spawned by `TitleGenerationHook.before_agent()` as a fire-and-forget task on the first turn of a new session — no agent parent span.

| Attribute | Value |
|-----------|-------|
| `gen_ai.conversation.id` | session_id |
| `title_generation.user_message_length` | chars of user message sent to LLM (capped at 500) |
| `title_generation.llm_duration_s` | elapsed seconds for the title LLM call |
| `title_generation.title_length` | char length of the generated title |
| `title_generation.skipped` | reason string if title was not saved (e.g. `"empty_response"`, `"session_not_found"`) |
| `error.type` | exception class name on timeout or LLM error |

---

## Metrics

| Metric | Type | Unit | Dimensions |
|--------|------|------|------------|
| `gen_ai.client.operation.duration` | Histogram | `s` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model` |
| `gen_ai.client.token.usage` | Histogram | `{token}` | above + `gen_ai.token.type` (`input` / `output`) |
| `EvoFlux.tool.execution.duration` | Histogram | `s` | `gen_ai.tool.name`, `gen_ai.agent.name` |
| `EvoFlux.agent.runs.total` | Counter | — | `gen_ai.agent.name`, `gen_ai.provider.name`, `gen_ai.request.model` |

Metrics are exported to `{EVOFLUX_STATE_DIR}/otel/metrics.jsonl` every 60 seconds and on shutdown.

---

## Hook wiring

### Team member (`app/agent/mode/team/member.py`)

```python
otel_hook = OpenTelemetryHook(
    agent_name=self.name,
    model_id=self.agent.model_id,
    lead_session_id=lead_session_id,   # anchors trace under lead's span
)
```

`lead_session_id` is the key: all member spans for the same team run share the same `trace_id` so the full team turn appears as one trace tree.

---

## Exporting to a backend (optional)

When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are forwarded via OTLP gRPC instead of writing to file. Install the optional exporter package first:

```bash
uv add opentelemetry-exporter-otlp-proto-grpc
```

Then set the env var and start the server:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 make run
```

Compatible backends (all have free tiers or self-hosted options):

| Backend | Docker one-liner |
|---------|-----------------|
| **SigNoz** | `docker run -d -p 3301:3301 signoz/signoz` |
| **Jaeger** | `docker run -d -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one` |
| **Grafana LGTM** | see [grafana/otel-lgtm](https://github.com/grafana/otel-lgtm) |

No hook or app code changes needed — swap the exporter, restart the server.

---

## HTTP API

The backend exposes a DuckDB-backed query layer over the JSONL partitions so the `/telemetry` UI (and any other client) can render aggregates, trace lists, and waterfalls without parsing files directly.

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/observability/summary?days=N` | Aggregates — totals, latency histograms, per-model and per-tool breakdowns, `sample_ratio` (used by the UI's sampling banner). |
| `GET` | `/api/observability/traces?days=N&limit=L&offset=O` | Trace list — one row per root `agent_run`, newest first. Each item has `trace_id`, `run_id`, `session_id`, `agent_name`, `model`, `started_at`, `duration_ms`, `llm_calls`, `tool_calls`, `input_tokens`, `output_tokens`, `status`. |
| `GET` | `/api/observability/traces/{trace_id}?days=N` | Full span tree for one trace. Returns `404` when the trace isn't in the `days` window. Each span carries a cleaned `attributes` dict (`None`-valued keys stripped). |

Query the window parameter generously (e.g. `days=30`) for trace-detail fetches — the trace list may have rendered a row that falls just outside a small window, producing a surprise `404`.

### How DuckDB reads the partitions

All handlers delegate to `observability_service._create_spans_window_view`. It pre-filters JSONL partitions by lexicographic stem (file names are `YYYY-MM-DD-HH.jsonl`, so a stem compare against `window_start.strftime("%Y-%m-%d-%H")` drops files outside the window cheaply) via `_candidate_files`, then creates a temp VIEW via `read_json([...], union_by_name=true)` and a derived `spans_window` view filtered by nanosecond `end_time` for the exact range. `union_by_name` is what surfaces every attribute key across all spans — which is why `get_trace` strips `None`-valued keys before serialising (without this step, DuckDB would report every attribute column on every row, leaking schema pollution into the span-detail panel).

---

## Querying spans

Use `jq` or `grep` to query the JSONL files directly. The app writes to hourly partitions under `.EvoFlux/state/otel/spans/`:

```bash
# Latest hour (adjust to match rtk ls -la .EvoFlux/state/otel/spans/)
SPANS=.EvoFlux/state/otel/spans/$(date -u +%Y-%m-%d-%H).jsonl

# Show last 20 spans
cat "$SPANS" | tail -20 | jq .

# Duration breakdown by operation
cat "$SPANS" | jq -s 'group_by(.attributes."gen_ai.operation.name") | map({op: .[0].attributes."gen_ai.operation.name", count: length})'
```

For multi-hour investigations, concatenate partitions first:

```bash
cat .EvoFlux/state/otel/spans/2026-04-17-{15,16,17}.jsonl > /tmp/window.jsonl
```

---

## TelemetryHook vs OpenTelemetryHook

Both hooks can coexist. They serve different purposes:

| | `TelemetryHook` | `OpenTelemetryHook` | Direct instrumentation |
|--|-----------------|---------------------|----------------------|
| Output | `.EvoFlux/state/telemetry/<sid>/<msg_id>.jsonl` | `.EvoFlux/state/otel/spans/YYYY-MM-DD-HH.jsonl` | `.EvoFlux/state/otel/spans/YYYY-MM-DD-HH.jsonl` |
| What | Full context window snapshot (all messages + system prompt) | Structured spans + metrics per LLM/tool call | `summarization`, `summarization_llm_call`, `title_generation` spans |
| When | After each agent run | During each LLM call and tool call | When summarization fires or title is generated |
| Use for | Debugging context window, summarization, prompt inspection | Latency, token cost, error rate, distributed tracing | Summarization + title generation latency |
| Wired | Deprecated (kept for reference) | Team members (via `TeamMemberBase._handle_messages`) | `SummarizationHook`, `title_service` |
