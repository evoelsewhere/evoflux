# area-settings-providers NOTES

Python source: `app/api/routes/settings.py`, `app/api/routes/auth.py`,
`app/api/schemas/settings.py`, `app/core/runtime_settings.py`,
`app/agent/sandbox_config.py`, `app/cli/seed.py` (`write_env_credentials`,
`install_seed`), `app/agent/providers/{catalog,model_discovery,model_registry,model_metadata,capabilities,thinking,registry,factory,plugin_registry}.py`,
`app/services/provider_usage.py`. Unit `settings-providers` (`server/routing.toml`;
pin breaker `adapter:settings-providers`). Contract tests:
`contract-tests/settings-providers/` (213 cases, all pass against Python v3.1.1;
snapshots under `snapshots/`).

The board row and `check_paths.py` name the lane `settings-providers`, so the crate
is `area-settings-providers` and the tests live in `contract-tests/settings-providers/`
(the task brief said `area-settings` / `contract-tests/settings`; the harness maps a
test folder to its unit by the board lane name, so the board name wins).

**Status:** Lb in slices. Ported: `/api/auth/**` (DS2-001; the OAuth flows stay
Python-owned, `KNOWN_DIFFERENCES.md` settings-providers) and the request-body
validator every route uses (`src/body.rs`, `src/models.rs`: FastAPI body parsing and
pydantic lax coercion, pinned by `tests/body_golden.json`, which
`tests/gen_body_golden.py` regenerates from the real pydantic models). The crate is
mounted in `units.rs` but not listed in `rust-ready.toml`: the unit stays on Python
until every slice and the adapter land. Lb sizing and dependencies are at the end.

## Scope: which routes the unit really serves

`/api/settings/**` and `/api/auth/**`, minus two more-specific prefixes that other
units own although the handlers sit in the same `settings.py`:

| Prefix | Owner | Here |
|---|---|---|
| `/api/settings/conductor/**` (`GET/PUT /conductor`, `connect`, `enroll`, `disconnect`, `sync`, `status`, `resources/{id}/approve`, `pull`) | `conductor` | not covered |
| `/api/settings/webbridge/**`, `/api/settings/computer-app/**` (`GET/PUT /webbridge`, `/webbridge/agent-browsing`, `/computer-app`) | `webbridge-browser` (`routing.toml` line 111; the brief only named conductor) | not covered; they share `settings.yaml` (below) |

## Endpoints

Every route: `401 {"detail":"Unauthorized — EvoFlux access key required."}` for a
missing or wrong bearer token, before validation and before the provider lookup (the
token is not accepted in the query string or as `Basic`). Validation errors are
FastAPI's `422 {"detail":[{"type","loc","msg","input",...}]}` (snapshots `*_422.json`).
Unknown paths inside the prefix are `404 {"detail":"Not Found"}`, wrong methods
`405 {"detail":"Method Not Allowed"}`, a trailing slash `307`.

