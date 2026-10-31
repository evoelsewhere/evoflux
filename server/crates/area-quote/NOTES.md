# area-quote — NOTES

Unit `quote` (edge-stateless). Python sources: `app/api/routes/quote.py`,
`app/services/quote_service.py`.

## Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/api/quote` | desktop token (bearer or `?_token=`); missing or wrong → `401 {"detail": "Unauthorized — EvoFlux access key required."}` | `200 {"quote": str, "author": str}` |

- Query parameters are ignored (no validation error exists). Other methods: `405 {"detail": "Method Not Allowed"}` with `Allow: GET`.
- `/api/quote/` redirects (`307`) to `/api/quote` (FastAPI `redirect_slashes`; the route is registered on the empty path).
- The endpoint has no error response: every failure inside the service returns the fallback.

## Resolution order (`get_quote_of_the_day`)

1. **Cache.** `<EVOFLUX_CACHE_DIR>/quoteoftheday.json`, `{"date","quote","author"}`.
   Hit only when `date` equals today's **UTC** date as `YYYY-MM-DD` (string
   equality: yesterday, tomorrow and non-string dates all miss). A missing,
   empty/blank, non-JSON, non-object, field-missing or wrongly typed-date file
   is a miss (all exceptions are swallowed, debug log `quote_cache_read_failed`).
   Extra fields are ignored. A hit returns without any network call and does not rewrite the file.
2. **No `NINJA_API_KEY`** → fixed fallback `{"quote": "First, solve the problem. Then, write the code.", "author": "John Johnson"}`. Not cached.
3. **Fetch** `GET https://api.api-ninjas.com/v2/quoteoftheday` with `X-Api-Key`,
   10 s timeout. A list response uses element 0 (`{}` when empty); `quote`
   defaults to `""` and `author` to `"Unknown"`. Empty quote → fallback (not
   cached). Success → write cache (`ensure_ascii=False`, parents created, write
   errors only logged) and return. Any exception (HTTP status, network, JSON) → fallback.

## State, files, side effects

- Reads and writes one file in the cache dir; deleting it is safe. No DB, no
  event, no background task, no in-memory cache (the day check re-reads the file per request).
- Outbound HTTPS to API Ninjas only when a key is configured and the cache misses.

## Odd behaviour (port as-is)

- The cache date is UTC, not local; the day boundary is midnight UTC.
- A future-dated cache file is a miss, and a fetch then overwrites it.
- Concurrent cache misses each fetch and write; last writer wins (no lock).
- A today-dated cache entry missing `quote` or `author` is a miss (the KeyError is swallowed), so with a key configured it is refetched and overwritten. Contract tests run without a key, so they observe the fallback only.
- The fetched quote is not validated beyond emptiness (`author` may be any JSON value Pydantic accepts as `str`; a non-string raises and ends in the fallback).

## Pins check

`rg quote_service`: only `app/api/routes/quote.py` (the route) imports it, plus
`tests/services/test_quote.py`. `web/src` calls the route over HTTP. No other
caller: **no adapter needed**. Both backends read and write the same
`quoteoftheday.json`.

## Contract tests

`contract-tests/quote/test_quote.py`: success (cache hit, fallback), cache day
boundary (yesterday, tomorrow, a year ago), each unreadable-cache shape, auth
missing/wrong/query token, ignored parameters, 405, redirect, concurrent reads.
The fetch path (step 3) needs a key and a fake upstream the URL cannot be
redirected to, so it stays a Rust unit test with an injected HTTP client and clock (L2b).

## Test map

| Python test (`tests/services/test_quote.py`) | Covered by |
|---|---|
| `test_write_cache_creates_file`, `_creates_parent_dirs`, `_handles_unicode`, `_handles_write_error` | Rust unit (fetch path writes the cache); unicode round trip also contract `test_cache_for_today_is_served` |
| `test_read_cache_returns_none_when_file_missing` | contract `test_no_cache_returns_fallback` |
| `test_read_cache_returns_none_when_file_empty` | contract `test_unreadable_cache_falls_back[empty,blank]` |
| `test_read_cache_returns_quote_when_date_matches` | contract `test_cache_for_today_is_served` |
| `test_read_cache_returns_none_when_date_stale` | contract `test_cache_for_another_day_is_ignored` |
| `test_read_cache_returns_none_when_file_corrupted` | contract `test_unreadable_cache_falls_back[invalid-json,…]` |
| `test_read_cache_returns_none_when_missing_fields` | contract `test_today_cache_missing_fields_falls_back`, `test_unreadable_cache_falls_back[stale-no-fields,no-date]` |
| `TestGetQuoteOfTheDay::test_returns_cached_quote_on_hit` | contract `test_cache_for_today_is_served`, `test_cached_quote_is_stable_and_not_rewritten` |
| `::test_returns_fallback_when_no_api_key` | contract `test_no_cache_returns_fallback` |
| `::test_fetches_from_api_on_cache_miss`, `test_caches_fetched_quote`, `test_handles_api_list_response`, `_dict_response`, `_empty_api_list`, `_missing_quote_text`, `_missing_author`, `_http_error`, `_network_error`, `_json_decode_error` | Rust unit with injected HTTP client (L2b); n/a for contract: the upstream URL is fixed and tests run offline |
| `test_quote_endpoint_returns_200`, `_response_shape` | contract `test_no_cache_returns_fallback`, `test_cache_for_today_is_served` |
| `test_quote_endpoint_returns_fallback_on_error` | contract `test_unreadable_cache_falls_back` |
| (new) auth, methods, redirect, parameters, concurrency | contract tests named above |

## Phase 1 notes for L2b

- Same-day parity: the contract tests seed today's UTC date, so Python and Rust
  are compared on the same day; the midnight-UTC boundary is a Rust unit test on
  an injected clock (day N-1 miss, day N hit, day N+1 miss).
- `server/Cargo.toml` `members` does not list `crates/area-quote` yet (shared
  file); the orchestrator adds it when L2b builds the crate. Fetching needs an
  HTTP client crate: a new dependency, so L2b stops (workflow §9) and lists it
  here before adding it.
