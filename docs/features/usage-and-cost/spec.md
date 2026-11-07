# Usage and cost history — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-store`, engine, protocol (model descriptor), desktop shell, desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Application database](../app-database/spec.md) |

## 1. Summary

evo keeps a history of every model response a chat gets — its tokens, how
long it took and what it cost — and shows it on a Usage page (sidebar →
**Usage**): totals and rates, a stacked chart over time by model (hourly,
daily or weekly), observations worth acting on, each model's efficiency (cost
per response and per 1k output tokens, speed, cache use, failures) against
today's models.dev price, what the same tokens would cost on other models,
and spend by chat and source. Before this feature each chat only kept running
totals, so nobody could see where the money went across chats, models or
days, or whether a model was worth its price.

## 2. Scope

### 2.1 Goals

- Record each response's usage and cost at the moment it finishes, from the
  engine, for the chat's own agent, its subagents, plugin child runs and side
  questions.
- Show spend over time, by model, chat and source, and the cost split into
  input, output, cache reads and cache writes.
- Show each model's current models.dev price (per million tokens) next to
  what it cost, and flag models with no price.
- Keep everything on this computer, in evo's local database.

### 2.2 Non-goals

- Spend limits or alerts (planned on top of this history; see
  [Application database](../app-database/spec.md) and the unticked phase in
  [tasks.md](tasks.md)).
- Plan usage of subscription providers (their plan quotas): that lives in
  **Settings → Providers**.
- Re-pricing history when models.dev changes a price: a row keeps the cost it
  was charged at; the page shows today's price beside it.
- Sending telemetry anywhere. Nothing leaves the machine.

## 3. User scenarios

### US-1 See where the money went (priority P1)

A person using evo with paid models wants to see what their chats cost over
time, by model, by chat and by source so that they know where the money goes.

Acceptance scenarios:

1. **Given** a new chat, **when** a prompt finishes and the person opens
   **Usage**, **then** the chat's cost shows and matches the turn footer.
2. **Given** a history of responses, **when** the person picks Today / 7 /
   30 / 90 days / All time or a model, **then** totals, the chart over time,
   cost by part, by source, by chat and the latest 50 responses follow the
   choice.
3. **Given** the chat list on the page, **when** the person clicks a chat,
   **then** that chat opens.

### US-2 Judge whether a model is worth its price (priority P2)

A person choosing between models wants each model's efficiency, today's
price and what the same work would cost elsewhere so that they can pick a
cheaper or faster model.

Acceptance scenarios:

1. **Given** responses from a model, **when** the person opens **Usage**,
   **then** the model's cost per response, per 1k output tokens, speed,
   latency, cache use and failures show beside today's models.dev price.
2. **Given** a model's recorded token mix, **when** the person looks at the
   price check, **then** the same tokens are priced on other models, cheapest
   first, with the difference.
3. **Given** spend patterns worth acting on (for example a cold cache or a
   cheaper model with the same tokens), **when** the page loads, **then** an
   observation names it.

### US-3 Clear the history (priority P3)

A person wants to empty the usage history so that they can start counting
afresh.

Acceptance scenarios:

1. **Given** a recorded history, **when** the person uses Clear history,
   **then** the page shows no responses; chats' own totals are unchanged.

### Edge cases

- A deleted chat's spend stays in the history and shows as "Deleted chat".
- Errored or aborted responses that used tokens are recorded (the provider
  charged them) and marked on the page.
- Responses with no tokens and no cost are not recorded.
- A model with no models.dev price costs $0 and shows "No price" (or "Free"
  when models.dev says so).
- An older engine that sends no prices: the price shows "—".
- A locked database or an engine killed mid-write can lose the last few
  responses; chats' own totals are unaffected.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Each finished response of a chat's agent is recorded with provider, model, tokens (input, output, cache read/write, reasoning), cost split and total, stop reason, time and chat. | Given a chat started by the desktop, when a prompt finishes, then a record with the response's usage and source "chat" exists. |
| FR-2 | Subagents, plugin child runs and side questions are recorded with source "subagent", "plugin" or "side", attributed to the chat. | Each kind of run maps to its source. |
| FR-3 | The cost recorded is the one the provider computed from models.dev prices (tiers, 1h cache writes included). | The recorded cost equals the response's total cost. |
| FR-4 | The Usage page shows totals, spend/tokens/responses over time stacked by model (hour, day or week; Auto picks by span), cost by part, by source, by chat (opens it) and the latest 50 responses, for Today / 7 / 30 / 90 days / All time, filterable by model. | Checked in the running app. |
| FR-5 | The engine's model list carries each model's price. | Every model in the list has a price and says whether one is configured. |
| FR-6 | The history can be cleared; deleting a chat keeps its spend in the history. | Clear history empties it; a deleted chat's records remain and show as "Deleted chat". |
| FR-7 | Model efficiency: per model cost per response, cost per 1k output tokens, paid per 1M tokens, average prompt and output, cache hit and what caching saved at today's price, output tokens/s and latency, failure rate and its cost, beside today's models.dev price; bar charts for the first three. | Checked in the running app. |
| FR-8 | Observations: prompt-heavy spend, a cold cache on a model that discounts cached tokens, price gaps between models, speed gaps, failed responses, unpriced models, spend outside the chats. | Checked in the running app. |
| FR-9 | Price check: a model's recorded token mix priced at every priced model of its provider (and the other models in the history), cheapest first, with the difference. | Checked in the running app. |
| FR-10 | Compaction and branch summaries are recorded with source "compaction", attributed to the chat. | Given a chat that compacts, when the summary finishes, then its tokens and cost appear under source "compaction". |
| FR-11 | Spend on providers billed by plan is labelled "API-equivalent", once the provider catalog marks which providers are plan-billed. | Given a plan-billed provider, then its spend shows as API-equivalent. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | A model turn never waits on the database. | Records are handed to a background writer; the turn does not wait. |
| NFR-2 | A locked database delays records, it does not lose them on the first try. | The writer retries a batch 3 times. |
| NFR-3 | Engines without a chat id (tests, other hosts) write nothing. | Recording does nothing until it is started with a chat id. |
| NFR-4 | Old databases upgrade; the chats' own totals are untouched. | An upgraded database has an empty history and unchanged chats. |

## 5. Success criteria

- SC-1 After a prompt, the person sees its cost on the Usage page and it
  matches the cost shown on the chat's turn.
- SC-2 The person can tell which model, chat, source and day any spend came
  from.
- SC-3 Recording usage never makes a model turn slower.
- SC-4 No usage data leaves the computer.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-07 — Q: Should compaction and branch summaries be recorded? → A: Yes;
  their usage is returned in the compaction result and recorded with source
  "compaction" (FR-10).
- 2026-11-07 — Q: How should spend on plan-billed (subscription) providers show?
  → A: Labelled "API-equivalent" once the provider catalog says which
  providers are plan-billed (FR-11).

## 7. History

- 2026-11-06 — Draft, built and verified in one change at the user's request.
- 2026-11-06 — Phase 1b: detailed charts and model efficiency analysis.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