| Endpoint | Behaviour | Errors |
|---|---|---|
| `GET /api/auth/check` | `200 {"ok":true}` | – |
| `GET /api/auth/{provider}/login` | SSE (`started`, `device_code`, `polling`, `token_acquired`, `verifying`, `success`, `failed`); runs `app.cli.commands.auth._PROVIDERS[...].login` in a thread, or a provider plugin's `login`; `?mode=browser` for `codex` | `404 Unknown OAuth provider '<id>'. Known: ['codex', 'copilot', 'xiaomi'].` |
| `POST /api/auth/{provider}/callback` | `{"code": str}` (`extra=forbid`) to a provider plugin's `oauth_callback`; `200 {"ok":true, ...success payload}` | `404 OAuth callback unsupported for '<id>'` (also for codex/copilot); `400` plugin failure; `422` (validation precedes the 404) |
| `GET/PUT /sandbox` | `sandbox.yaml`; `PUT` strips and drops blank patterns, keeps duplicates and order | `422` on invalid YAML (`Invalid YAML in <path>: ...`); body `422` |
| `GET/PUT /context` | `ContextSettings` overrides; `null` is the built-in; `defaults`, `coding_defaults`, `max_tokens`, `context_ratio` are derived and ignored on write; `ignored[]` lists this section's rejected hand-edited values | `422` (file unreadable, or body out of range) |
| `GET/PUT /version-control` | one body split into `git` and `code_reviews` sections; every field required on PUT | same |
| `GET/PUT /team-spawn`, `/follow-up`, `/background-tasks`, `/response-style` | one small section each; a PUT replaces the section | `GET` of these four returns `500` when `settings.yaml` is unreadable (below) |
| `GET /providers` | whole catalog (201 providers in v3.1.1) with `is_saved`, `is_configured`, `is_reachable`, `saved_credentials` (non-secret fields only), `visible_models`, counts, `rank` | `500` when `settings.yaml` is unreadable |
| `PUT /providers/{id}` | writes credentials to `.env` and `os.environ`; `{"saved":bool,"is_first_provider":bool}` | `404 Unknown provider '<id>'`, `422` |
| `DELETE /providers/{id}` | removes the provider's variables from `.env` and `os.environ` (api_key, cloud_creds, plugin fields), deletes the OAuth token file (codex, copilot), no-op for local; `{"deleted":true}` always for a known id | `404` |
| `POST /providers/{id}/models` | live discovery with per-request overrides merged over saved credentials (blank fields ignored); `{"provider","models","source":"provider","model_costs","model_details"}`; discovery failure is `200` with `models: []` | `404`, `422` |
| `POST /providers/{id}/test` | one-token completion with temporarily overridden environment, under a process-wide lock; `200 {"ok","latency_ms","error"}` also on failure | `404`, `422` (`model` required) |
| `PUT /providers/{id}/visible-models` | trims, de-duplicates and sorts; an empty list removes `providers.<id>` | `404`, `422` |
| `GET /providers/{id}/usage` | live usage from the provider (needs OAuth token and network) | `404` unsupported / `Codex OAuth credentials not found.` / `Copilot ...`; `502 Provider usage unavailable.` |
| `GET /providers/{id}/logo` | SVG proxied from `models.dev`, cached in `<cache>/provider-logos/<source>.svg`, `?color=#rgb\|#rrggbb\|#rrggbbaa` replaces `currentColor` and `fill/stroke="black"`; headers `Cache-Control: public, max-age=604800`, strict CSP, `nosniff` | `404 Unknown provider` / `No logo for this provider` |
| `POST /seed` | installs bundled agents into `<config>/agents` (placeholder `__PROVIDER_MODEL__` replaced by `provider_model`); may download a tarball | `422` (`provider_model` must contain `:`), `502` download failure |

## Files read and written

| File | Written by this unit | Read by |
|---|---|---|
| `<CONFIG>/settings.yaml` | every section PUT, `visible-models` (load whole file, replace one section, atomic rewrite of **all** sections: unknown keys, comments and ordering are lost) | see "Caches" |
| `<CONFIG>/sandbox.yaml` | `PUT /sandbox` (never created by a GET) | `app/agent/sandbox.py`, `permission.py`, `outbound_redaction.py`, worktree tools |
| `<CONFIG>/.env` | `PUT/DELETE /providers/{id}` via `write_env_credentials` (merge: replace in place, append, drop on empty value, keep unknown lines; created with a 4-line header and `APP_ENV=production`) | Python `settings` at start-up (pydantic `env_file`), `ProviderCredentialStore` |
| `<CACHE>/provider-models.json` | manual remote catalog providers (`auto_connect=False`, not local) on `models` | same route, `agents.py` |
| `<CACHE>/provider-logos/<id>.svg` | logo route | logo route |
| `<CACHE>/codex_oauth.json`, `copilot_oauth.json` | deleted by `DELETE`; written by the OAuth login (CLI and `/api/auth`) | provider factory, usage |
| `<CONFIG>/agents/**.md` | `POST /seed`; `PUT /providers` backfills placeholder models | agents-skills unit |
| process `os.environ` | `PUT/DELETE /providers`, `/test` (temporarily) | `factory.require_api_key` reads it **first** |

## Caches other code reads

