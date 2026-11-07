# Usage and cost history

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-store`, engine, protocol (model descriptor), desktop shell, desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-06 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | [0002 models.dev is the model database](../../architecture/decisions/0002-models-dev-is-the-model-database.md) |
| Related | [Application database](../app-database/sdd.md) (planned table "Usage and cost history") |

## 1. Summary

evo keeps a history of every model response a chat gets — its tokens, how
long it took and what it cost — and shows it on a Usage page (sidebar →
Usage): totals and rates, a stacked chart over time by model (hourly, daily or
weekly), observations worth acting on, each model's efficiency (cost per
response and per 1k output tokens, speed, cache use, failures) against today's
models.dev price, what the same tokens would cost on other models, and spend by
chat and source. Until now each chat only kept running totals, so nobody could
see where the money went across chats, models or days, or whether a model was
worth its price.

## 2. Scope

### 2.1 Goals

- Record each response's usage and cost at the moment it finishes, from the
  engine, for the chat's own agent, its subagents, plugin child runs and side
  questions.
- Show spend over time, by model, chat and source, and the cost split into
  input, output, cache reads and cache writes.
- Show each model's current models.dev price (per million tokens) next to
  what it cost, and flag models with no price.
- Keep everything on this computer, in `evo.db`.

### 2.2 Non-goals

- Spend limits or alerts (planned table `spend_limits`, app-database SDD).
- Plan usage of subscription providers (Codex, Copilot quotas): that is
  `get_provider_usage` in Settings → Providers.
- Re-pricing history when models.dev changes a price: a row keeps the cost it
  was charged at; the page shows today's price beside it.
- Sending telemetry anywhere. Nothing leaves the machine.
- Compaction summaries (they run inside `evo-harness` without an agent event);
  see section 9.

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Each finished response of a chat's agent is one `usage_events` row with provider, model, tokens (input, output, cache read/write, reasoning), cost split and total, stop reason, time and chat id. | Given a chat started by the desktop, when a prompt finishes, then a row with the response's usage and `source = chat` exists. |
| FR-2 | Subagents, plugin child runs and side questions record with `source` `subagent`, `plugin`, `side`, attributed to the chat. | Unit-checked at the call sites; `row_for` test covers the mapping. |
| FR-3 | The cost recorded is the one the provider computed from models.dev prices (tiers, 1h cache writes included). | The recorded `cost_usd` equals the response's `usage.cost.total`. |
| FR-4 | The Usage page shows totals, spend/tokens/responses over time stacked by model (hour, day or week; Auto picks by span), cost by part, by source, by chat (opens it) and the latest 50 responses, for Today / 7 / 30 / 90 days / All time, filterable by model. | Checked in the running app. |
| FR-7 | Model efficiency: per model cost per response, cost per 1k output tokens, paid per 1M tokens, average prompt and output, cache hit and what caching saved at today's price, output tokens/s and latency, failure rate and its cost, beside today's models.dev price; bar charts for the first three. | Checked in the running app. |
| FR-8 | Observations: prompt-heavy spend, a cold cache on a model that discounts cached tokens, price gaps between models, speed gaps, failed responses, unpriced models, spend outside the chats. | Checked in the running app. |
| FR-9 | Price check: a model's recorded token mix priced at every priced model of its provider (and the other models in the history), cheapest first, with the difference. | Checked in the running app. |
| FR-5 | The model list over RPC carries each model's price. | `get_available_models` descriptors have `cost` and `costConfigured`. |
| FR-6 | The history can be cleared; deleting a chat keeps its spend in the history. | `usage::tests::events_page_backwards_and_show_chat_titles`. |

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | A model turn never waits on the database. | Rows go through a channel to a writer thread. |
| NFR-2 | A locked database delays rows, it does not lose them on the first try. | Writer retries a batch 3 times (`the_writer_batches_retries_and_answers_flushes`). |
| NFR-3 | Engines without a chat id (tests, other hosts) write nothing. | `record` is a no-op until `start`. |
| NFR-4 | Old databases upgrade; the chats' own totals are untouched. | `tests::usage_events_arrive_empty_and_keep_existing_chats`. |

## 4. Context and constraints

- Every provider in `evo-ai` already fills `AssistantMessage.usage.cost` with
  `calculate_cost(&model.cost, &usage)`; `model.cost` comes from models.dev
  (`evo_runtime::models_dev`, [ADR 0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md)).
  Prices are never hardcoded.
- The desktop already adds each finished turn's cost to `chats.cost_usd`
  (`chats::record_turn`) — a per-chat total with no time or model axis.
- Engines open `evo.db` with short-lived connections and `BEGIN IMMEDIATE`
  writes ([app-database SDD](../app-database/sdd.md)).
- The engine owns agent logic; the shell reads `evo.db` for pages
  (like the run log).

## 5. Design

### 5.1 Overview

```text
agent loop ──MessageEnd──► UsageTap ─┐               (source = chat)
agent_tool ProgressEmitter ──────────┤ usage_log::record ─► channel ─► writer thread
child_agents Job::observe ───────────┤               (subagent / plugin / side)
side_questions Emitter ──────────────┘                                 │
                                                    evo.db usage_events ◄┘
