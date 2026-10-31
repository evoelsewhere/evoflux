# area-observability NOTES

Python source: `app/api/routes/observability.py`, `app/services/observability_service.py`,
`app/core/otel_retention.py`. Unit `observability` (service `otel_retention`, see
`server/routing.toml`). Contract tests: `contract-tests/observability/test_observability.py`
with the synthetic span set in `contract-tests/observability/fixtures/spans/` (all pass
against Python v3.1.1).

## Endpoints

All three are `GET` only (`405 {"detail":"Method Not Allowed"}` otherwise) and need auth
(`401 {"detail":"Unauthorized — EvoFlux access key required."}`, checked before query
validation; `?_token=` works).

| Endpoint | Query | Success | Errors |
|---|---|---|---|
| `GET /api/observability/summary` | `days` int 1..90, default 7 | `200` span aggregates (below) | `422` pydantic list `detail` |
| `GET /api/observability/traces` | `days` 1..90 (7), `limit` 1..200 (50), `offset` >= 0 (0) | `200 {"traces":[...],"limit","offset","total","has_next"}` | `422` |
| `GET /api/observability/traces/{trace_id}` | `days` 1..90, default **30** | `200 {"trace_id","spans":[...]}` | `404 {"detail":{"reason":"trace_not_found","trace_id":"<as given>"}}`; `422` |

`422` bodies are FastAPI's: `{"detail":[{"type","loc":["query",<name>],"msg","input","ctx"}]}`.
`days=0` is `greater_than_equal` (`ge: 1`, input `"0"`), `days=91` is `less_than_equal`
(`le: 90`, input `"91"`), `abc` is `int_parsing` without `ctx`. Several errors come back
together in parameter order `days`, `limit`, `offset`. Validation runs before the
lookup, so `/traces/x?days=0` is a `422`, not a `404`. `{trace_id}` does not match a
slash: `/traces/a/b` is `404 {"detail":"Not Found"}`.

### Summary body

`window_start`/`window_end` (ISO-8601 with `+00:00`, `end - start == days`), `sample_ratio`
(`OTEL_SPAN_SAMPLE_RATIO` clamped to 0..1, default 1.0), `totals`, `latency_ms`,
`daily_turns`, `time_series`, `bucket_size` (`hour` when `days == 1`, else `day`),
`by_model`, `cache_by_step`, `by_tool`, `tokens_by_model`. No spans in the window
(missing dir, empty dir, no file in the window) gives the zero body with `daily_turns`,
`time_series`, `by_model`, `cache_by_step`, `by_tool` and `tokens_by_model` all `[]`.
With spans, `time_series` is filled to a dense grid from the window start's bucket to
the window end's bucket (25 hourly buckets, or `days + 1` daily ones).

Span classes (by name, case-sensitive prefix match):

- turn: `agent_run%`;
- LLM call: not a turn and (`chat%`, `summarization_llm_call%`, `title_generation%`, or
  attribute `gen_ai.operation.name` in `chat`/`summarization`/`title_generation`);
- tool call: `execute_tool%`.

Totals sum usage over LLM calls only. `errors` is an alias of `failed_turns` (root turns
with status `ERROR`); `error_spans` counts every span with `ERROR`. Percentiles are
DuckDB `quantile_cont` (linear interpolation), rounded to 1 decimal; money is rounded
to 8 decimals; `usd_per_mtok = round(cost / ((input + output) / 1e6), 6)`; percents are
`round(part / total * 100, 1)`; `cache_percent` clamps cached to `0..input`;
`fresh_input_tokens` is `max(input - cached - cache_write, 0)`.

Ordering: `by_model` and `cache_by_step` by cost descending (then calls / input tokens
descending), `by_tool` by calls descending with **no tie-break** (equal call counts come
back in an unspecified order; the contract test sorts by name there), `tokens_by_model`
by bucket, provider, model. `tokens_by_model` drops groups with zero input and zero
output tokens; `by_model` keeps them. Missing provider, model or tool name attributes
group under `unknown`.

### Trace list body