- `os.environ` mirrors the `.env` writes. `factory.require_api_key` and
  `ProviderCredentialStore.get` read the environment before the file, and the
  `settings` singleton is frozen at start-up. A key written by a Rust `PUT` reaches
  a running Python sidecar only after a restart: this is what `adapter:settings-providers`
  must bridge (Python needs a refresh hook that re-reads `.env` into `os.environ`).
  Rust's own consumers (`core::config::Settings`, chat-core) have the same
  start-up snapshot.
- `settings._provider_model_cache` (60 s TTL; manual providers persisted) and
  `_manual_model_ids` are imported by `app/api/routes/agents.py`
  (`_cached_provider_models`, `_provider_is_configured`, `_provider_saved_overrides`)
  for the agents registry. Python reads them in-process; a Rust unit cannot fill them.
- `_local_reachable_cache` (10 s), `_TEST_PROVIDER_LOCK`: route-local.
- `load_runtime_settings()` is uncached and called from 24 modules (dream, memory
  vector, webbridge policy every 60 s, hooks, code review, mcp, conductor, git
  routes). Writers revalidate by reading the file; none holds a stale copy except
  `app.state.runtime_settings` (start-up snapshot used by lifespan services) and
  `webbridge_manager.reload_policy()`, which `PUT /webbridge*` calls (webbridge unit).

## Other units that write the same files

| File | Other writers |
|---|---|
| `settings.yaml` | import `PUT /auto-sync` (`area-imports/NOTES.md`: rewrites the whole file); webbridge `PUT /webbridge`, `/webbridge/agent-browsing`, `/computer-app`; conductor `PUT /conductor` and `conductor/service.py` (4 saves); `app/api/routes/dream.py`; CLI `start`/`init`; `ensure_runtime_settings` |
| `.env` | `app/api/routes/team/reviews.py` (review tokens), `app/agent/providers/xiaomi/oauth.py`, CLI `init` |
| `sandbox.yaml` | only this unit |

No writer takes a file lock; Python is safe in-process only because every handler
loads, modifies and saves without an `await` in between, so the event loop
serialises them (contract tests `test_concurrent_*` pass for that reason). A Rust
port must hold one lock per file across read-modify-write, and mixed Python/Rust
writers (import, webbridge, conductor before their own cutovers) can still lose
each other's updates: cross-process atomic rename keeps the file valid, not merged.

## Pins check

`rg "routes.settings|routes import settings"` outside the unit: `app/api/app.py`
(mount) and `app/api/routes/agents.py:476` (imports four private helpers, above).
`rg "runtime_settings|sandbox_config|write_env_credentials"` shows the writers in the
table above. **Needs adapter**: `agents.py` calls `_cached_provider_models`,
`_provider_is_configured` and `_provider_saved_overrides` in process, and the whole
provider/OAuth/model stack (`catalog`, `model_discovery`, `plugin_registry`,
`factory`) is Python code other units call. Per `server/AGENTS.md` §9 La stops here
and does not add the adapter; it is a cutover prerequisite (`routing.toml` pin breaker).

## Odd behaviour (pinned as is unless noted)

- **Whole-file rewrite** on every settings PUT (above); `float` fields are written as
  `60.0`; the dump of every section is snapshot `settings_yaml_full_dump.json`.
- **Pydantic lax parsing:** `"3"` is an int, `2.0` an int, `"yes"`/`"no"` booleans in
  every body (`test_bodies_are_parsed_leniently_like_pydantic`); `2.5` or `"three"` are
  `422`. A Rust `serde` model must reproduce this.
- **Load tolerance:** `load_runtime_settings_report` drops each invalid value (up to
  a prune limit) and falls back to defaults; only YAML that does not parse or is not a
  mapping raises.
- **Suspected bug S0 (500 instead of 422):** `GET /team-spawn`, `/follow-up`,
  `/background-tasks`, `/response-style`, `/providers` and `PUT .../visible-models`
  do not catch the `ValueError` the other sections turn into `422`, so an unreadable
  `settings.yaml` is `500 Internal Server Error` (uvicorn then drops the keep-alive
  connection). Pinned by `test_unreadable_settings_file_is_500_on_unguarded_reads`.
