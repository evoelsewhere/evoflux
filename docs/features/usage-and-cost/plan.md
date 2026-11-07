# Usage and cost history — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | [0002 models.dev is the model database](../../architecture/decisions/0002-models-dev-is-the-model-database.md) |

## 1. Context and constraints

- Every provider in `evo-ai` already fills `AssistantMessage.usage.cost` with
  `calculate_cost(&model.cost, &usage)`; `model.cost` comes from models.dev
  (`evo_runtime::models_dev`, [ADR 0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md)).
  Prices are never hardcoded.
- The desktop already adds each finished turn's cost to `chats.cost_usd`
  (`chats::record_turn`) — a per-chat total with no time or model axis.
- Engines open `evo.db` with short-lived connections and `BEGIN IMMEDIATE`
  writes ([Application database](../app-database/plan.md)).
- The engine owns agent logic; the shell reads `evo.db` for pages (like the
  run log).
- Plan usage of subscription providers is a separate command,
  `get_provider_usage`, shown in **Settings → Providers**.
- Compaction and branch summaries call the provider from `evo-harness`
  without an agent event, so the emitter tap below does not see them yet;
  FR-10 (spec 6.2) returns their usage in the compaction result instead.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The engine records each response; the shell only reads `evo.db` for the page, like the run log. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-store` holds the table and queries; the providers in `evo-ai` are unchanged (they already compute the cost). |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | The model descriptor gains optional `cost` and `costConfigured`, consumed through the engine store's models; older engines omit both and the page shows "—". |
| Models come from models.dev; no hardcoded model facts | ok | Costs and prices come from models.dev ([ADR 0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md)); nothing is hardcoded. |
| Real engine in the app; settings and credentials reload live | n/a | No settings; recording is on for every desktop chat. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | No new inputs from models or tools; rows are built from provider usage numbers (3.7). |
| Desktop UI structure and `DESIGN.md` | ok | The page reads through `usage-store`; chart colours are `--viz-*` tokens validated for colour-vision deficiency, and colour is never the only cue. |

## 3. Design

### 3.1 Overview

```text
agent loop ──MessageEnd──► UsageTap ─┐               (source = chat)
agent_tool ProgressEmitter ──────────┤ usage_log::record ─► channel ─► writer thread
child_agents Job::observe ───────────┤               (subagent / plugin / side)
side_questions Emitter ──────────────┘                                 │
                                                    evo.db usage_events ◄┘
desktop: Usage page ─► usage-store ─► invoke usage_summary / usage_events ─► evo_store::usage
         prices ◄── engine-store models ◄── get_available_models (cost from models.dev)
```

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-store/src/usage.rs`, `crates/evo-store/src/migrations/0008_usage_events.sql`, `crates/evo-store/src/migrations/0009_usage_durations.sql` | Table, `record`, `summary` (totals incl. failures and timing, series by bucket × model, by model/chat/source), `events`, `clear` | FR-1, FR-4, FR-6, FR-7, NFR-4 |
| engine | `crates/evo-engine/src/usage_log.rs` | Recorder (writer thread, retries, flush), `UsageTap` emitter, `record(message, source)` | FR-1, FR-2, FR-3, NFR-1, NFR-2, NFR-3 |
| engine | `crates/evo-engine/src/session.rs` (tap around the broadcast emitter), `crates/evo-engine/src/host.rs` (start in RPC mode with `--session-id`, flush at exit), `crates/evo-engine/src/agent_tool.rs`, `crates/evo-engine/src/child_agents.rs`, `crates/evo-engine/src/side_questions.rs` | Feed responses to the recorder | FR-1, FR-2, NFR-3 |
| engine | `crates/evo-engine/src/rpc/protocol.rs` `model_descriptor` | `cost`, `costConfigured` on every model | FR-5 |
| desktop shell | `apps/desktop/src-tauri/src/db.rs` | `usage_summary`, `usage_events` (blocking thread), `usage_clear` | FR-4, FR-6 |
| desktop UI | `apps/desktop/src/stores/usage-store.ts`, `apps/desktop/src/features/usage/{usage-page.tsx,usage-charts.tsx,analysis.ts}`, `apps/desktop/src/stores/ui-store.ts` (`usageOpen`), `apps/desktop/src/features/shell/app-sidebar.tsx`, `apps/desktop/src/app/app.tsx`, chart colours `--viz-*` in `apps/desktop/src/index.css` | The page, its charts, the efficiency figures, observations and price check | FR-4, FR-6, FR-7, FR-8, FR-9 |

### 3.3 Interfaces

Model descriptor (`get_available_models`), added fields:

```json
{ "cost": { "input": 3, "output": 15, "cacheRead": 0.3, "cacheWrite": 3.75,
            "tiers": [{ "input": 6, "output": 22.5, "cacheRead": 0.6, "cacheWrite": 7.5, "inputTokensAbove": 200000 }] },
  "costConfigured": true }
```

