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

## Layout

| File | Purpose |
|---|---|
| `backends.py` | `start_backend(target, data_dir, db_fixture)` starts the process, reads its `EVOFLUX_HANDSHAKE` line, returns `Backend` (`base_url`, `token`, `pid`, `stop()`, `log_tail()`). |
| `conftest.py` | Fixtures `backend` and `client` (fresh temp data/config/state/cache dirs per test, bearer token set), `snapshot`, and the `--snapshot-update` option. |
| `normalize.py` | `normalize(obj, rules)`: UUIDs become `<uuid:N>`, ISO-8601 timestamps `<ts>`, lists are sorted only at JSON paths a rule names. |
| `sse.py` | `collect_events(...)` and `assert_same_sequence(a, b)`; SSE is compared as event sequences, never raw bytes. |
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