desktop: Usage page ─► usage-store ─► invoke usage_summary / usage_events ─► evo_store::usage
         prices ◄── engine-store models ◄── get_available_models (cost from models.dev)
```

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| crate | `crates/evo-store/src/usage.rs`, `migrations/0008_usage_events.sql`, `0009_usage_durations.sql` | Table, `record`, `summary` (totals incl. failures and timing, series by bucket × model, by model/chat/source), `events`, `clear` |
| engine | `crates/evo-engine/src/usage_log.rs` | Recorder (writer thread, retries, flush), `UsageTap` emitter, `record(message, source)` |
| engine | `session.rs` (tap around the broadcast emitter), `host.rs` (start in RPC mode with `--session-id`, flush at exit), `agent_tool.rs`, `child_agents.rs`, `side_questions.rs` | Feed responses to the recorder |
| engine | `rpc/protocol.rs` `model_descriptor` | `cost`, `costConfigured` on every model |
| desktop shell | `apps/desktop/src-tauri/src/db.rs` | `usage_summary`, `usage_events` (blocking thread), `usage_clear` |
| desktop UI | `src/stores/usage-store.ts`, `src/features/usage/{usage-page.tsx,usage-charts.tsx,analysis.ts}`, `ui-store.ts` (`usageOpen`), `app-sidebar.tsx`, `app.tsx`, chart colours `--viz-*` in `index.css` | The page, its charts, the efficiency figures, observations and price check |

### 5.3 Interfaces

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

### 5.4 Data and storage

Migration 8, `usage_events` (STRICT): `id`, `at_ms`, `chat_id` (no foreign
key: spend outlives its chat), `source` (`chat|subagent|plugin|side`, CHECK),
`provider_id`, `model_id`, `input`, `output`, `cache_read`, `cache_write`,
`reasoning`, `cost_input`, `cost_output`, `cost_cache_read`,
`cost_cache_write`, `cost_usd`, `stop_reason`. Indexes on `at_ms` and
`(chat_id, at_ms)`. Migration 9 adds `duration_ms` (request out to last
token; NULL when unknown). Time buckets are computed at query time on the
local clock (`strftime('%Y-%m-%d %H', …, 'localtime')` for hours, `date(…)`
for days, the Monday on or before for weeks) rather than kept in a view, so
"today" is the reader's local day. No pruning: a row is ~100 bytes; Clear history
empties it.

### 5.5 Behaviour

- The desktop starts every chat's engine with `--session-id <chat id>`;
  `host.rs` calls `usage_log::start(chat id)` in RPC mode.
- `UsageTap` wraps the session's broadcast emitter, so it sees every event of
  the chat's agent loop synchronously (no broadcast lag) and survives
  `/reload`, which re-wraps the same emitter. Child harnesses get their own
  emitters, so a subagent's responses are never counted twice.
- `record` builds a row and sends it on a channel; empty responses (no tokens,
  no cost) are skipped. The writer drains what is queued, writes it in one
  `BEGIN IMMEDIATE` transaction on a fresh connection, retries 3× with a
  growing pause, then drops the batch with a warning.
- A response's duration is the time from its provider stamp
  (`AssistantMessage.timestamp`, set when the request goes out) to recording;
  missing stamps or more than an hour count as unknown. Speed is output tokens
  over that whole time, so it includes reading the prompt.
- At exit the RPC host waits up to 3 s for the writer (`flush`).
- The Usage page loads on open and every 15 s; only the newest request's
  answer is applied. "Auto" grouping uses hours while the covered span is
  under three days, weeks past four months, days otherwise.
- Charts colour the four most expensive models with a fixed categorical order
  (validated for colour-vision deficiency on both themes) and fold the rest
  into a grey "Other"; the legend, hover values and the tables carry the same
  numbers, so colour is never the only cue.
- Cache savings and the price check use today's models.dev base rates
  (long-context tiers aside); recorded costs are never re-priced.

### 5.6 Errors and edge cases

- Database locked past the busy timeout three times: the batch is dropped and
  logged; chats' own totals are unaffected.
- Engine killed mid-write: at most the responses of the last moments are lost.
- Errored or aborted responses that used tokens are recorded with their stop
  reason (the provider charged them); the page marks them.
- Models with no models.dev price cost $0; the page shows "No price" (or
  "Free" when models.dev says so).
- A deleted chat's rows show as "Deleted chat".

### 5.7 Security and trust

No new inputs from models or tools: rows are built from provider usage
numbers. `evo.db` still holds no secrets. Nothing is sent off the machine.

### 5.8 Configuration

None. Recording is on for every desktop chat; Clear history on the page
empties it.

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| Record from the desktop on turn finish (like `chats.record_turn`) | Loses per-model detail of subagents (their usage reaches the UI folded into a tool result) and misses responses while no window listens. |
| Wrap every `Provider` to observe streams | Catches compaction too, but means re-piping every event stream in `evo-runtime`; the emitter tap covers the calls that matter with one small type. |
| A subscriber on the broadcast channel | A lagging receiver skips events; `MessageEnd` must not be lost. |
| Store prices per row | The provider already turned price into cost; today's price comes from the live catalog. |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | Table, recorder, descriptor prices, Usage page | listed in 5.2 | Implemented 2026-11-06 |
| 1b | Durations, failures, time buckets by model, efficiency, observations, price check | listed in 5.2 | Implemented 2026-11-06 |
| 2 | Spend limits and alerts on top of the history | `spend_limits`, engine check before a run | proposed |

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1, FR-3, FR-5 | Real engine over RPC (`--session-id`, copy of a real `evo.db`): one prompt to `copilot/claude-sonnet-5.5`; the row's tokens and cost equal the response's `usage`; 37 of 41 models carry a models.dev price | passed (2026-11-06) |
| FR-2 | `cargo test -p evo-engine usage_log` | passed (2026-11-06) |
| FR-4 | Desktop app end to end (WebView2 DevTools): new chat, prompt, Usage page shows the chat's $0.011 matching the turn footer; range buttons, model filter, latest responses | passed (2026-11-06) |
| FR-6, NFR-4 | `cargo test -p evo-store` (`usage::tests::*`, `usage_events_arrive_empty_and_keep_existing_chats`) | passed (2026-11-06) |
| NFR-1, NFR-2 | `usage_log::tests::the_writer_batches_retries_and_answers_flushes` | passed (2026-11-06) |
| all | `cargo test -p evo-engine` (637 passed), `bun run typecheck`, `cargo check` in `src-tauri` | passed (2026-11-06) |
| FR-4, FR-7, FR-8 (1b) | Desktop dev app on the real `evo.db` (v9): a real codex/GPT-6.1 Sol response shows duration and speed (3.6 s, 5 tok/s), the efficiency table, an observation and the weekly chart; a stacked bar rendering only ~3% of its height was found and fixed (grow factors below 1) | passed (2026-11-07) |
| FR-7 (1b) | `cargo test -p evo-store` (`the_series_splits_buckets_by_model`, `errors_and_speed_are_counted`), `usage_log` duration cases | passed (2026-11-07) |
| FR-9, multi-model chart | Visual check with several models in the app | not run: the app was in use; checked by type and build only |

## 9. Open questions

1. Compaction and branch summaries are not recorded (they call the provider
   from `evo-harness` without an agent event). Proposed: return their usage
   in the compaction result and record it as `source = compaction`.
2. Subscription providers (Copilot, Codex) are billed by plan, yet models.dev
   prices their models; the page shows the API-equivalent cost. Proposed:
   label those providers' spend "API-equivalent" once the provider catalog
   says which providers are plan-billed.

## 10. As-built notes

- The planned shape in the app-database SDD
  (`usage_events(id, session_id, …, at)` + a rollup view, written from
  `agent_end`) became: `chat_id`, `at_ms`, a cost split and `source`, written
  per response from the engine, and day rollups computed in the query.

## 11. History

- 2026-11-06 — Draft, built and verified in one change at the user's request.
- 2026-11-06 — Phase 1b: detailed charts and model efficiency analysis.