One row per `agent_run` span, newest `end_time` first. Per-row usage is joined on
`trace_id` plus the run's `run_id` attribute, so two runs in one trace (team turns) do
not share totals; a child span with no `run_id` is attributed to the trace's only run
when there is exactly one. `error` is the root's status `ERROR` **or** any errored span
in that run. `start_ms`/`end_ms` are epoch ms, `duration_ms` and cost are rounded (1 and
8 decimals). `provider_model` is `null` unless both provider and model are present.
`total` counts agent_run spans in the window; an empty page past the end still reports
the real total. `has_next` is `offset + limit < total`.

### Trace detail body

Every span of the trace in the window, `ORDER BY start_time ASC` (ties unspecified).
The requested id is lower-cased, then `0x` is prepended unless it already starts with
`0x` (so `0X…`, `0x…` and bare hex all match), and compared with `lower(trace_id)`. The returned `trace_id` is the stored one. `attributes`
drops keys whose value is null (DuckDB unions the attribute schema across spans);
numbers stay numbers. `kind` defaults to `INTERNAL`, `status` to `UNSET`,
`parent_span_id` is `null` for roots.

## State, files, side effects

No DB, no in-memory state, no events, nothing written by the routes. Every request
re-reads `{EVOFLUX_STATE_DIR}/otel/spans/*.jsonl` (hourly partitions
`YYYY-MM-DD-HH.jsonl`, written by `app/core/otel.py`, which stays Python). Python
creates the `spans/` directory at start-up, so the missing-dir case only happens after
someone deletes it; both must give the empty bodies.

File selection: sorted `*.jsonl` whose **stem** compares `>=` the window start formatted
`%Y-%m-%d-%H` (lexicographic). Rows are then kept when `end_time IS NOT NULL` and
`end_time` is between the window start and now, in ns (`end_time` is epoch ns UTC; spans
without it are dropped). Span record keys: `name`, `trace_id` (`0x` + 32 hex),
`span_id` (`0x` + 16 hex), `parent_id`, `kind`, `start_time`, `end_time`, `duration_ms`,
`status`, `attributes`, `events`, `resource`. `read_json(..., union_by_name=true)`;
aggregates read `attributes` cast to `MAP(VARCHAR, VARCHAR)` and use `try_cast`, so a
non-numeric usage attribute counts as 0.

## Retention sweeper (`otel_retention.py`, spec for the Rust `spawn_otel_retention`)

Background task started by the lifespan (service name `otel_retention`, disabled by
`EVOFLUX_DISABLE_SERVICES`). Pinned for the Rust unit test on a temp dir:

| Item | Python behaviour |
|---|---|
| Interval | `OTEL_RETENTION_SWEEP_INTERVAL_HOURS`, default **24**, floor 1 h, as seconds (`hours * 3600`). One sweep **immediately** at start, then sleep the interval, repeat. |
| Span age | `OTEL_SPAN_RETENTION_DAYS`, default **30**, floor 1 |
| Metric age | `OTEL_METRIC_RETENTION_DAYS`, default **90**, floor 1 |
| Enabled | `OTEL_RETENTION_ENABLED`, default true; false only when the value (stripped, lower-cased) is not one of `1`, `true`, `yes`, `on` |
| Env parsing | an unparsable integer gives the default; a value below the floor is raised to it (`max(floor, v)`) |
| Roots | `{EVOFLUX_STATE_DIR}/otel/spans` and `{EVOFLUX_STATE_DIR}/otel/metrics` |
| File selection | `root.glob("*.jsonl")`: direct children only, no recursion; only regular files (`is_file`, a directory named `x.jsonl` is skipped and not counted); other extensions untouched |
| Age | file **mtime**, never the name. `cutoff = now - max_age_days * 86400`; deleted when `mtime < cutoff`; `mtime == cutoff` is kept |
| Guards | `max_age_days <= 0` or a missing root: nothing scanned, result `(0,0,0,0)` |
| Result | `scanned` (regular files seen), `deleted`, `errors`, `bytes_freed` (size of deleted files) |
| Errors | `stat` or `unlink` failure is counted in `errors` (unlink also logs `otel_retention_unlink_failed path error`), the sweep continues; a whole-sweep failure is logged `otel_retention_sweep_failed` and the loop goes on |
| Logs | `otel_retention_started span_days metric_days interval_h`, `otel_retention_disabled`, `otel_retention_swept ...` (info when something was deleted, debug otherwise). Keep these field names |
| Lifecycle | `start` is idempotent and a no-op without a running loop; `stop` cancels and awaits the task |