USD per million tokens. Older engines omit both; the page then shows "—".

Tauri commands (camelCase JSON, `evo_store::usage` types):

```ts
usage_summary({ query: UsageQuery }) -> UsageSummary
usage_events({ query: UsageQuery, beforeId?: number, limit?: number }) -> UsageEvent[]
usage_clear() -> number
type UsageQuery = { fromMs?, toMs?, chatId?, providerId?, modelId?, source?, bucket?: "hour" | "day" | "week" }
// UsageSummary = { totals, bucket, series: [{ bucket, providerId, modelId, ...totals }], byModel, byChat, bySource, firstMs }
// totals also carry errors, costErrors, timed, timedMs, timedOutput
```

### 3.4 Data and storage

Migration 8, `usage_events` (STRICT): `id`, `at_ms`, `chat_id` (no foreign
key: spend outlives its chat), `source` (`chat|subagent|plugin|side`, CHECK),
`provider_id`, `model_id`, `input`, `output`, `cache_read`, `cache_write`,
`reasoning`, `cost_input`, `cost_output`, `cost_cache_read`,
`cost_cache_write`, `cost_usd`, `stop_reason`. Indexes on `at_ms` and
`(chat_id, at_ms)`. Migration 9 adds `duration_ms` (request out to last
token; NULL when unknown). Time buckets are computed at query time on the
local clock (`strftime('%Y-%m-%d %H', …, 'localtime')` for hours, `date(…)`
for days, the Monday on or before for weeks) rather than kept in a view, so
"today" is the reader's local day. No pruning: a row is ~100 bytes; Clear
history empties it.

### 3.5 Behaviour

- The desktop starts every chat's engine with `--session-id <chat id>`;
  `host.rs` calls `usage_log::start(chat id)` in RPC mode. Until `start`,
  `record` is a no-op (NFR-3).
- `UsageTap` wraps the session's broadcast emitter, so it sees every event of
  the chat's agent loop synchronously (no broadcast lag) and survives
  `/reload`, which re-wraps the same emitter. Child harnesses get their own
  emitters, so a subagent's responses are never counted twice.
- `record` builds a row and sends it on a channel; empty responses (no
  tokens, no cost) are skipped. The writer drains what is queued, writes it
  in one `BEGIN IMMEDIATE` transaction on a fresh connection, retries 3× with
  a growing pause, then drops the batch with a warning.
- A response's duration is the time from its provider stamp
  (`AssistantMessage.timestamp`, set when the request goes out) to
  recording; missing stamps or more than an hour count as unknown. Speed is
  output tokens over that whole time, so it includes reading the prompt.
- At exit the RPC host waits up to 3 s for the writer (`flush`).
- The Usage page loads on open and every 15 s; only the newest request's
  answer is applied. "Auto" grouping uses hours while the covered span is
  under three days, weeks past four months, days otherwise.
- Charts colour the four most expensive models with a fixed categorical
  order (validated for colour-vision deficiency on both themes) and fold the
  rest into a grey "Other"; the legend, hover values and the tables carry the
  same numbers, so colour is never the only cue.
- Cache savings and the price check use today's models.dev base rates
  (long-context tiers aside); recorded costs are never re-priced.

### 3.6 Errors and edge cases

- Database locked past the busy timeout three times: the batch is dropped
  and logged; chats' own totals are unaffected.
- Engine killed mid-write: at most the responses of the last moments are
  lost.
- Errored or aborted responses that used tokens are recorded with their stop
  reason (the provider charged them); the page marks them.
- Models with no models.dev price cost $0; the page shows "No price" (or
  "Free" when models.dev says so).
- A deleted chat's rows show as "Deleted chat".

### 3.7 Security and trust

No new inputs from models or tools: rows are built from provider usage
numbers. `evo.db` still holds no secrets. Nothing is sent off the machine.

### 3.8 Configuration

None. Recording is on for every desktop chat; Clear history on the page
empties it.

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Record from the desktop on turn finish (like `chats.record_turn`) | Loses per-model detail of subagents (their usage reaches the UI folded into a tool result) and misses responses while no window listens. |
| Wrap every `Provider` to observe streams | Catches compaction too, but means re-piping every event stream in `evo-runtime`; the emitter tap covers the calls that matter with one small type. |
| A subscriber on the broadcast channel | A lagging receiver skips events; `MessageEnd` must not be lost. |
| Store prices per row | The provider already turned price into cost; today's price comes from the live catalog. |

## 5. As-built notes

- The planned shape in the [Application database](../app-database/plan.md)
  design (`usage_events(id, session_id, …, at)` + a rollup view, written
  from `agent_end`) became: `chat_id`, `at_ms`, a cost split and `source`,
  written per response from the engine, and day rollups computed in the
  query.
