# Contract tests

Black-box HTTP tests that start a real backend process and compare its behaviour
with EvoFlux v3.1.1 (Python). The same tests run against Python, the Rust server
and the strangler gateway; a Rust lane counts as ported only when its area passes
against `TARGET=rust` as well as `TARGET=python`.

```bash
make contract AREA=health TARGET=python      # one area, one backend
make contract-all TARGET=python              # everything under contract-tests/
```

`TARGET` is `python` (default), `rust` or `gateway`. `rust` and `gateway` run
`server/target/debug/evoflux-server serve`, which Phase 0 task 11 builds; until
then those targets fail at start-up with a message naming the missing binary.
`make` needs the `contract` dependency group, which `uv run --group contract`
installs.

The backend runs with an allow-listed environment, `HOME`/`APPDATA` and the
working directory inside a per-test temp dir, so the developer's `.env`,
`DATABASE_URL`, provider keys and skills never reach it. `Backend.stop()` ends
only the backend process; on Windows `terminate()` does not take a process tree,
so the gateway target relies on the gateway's own tree kill (Phase 0 task 10).

## Layout

| File | Purpose |
|---|---|
| `backends.py` | `start_backend(target, data_dir, db_fixture)` starts the process, reads its `EVOFLUX_HANDSHAKE` line, returns `Backend` (`base_url`, `token`, `pid`, `stop()`, `log_tail()`). |
| `conftest.py` | Fixtures `backend` and `client` (fresh temp data/config/state/cache dirs per test, bearer token set), `snapshot`, and the `--snapshot-update` option. |
| `normalize.py` | `normalize(obj, rules)`: UUIDs become `<uuid:N>`, ISO-8601 timestamps `<ts>`, lists are sorted only at JSON paths a rule names. |
| `sse.py` | `collect_events(...)` and `assert_same_sequence(a, b)`; SSE is compared as event sequences, never raw bytes. |
| `harness/` | Tests of the harness itself (isolation, SSE timeout, normalizer, `openapi_diff.py`). |
| `mock_provider/` | `server.py` is a replaying model provider (OpenAI Chat Completions and Anthropic Messages streaming); `recordings/*.jsonl` are its scripts. |
| `fixtures/` | `upgrade/<tag>/` holds a seeded `evoflux.db`, `config/`, `wiki/` and `MANIFEST.json` for v3.0.0, the oldest schema (the builder can produce any v3.0.0 to v3.1.1 tag with `--tag`); `build_upgrade_fixtures.py` rebuilds them (git worktrees under `D:\evoelsewhere\.tmp-upgrade-tags`, removed afterwards). `fixtures.upgrade_fixture(tag)` returns a temp copy of the database. `config/.env` holds only the dummy key `sk-dummy-upgrade-fixture-0000`; `Backend` starts from the database alone, so config and wiki are for later phases. |
| `<area>/` | One directory per area, with `test_*.py` and `snapshots/`. |
| `openapi/python-v3.1.1.json` | Pinned `GET /openapi.json` from v3.1.1. |

## Rules

- A new test must pass against Python before it is merged.
- Never loosen an assertion, add a skip or widen normalization to make Rust pass.
- Snapshots are recorded from Python only: `uv run --group contract pytest contract-tests/<area> --snapshot-update`
  with `TARGET=python`, then reviewed in the diff.
- To start from a fixture database, override the `db_fixture` fixture in the area's `conftest.py`.
- Tests leave no state behind: every test gets its own temporary directories.

## OpenAPI diff

```bash
uv run python scripts/migration/openapi_diff.py <area> --candidate http://127.0.0.1:PORT/openapi.json --token <token>
```

It cuts the pinned spec and the candidate down to the paths the `[[unit]]` named
`<area>` owns in `server/routing.toml` (or `--routes '/api/health/**'`), inlines
component references so generated names do not matter, then runs `oasdiff breaking`
when installed and a strict structural diff. Exit 1 on any difference.

## Mock model provider

Fixture `mock_provider` starts a `MockProvider` on `127.0.0.1` (port 0) per test:
`base_url`, `load(recording)`, `requests` (streamed agent-turn requests, in
order) and `side_requests` (non-streamed ones such as title generation, which get
a fixed reply and never consume the recording). A recording is JSONL, one line
per item: `{"response": n}` starts the n-th response (request k gets response k,
the last repeats), `{"delay_ms": n}` sleeps, `{"event": "...", "data": {...}}`
is one SSE event (`event` is omitted for OpenAI), and
`{"status": 429, "headers": {...}, "body": {...}}` is a plain JSON error.
Recordings are shared fixtures: add them through a shared PR, secrets scrubbed.

`configure_backend_provider(client, mock, wire="openai"|"anthropic")` registers it
through the UI's own settings API: `PUT /api/settings/providers/{id}` with a dummy
`api_key` and the base URL override in `extra`, then `POST /api/settings/seed`
with `provider_model` so the bundled agents use the mock model. `wire="openai"`
registers the `router9` provider (`ROUTER9_BASE_URL`), because the `openai`
provider itself calls the Responses API, not Chat Completions; `wire="anthropic"`
registers `anthropic` (`ANTHROPIC_BASE_URL`). Chat goes in with
`POST /api/team/chat` (form `message`, returns `202 {"session_id"}`) and the turn
is read from `GET /api/team/{session_id}/stream` until `done`.

v3 behaviour worth knowing: a retryable 429 produces `rate_limit` and
`provider_status` events and no `error` event; a quota-style 429
(`insufficient_quota`, which v3 treats as non-retryable) ends the turn with no
event or message at all.