- `is_configured` = key present **and** the provider listed models; `is_saved` =
  key present (for manual providers also needs a cached model list, so a saved
  catalog provider shows `is_saved: false` until its models are listed). Ollama is
  never contacted by `GET /providers`. `DELETE` on a local provider keeps its saved
  base URL.
- `api_key` goes to the **first declared credential**; `extra` values are written for
  every name in the body, declared or not (see S2). An empty value removes the line.
- `bedrock`'s `AWS_ACCESS_KEY_ID` is declared non-secret, so `saved_credentials`
  echoes it; the secret access key is declared secret and never is.
- `PUT /providers` for an OAuth provider ignores the key (`saved: false`).
- `is_first_provider` = no `.env`, or no known provider key in it.
- `POST /test` with no key uses the saved key (`os.environ`); the candidate key is
  restored after the call; failures are `200 {"ok":false}`.
- Context `defaults.summary_trigger_tokens` is derived from the model registry
  (`cost_optimal_prompt_token_threshold`, 333842 in v3.1.1); the test pins the other
  built-ins only.

## Security findings (for the owner; contract tests never print real values)

- **S1: a `422` echoes the request body.** `POST /providers/{id}/test` with
  `{"api_key": "<key>"}` and no `model` answers
  `{"detail":[{"type":"missing","loc":["body","model"],"input":{"api_key":"<key>"}}]}`:
  the key comes back to the caller that sent it (authenticated, same caller, but
  it lands in any client log or proxy that records responses). Pinned by
  `test_known_leak_a_missing_model_422_echoes_the_whole_request_body`; a Rust port
  that redacts `input` for these routes is a `KNOWN_DIFFERENCES.md` entry. Every other
  response (save, list, models, test, usage, delete, seed, sweeps of all GETs, `.env`-only
  storage, other files, backend log, desktop token) is clean in
  `test_secret_masking.py`.
- **S2: `PUT /providers/{id}` writes arbitrary variable names and values to `.env`
  and the process environment.** `extra: {"FOO": "x\nBAR=y"}` created two lines
  (`FOO=x`, `BAR=y`): both name and newline injection work, so a caller with the
  access key can set any variable (`PATH`, `PYTHONPATH`, `EVOFLUX_*`, `LD_PRELOAD`)
  in the running sidecar and persist it for the next start. Not pinned by a test (it
  would freeze a vulnerability); Lb must decide: allow-list names to the provider's
  declared credentials and reject control characters (a known difference), or port
  as is. Needs a security review.
- `.env` is written without restricting its permissions; the sidecar's temp file for
  `settings.yaml` is created with `mkstemp` (0600) and renamed over the target.