The sweep deletes spans before metrics, each with its own age. The Rust sweep must run the
blocking file work through `core::blocking` and honour the cancellation token.

## Suspected Python quirks (ported as-is, raise per section 9 if they matter)

- `by_tool` has no tie-break, so equal call counts order differently between calls.
- The trace list joins children to a turn through `run_id` only; spans with a `run_id` that
  matches no `agent_run` in a multi-run trace are in no row's usage.
- `get_trace` lower-cases the id for the query but a stored upper-case id still matches
  (the column is lower-cased too); the response keeps the stored spelling.
- Window edges use the backend clock (`datetime.now`), so a span ending after "now" is
  invisible until time passes.

## Pins check (callers outside the routes)

| Caller | Uses | Verdict |
|---|---|---|
| `app/api/app.py:44,93-101,379` | `start_otel_retention` / `stop_otel_retention` (lifespan) | owned by the Rust `spawn_otel_retention`; the unit's `services = ["otel_retention"]` in `routing.toml` makes Python skip it. No adapter: it only deletes files |
| `app/core/gateway_mode.py:34` | lists `otel_retention` as a service the gateway can disable | config only, no adapter |
| `app/core/otel.py:311-333,431-456` | **writes** the span and metric JSONL (`setup_otel`) | stays Python; Rust only reads the same files, no adapter. Hourly file names and the record keys above are the shared contract |
| `observability_service` (`list_traces`, `count_traces`) | compatibility wrappers, unused by the routes | no callers outside the service and its tests |

