# Web search and web fetch — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

`evo-web` tests run with `cargo test -p evo-web <name>`. The live backends
can be tried by hand with `cargo run -p evo-web --example try -- search
<query>` (also `-- exa <query>`, `-- wikipedia <query>`, `-- fetch <url>`).

### Phase 1 — Built-in `web_fetch` (layer 1)

Done when: the agent reads a public page as Markdown in windows, and private
targets fail before any request.

- [x] T1 [FR-2] Public-address guard: resolver and URL checks on every hop — `crates/evo-web/src/guard.rs` — check: `private_and_special_addresses_are_refused`, `urls_are_checked`
- [x] T2 [FR-1] [FR-6] [NFR-1] Fetch: redirects, limits, charset, cache, content types — `crates/evo-web/src/fetch.rs` — check: `urls_get_a_scheme_and_lose_fragments`, `charsets_are_honoured`, `private_targets_fail_before_any_request`
- [x] T3 [FR-1] HTML extraction to Markdown — `crates/evo-web/src/extract.rs` — check: `the_article_is_kept_and_the_chrome_dropped`
- [x] T4 [FR-1] [FR-3] [FR-7] `web_fetch` tool: 40,000-character windows, `<web_page url title>` wrapper, data-not-instructions description, `webTools` switch, no approval — `crates/evo-engine/src/web_tools.rs`, `crates/evo-engine/src/session.rs`, `crates/evo-engine/src/settings.rs` — check: manual check with a real model

### Phase 2 — Built-in `web_search`, keyless chain (layer 2)

Done when: a search answers from the first backend with results and falls
back when one is blocked.

- [x] T5 [FR-4] [FR-5] [FR-6] Search chain: order, domain filter, skip failed or paused backends, error listing all failures, 10-minute cache, snippet clip — `crates/evo-web/src/search.rs` — check: `domains_filter_the_results`, `wikipedia_is_skipped_when_it_cannot_serve_the_query`, `pauses_end`, `snippets_are_clipped_on_a_character`
- [x] T6 [P] [FR-5] [NFR-3] DuckDuckGo backend with pauses on block pages — `crates/evo-web/src/search/duckduckgo.rs` — check: `results_are_parsed_without_ads`, `domains_shape_the_query`, `blocks_are_recognised`
- [x] T7 [P] [FR-5] [NFR-3] Exa backend (hosted MCP, objective carries the limits, 60 s pause) — `crates/evo-web/src/search/exa.rs` — check: `entries_are_parsed`, `replies_are_read_as_json_or_events`, `the_objective_carries_the_limits`
- [x] T8 [P] [FR-5] Wikipedia backend — `crates/evo-web/src/search/wikipedia.rs` — check: `results_are_parsed` (in `search::wikipedia`)
- [x] T9 [FR-4] [FR-7] `web_search` tool: schema, numbered results, `details.source` — `crates/evo-engine/src/web_tools.rs` — check: manual check with a real model
- [x] T10 [FR-8] Transcript rendering: "Searched the web · query" with result links; "Read · host/path" with the page text — `apps/desktop/src/components/ai-elements/tool.tsx` — check: manual check in the running app
- [x] T11 [FR-1] [FR-5] Manual runner example — `crates/evo-web/examples/try.rs` — check: `cargo run -p evo-web --example try -- search <query>`

### Phase 3 — Keyed backends and fetch permissions (layer 2, proposed)

Done when: a keyed backend can be chosen and tested in **Settings → Web**,
and `web_fetch` asks per domain.

- [ ] T12 [FR-9] Write failing tests for a keyed backend trait (Brave, Tavily, Exa, Serper, SearXNG) — `crates/evo-web/src/search.rs` — check: the tests fail for the right reason
- [ ] T13 [FR-9] Implement the keyed backends; keys with the other credentials, hot-reloaded — `crates/evo-web/src/search/`, `crates/evo-engine/src/web_tools.rs` — check: T12 passes
- [ ] T14 [FR-10] Per-domain Allow / Ask / Block for `web_fetch`, **Always allow this domain** saved in settings — `crates/evo-engine/src/web_tools.rs`, `crates/evo-engine/src/settings.rs` — check: an engine test that a new domain asks first
- [ ] T15 [FR-9] [FR-10] **Settings → Web**: backend, key, **Test**, fetch domain list — `apps/desktop/src/features/settings/` — check: manual check in the running app

### Phase 4 — The provider's own search (layer 3, proposed)

Done when: a model with provider search uses it, its blocks survive the next
turn, and its citations and cost show.

- [ ] T16 [FR-11] Opaque `ProviderBlock { provider, raw }` kept in order and sent back unchanged; `pause_turn` handled — `crates/evo-ai/src/types.rs`, provider mappers — check: `evo-ai` tests with recorded provider streams
- [ ] T17 [FR-11] Citations parsed into a common shape; search cost from `server_tool_use.web_search_requests` in the turn's usage — `crates/evo-ai/src/` — check: `evo-ai` tests
- [ ] T18 [FR-11] **Use the model's own search** setting; send the provider's tool when the model supports it (models.dev data, else a per-provider list) — `crates/evo-engine/src/`, `apps/desktop/src/features/settings/` — check: manual check with a supporting model
- [ ] T19 [FR-12] Result list with favicon, domain and title; citations as numbered chips — `apps/desktop/src/components/ai-elements/tool.tsx` — check: manual check in the running app

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-web -- the_article_is_kept_and_the_chrome_dropped charsets_are_honoured urls_get_a_scheme_and_lose_fragments` | not run |
| FR-2 | `cargo test -p evo-web -- private_and_special_addresses_are_refused urls_are_checked private_targets_fail_before_any_request` | not run |
| FR-3 | Manual check: the result is wrapped in `<web_page …>` and the description says it is data | not run |
| FR-4 | `cargo test -p evo-web snippets_are_clipped_on_a_character`; manual check with a real model | not run |
| FR-5 | `cargo test -p evo-web` (search chain and backend tests) | not run |
| FR-6 | Code review of the caches in `fetch.rs` and `search.rs` | not run |
| FR-7 | Manual check: `webTools: false` removes both tools | not run |
| FR-8 | Manual check in the running app | not run |
| FR-9 | T12–T13 (not built) | not run |
| FR-10 | T14 (not built) | not run |
| FR-11 | T16–T18 (not built) | not run |
| FR-12 | T19 (not built) | not run |
| NFR-1 | Code review of the limits in `fetch.rs` | not run |
| NFR-2 | Manual check with a real model: it searched, read the official page, and answered with the source URL | passed (2026-11-06) |
| NFR-3 | `cargo test -p evo-web -- blocks_are_recognised pauses_end` | not run |