- The logo route fetches only IDs the catalog claims, refuses redirects, non-SVG,
  bodies over 256 KiB and active markup in the first 4 KiB; a cached file is served
  without re-validation.

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/test_settings_routes.py`: sandbox (4) | contract `test_sandbox_*` |
| …: `test_list_providers_*` (returns_catalog, marks_configured, no_ollama, router9, oauth_file) | contract `test_list_*`; OAuth-file and daemon-probe cases: Rust unit (needs the token file and a daemon) |
| …: `test_test_provider_*`, `test_list_provider_models_*` (404, empty, discovered, filters, no_environ) | contract `test_provider_test_*`, `test_models_*`, `test_candidate_credentials_never_outlive_the_request`; `filters_explicit_non_agent_capabilities`: Rust unit (catalog filter) |
| …: `test_save_provider_*`, `qwencloud`, `plugin_credentials`, `base_url_*`, 404 | contract `test_save_*`; `qwencloud` and `plugin_credentials`: Rust unit (plugin credential store is Python code, see Lb) |
| …: `test_install_seed_defaults_*` (4) | contract `test_seed_*`; download failure `502`: Rust unit (needs a failing downloader) |
| …: `test_local_provider_reachable_*` | Rust unit (probe cache, 10 s TTL, swallowed errors) |
| …: `test_get_*_provider_usage_*`, `test_codex_usage_*`, `test_copilot_usage_*`, `tests/services/test_provider_usage.py` | contract `test_usage_errors_without_credentials`; the success shapes: Rust unit (needs the provider's usage API, mocked) |
| …: `test_provider_configuration_reads_saved_config_env` | contract `test_list_marks_a_saved_key_and_never_echoes_it` |
| …: `test_save_provider_visible_models_*` | contract `test_visible_models_*` |
| …: `test_version_control_settings_round_trip` | contract `test_version_control_*` |
| …: `test_webbridge_*`, `test_computer_app_*`, `test_agent_browsing_*` | n/a: webbridge-browser unit |
| …: `test_*conductor*` (7) | n/a: conductor unit |
| …: `test_registry_*`, `test_saved_manual_provider_*`, `test_manual_provider_models_survive_a_restart`, `test_clearing_a_manual_provider_*`, `test_manual_ollama_*`, `test_unsaved_manual_provider_*`, `test_build_overrides_*` | Rust unit (registry and manual-model cache; the mock provider does not serve Ollama's `/api/tags`, so a manual listing has no contract case) |
| …: `test_get_context_*`, `test_put_context_*`, `test_context_overrides_reach_the_hooks`, `test_an_unrelated_section_survives_*` | contract `test_context_*`; `reach_the_hooks`: n/a (Python hooks) |
| …: `test_*response_style*`, `test_*background_tasks*` | contract `test_simple_section_*`, `test_a_hand_edited_invalid_value_*` |
| `tests/api/test_auth_routes.py` (9) | contract `test_auth_routes.py` for 404 and callback validation; SSE stream, browser flag, plugin login/callback success: Rust unit (stubbed login), n/a for the Python plugin loader |
| `tests/api/test_provider_logo.py` | contract `test_logo_*` (cache hit and tint); fetch, size and active-markup refusals: Rust unit |
| `tests/agent/test_sandbox_config.py` (30) | contract `test_sandbox_*`; file-level cases (atomic write, whitespace, legacy keys, extra forbid): Rust unit |
| `tests/api/test_gateway_mode.py`, `tests/core/test_desktop_auth.py` | n/a: authentication is `core::auth`, covered by `test_settings_auth.py` per route |

## Lb: size and dependencies

**Size: large, the biggest port so far, about 3,500 lines of non-test Rust, and it
should be sliced.** The routes are thin; the weight is behind them.

1. *Settings sections slice (small, independent):* sandbox, context, version-control,
   team-spawn, follow-up, background-tasks, response-style, visible-models. Needs the
   `RuntimeSettings` schema (19 sections, serde with lax coercion, per-field pruning on
   load, `yaml-rust2`-compatible emitter for the whole-file dump that matches PyYAML for
   `float`s, `'off'` quoting and key order). The same schema unblocks `area-imports`
   `PUT /auto-sync` (its blocker 2); do it once in a shared module.
2. *Providers slice (large):* the provider catalog (587 lines Python plus the bundled
   models.dev data), model discovery (880), model registry (1005), metadata and
   capabilities (900), thinking levels (956, `area-providers` has `thinking.rs` only),
   `.env` merge writer, usage, logo proxy, seed installer (tarball download and
   extract; needs the zip/tar crates, a shared dependency commit).
3. *Auth slice:* `/check` is trivial; OAuth login needs device-code and browser flows
   for codex, copilot and xiaomi (SSE).

**Depends on:** (a) the `adapter:settings-providers` Python bridge (refresh
`os.environ` after a Rust write; `agents.py` reading the provider cache; provider
plugins), a cutover prerequisite that La does not add; (b) **provider plugins are
Python modules executed in process** (`plugin_registry`: `exec_module` of `*.py`
files), which Rust cannot run, so plugin providers and plugin OAuth need either the
adapter or Python-owned routes for those ids; (c) the owner's decision on S1/S2;
(d) `build_provider` for `POST /test` is `area-providers`' factory, which must cover
every catalog transport; (e) shared dependency commits (`tar`/`flate2`, maybe `zip`);
(f) the `settings.yaml` schema shared with `area-imports`, webbridge and conductor
lanes, and a per-file write lock. Needs a security review (credentials, API keys,
environment injection).