Nothing else imports `observability_service` or `otel_retention`.

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/routes/test_observability_route.py::test_returns_empty_payload_when_no_spans` | `test_summary_without_a_spans_dir`, `test_empty_spans_dir` |
| `::test_days_query_param_bounds` | `test_summary_days_zero`, `test_summary_days_91`, `test_summary_days_boundaries_are_accepted` |
| `::test_traces_list_returns_empty_when_no_spans` | `test_traces_without_a_spans_dir` |
| `::test_traces_list_returns_turn_rows` | `test_traces_newest_first_with_per_run_usage` |
| `::test_traces_list_respects_query_bounds` | `test_traces_validation_bodies`, `test_traces_boundaries_are_accepted` |
| `::test_trace_detail_returns_span_tree` | `test_trace_detail_orders_spans_by_start_and_keeps_attributes` |
| `::test_trace_detail_404_when_missing` | `test_trace_detail_unknown_id_is_404_with_the_given_id`, `test_trace_detail_without_a_spans_dir_is_404` |
| `tests/services/test_observability_service.py::test_summarize_returns_empty_when_spans_dir_missing` | `test_summary_without_a_spans_dir` |
| `::test_summarize_returns_empty_when_no_files_in_window` | `test_only_partitions_older_than_the_window_are_empty` |
| `::test_summarize_aggregates_turns_llm_tools` | `test_summary_one_day`, `test_summary_seven_days_adds_the_older_turn`, `test_summary_counts_title_generation_and_summarization_as_llm_calls` |
| `::test_summarize_survives_a_window_with_no_turn_spans` | `test_summary_survives_llm_spans_without_a_turn_span` |
| `::test_tokens_by_model_splits_each_bucket_by_model_and_cache_state` | `test_summary_one_day` (`tokens_by_model`) |
| `::test_tokens_by_model_clamps_a_span_reporting_more_cache_than_input` | `test_summary_bounds_the_cache_rate_and_fresh_tokens` |
| `::test_tokens_by_model_skips_a_model_that_reported_no_tokens` | `test_summary_bounds_the_cache_rate_and_fresh_tokens` |
| `::test_summarize_handles_missing_cache_read_tokens` | `test_summary_one_day` (orphan span has no cache keys), `test_summary_missing_attributes_group_as_unknown` |
| `::test_summarize_clamps_days` | n/a: the route rejects values outside 1..90 with 422, so the clamp is unreachable over HTTP (Rust may keep it as a service-level unit test) |
| `::test_summarize_reports_sample_ratio` | Rust unit test: `OTEL_SPAN_SAMPLE_RATIO` parsing and clamp (the harness allow-list passes no such env var, so no contract case) |
| `::test_to_dict_round_trips` | `test_summary_one_day` (full body) |
| `::test_list_traces_empty_when_no_files` | `test_traces_without_a_spans_dir` |
| `::test_list_traces_returns_one_row_per_agent_run` | `test_traces_newest_first_with_per_run_usage`, `test_traces_leave_out_orphan_spans` |
| `::test_list_traces_pagination` | `test_traces_pagination_boundaries`, `test_traces_offset_past_the_end_keeps_the_total` |
| `::test_list_traces_marks_trace_failed_when_child_span_errors` | `test_traces_newest_first_with_per_run_usage` (T1) |
| `::test_list_traces_does_not_duplicate_usage_across_team_runs` | `test_traces_newest_first_with_per_run_usage` (T3 rows) |
| `::test_list_traces_clamps_inputs` | n/a: same as `test_summarize_clamps_days` |
| `::test_get_trace_returns_none_when_missing` | `test_trace_detail_unknown_id_is_404_with_the_given_id` |
| `::test_get_trace_returns_all_spans_ordered` | `test_trace_detail_orders_spans_by_start_and_keeps_attributes`, `test_trace_detail_returns_every_run_of_a_shared_trace` |
| `::test_get_trace_strips_null_attributes_unioned_across_span_types` | `test_trace_detail_orders_spans_by_start_and_keeps_attributes` (spans differ in attribute keys) |
| `::test_get_trace_accepts_unprefixed_trace_id` | `test_trace_detail_accepts_unprefixed_and_uppercase_ids` |
| `::test_sparse_series_from_rows_tolerates_null_aggregates` | Rust unit test: null aggregates coerce to zero in the bucket rows (DuckDB-specific, not reachable over HTTP) |
| `tests/core/test_otel_retention.py::test_sweep_deletes_files_older_than_cutoff` | Rust unit test `spawn_otel_retention` sweep on a temp dir (age, 45 d deleted, 5 d kept, counts and bytes) |
| `::test_sweep_noop_on_missing_root` | Rust unit test: missing root gives zeros |
| `::test_sweep_boundary_keeps_exact_age_files` | Rust unit test: `mtime == cutoff` is kept, strict less-than deletes |
| `::test_sweep_respects_pattern` | Rust unit test: only `*.jsonl` direct children are selected |
| `::test_sweep_zero_max_age_is_noop` | Rust unit test: `max_age_days <= 0` scans nothing |
| `::test_sweep_skips_directories` | Rust unit test: a directory named `*.jsonl` is skipped and not counted |
| `::test_run_once_sweeps_both_spans_and_metrics` | Rust unit test: spans (30 d) and metrics (90 d) swept in one pass |
| `::test_run_once_honours_env_overrides` | Rust unit test: env overrides and floors, through `core` config rather than direct env reads |
| `::test_run_once_tolerates_empty_dir` | Rust unit test: no `spans/` or `metrics/` dir is fine |
| `::test_start_retention_disabled_env` | Rust unit test: disabled flag starts nothing |
| `::test_start_retention_runs_once_and_stops` | Rust unit test: one sweep at start, cancel stops it, 24 h interval after the first sweep (paused tokio clock) |

Extra contract cases beyond the Python tests: auth (missing, wrong, `?_token=`, auth
before validation), 405s, the exact `days` 0 and 91 `422` bodies, `int_parsing`, error
order for several bad parameters, `limit` 201, validation before lookup, a slash in
`trace_id`, an empty spans dir and a non-JSONL file, the 1/2/7/30/90 day windows, the
40-day-old trace against the default 30-day detail window, dense `time_series`, daily
buckets, uppercase and `0X` trace ids, concurrent reads, and a scrub check of the fixtures.

## Fixture and time handling

`fixtures/spans/*.jsonl` is synthetic (no real prompts, paths, keys or hosts; a test
greps for them). It is anchored at `2026-10-30T12:00:00Z`. `otel_fixtures.seed` shifts
every `start_time`/`end_time` and file name by a whole number of hours so the anchor
sits one hour before the current hour; expectations for dates and buckets come from
`Seeded.ms/day/hour_bucket`, never from the wall clock. Not covered by a contract test
(needs a controllable clock): a window edge falling inside a partition file.

Rust unit tests for L5b (not yet written): the retention rows above, `OTEL_SPAN_SAMPLE_RATIO`
clamp, null aggregate coercion and the service-level `days`/`limit` clamps.
