# Rust HTTP/async server stack for replacing EvoFlux's FastAPI sidecar

Research date: 2026-10-30. Tool budget was limited (~15 calls), so many findings come from docs.rs pages and secondary search summaries. Claims marked "(prior knowledge)" in Inferences come from the researcher's background knowledge and were not re-verified in this session. Verify them before relying on them.

## 1. Framework choice: axum vs actix-web vs poem/salvo/rocket

### Takeaway
Use axum 0.8.x (latest 0.8.9, April 2026) on tokio + hyper 1 + tower 0.5 / tower-http 0.7. It has the most downloads, is the "default for new Rust APIs in 2026" per several guides, and its tower ecosystem is what the reverse-proxy, OpenAPI (utoipa-axum, aide) and Tauri integration crates build on. actix-web (4.12.x) is maintained and possibly 10–15% faster in synthetic benchmarks, but that is irrelevant for a local single-user desktop backend. No reliable 2026 head-to-head benchmark exists, and TechEmpower was archived in March 2026.

### Cited Findings
- Latest axum is v0.8.9 (released 14 Apr, 2026 per Dependabot PR dated 2026-04-27); axum-extra v0.12.6, axum-core v0.5.6. No 0.9 is announced on the releases page and no breaking changes are planned. — [axum GitHub releases](https://github.com/tokio-rs/axum/releases); [releasealert.dev](https://releasealert.dev/github/tokio-rs/axum)
- axum 0.8 was released January 2025. Its main breaking change from 0.7: path syntax `/:id` became `/{id}`. 0.8.8 fixed compilation on recent nightly. — [releasealert.dev](https://releasealert.dev/github/tokio-rs/axum) (secondary)
- actix-web 4.11.0 was prepared on 2025-05-10 (added `HttpServer::shutdown_signal()` and `Logger::log_level()`). It was superseded by 4.12.0/4.12.1; 4.12.0 makes `HttpResponseBuilder::streaming()` default to `application/octet-stream`. — [actix-web commit](https://git.vbrandl.net/actix/actix-web/commit/2c55d659dda7852f890fec71c7489e1bfce9e502); [Fedora packages](https://packages.fedoraproject.org/pkgs/rust-actix-web/rust-actix-web-devel/fedora-43.html); [dependabot record](https://dependabot.ecosyste.ms/hosts/GitHub/repositories/GalvinPython%2Flatest-uploads-api/issues/46)
- Benchmark claims conflict. One article says actix-web is roughly 10–15% faster under heavy load; another lists ~780K req/s for axum vs ~850K for actix. A page citing "Actix Web 5.0" numbers is unreliable because no 5.0 exists. — [reintech 2026 comparison](https://reintech.io/blog/axum-vs-actix-web-vs-rocket-rust-framework-comparison-2026); [codercops 2026](https://blog.codercops.com/blog/axum-actix-rocket-rust-web-frameworks-2026); [jisaku glossary](https://jisaku.com/glossary/rust-web-framework) (discount)
- TechEmpower FrameworkBenchmarks was archived (read-only) on GitHub in March 2026. — [codercops 2026](https://blog.codercops.com/blog/axum-actix-rocket-rust-web-frameworks-2026) (secondary; verify on github.com/TechEmpower)
- Reported downloads: about 462M lifetime for axum vs about 80M for actix-web. Guides call axum the default for new Rust APIs in 2026 and call all three (axum/actix/rocket) production-grade. — [depscope compare](https://depscope.dev/compare/cargo/actix-web-vs-axum-vs-rocket); [codercops 2026](https://blog.codercops.com/blog/axum-actix-rocket-rust-web-frameworks-2026)
- Production AI-agent use: Block's Goose ships `goose-server` (binary `goosed`), an Axum-based HTTP and WebSocket API with SSE streaming of agent responses. The Goose desktop app (Electron) talks to it as a local sidecar. This is architecturally the closest public analogue to EvoFlux. — [DeepWiki block/goose](https://deepwiki.com/block/goose); [mintlify goose server deployment](https://mintlify.com/block/goose/advanced/server-deployment) (secondary mirrors)

### Inferences
- For a localhost, single-user backend, framework throughput differences do not matter. What matters is ecosystem fit: tower middleware, hyper-native reverse proxying, and OpenAPI tooling. That favors axum.
- (Prior knowledge) actix-web runs its own per-thread (non-work-stealing) actix-rt, which complicates sharing tokio-based libraries and tower middleware. Poem has built-in poem-openapi but a much smaller community and a mostly single-maintainer bus factor. Salvo is smaller still. Rocket 0.5 has historically released slowly. None of them beats axum's maturity or ecosystem.
- Pin `axum = "0.8"`. Expect 0.9 at some point (not announced as of Oct 2026); the 0.7→0.8 history suggests mostly mechanical migrations.

### Gaps
- No authoritative 2026 benchmark (TechEmpower archived). The crates.io download figures come from an aggregator and were not checked on crates.io.
- Could not confirm whether OpenAI codex-rs, Zed or Warp expose an axum HTTP server. (Prior knowledge: codex-rs uses stdio/JSON-RPC for its app-server and MCP rather than an HTTP framework. Treat as unverified.)

## 2. SSE and WebSocket support, backpressure, disconnect and cancellation

### Takeaway
axum ships `axum::response::sse::{Sse, Event, KeepAlive}` and `axum::extract::ws` (tokio-tungstenite). Detect client disconnects by the response stream being dropped: wrap the agent-turn stream in a guard whose `Drop` fires a cancellation token, or `tokio::select!` on a `CancellationToken`. Do not rely on a write error. Backpressure is natural because hyper polls the stream only as fast as the socket drains. Use a bounded mpsc between the agent producer and the SSE stream.

### Cited Findings
- NVIDIA Dynamo's `dynamo-llm` (an LLM-serving HTTP layer on axum) wraps its SSE stream in a handle that is armed when streaming starts and disarmed on normal completion. If the stream is dropped early, `Drop` signals "connection closed unexpectedly". A monitor task then kills the engine context, bumps disconnect metrics and logs. Later versions use `tokio::select!` racing stream events against the context's stopped signal. — [dynamo-llm disconnect.rs](https://docs.rs/dynamo-llm/latest/src/dynamo_llm/http/service/disconnect.rs.html); [dynamo-llm 1.5.0 source](https://docs.rs/crate/dynamo-llm/1.5.0/source/src/http/service/disconnect.rs)
- Another project notes that axum drops the response stream when the client goes away even if no chunk was in flight, so drop-based detection is more reliable than waiting for a send error. — [turbospark-server cancel.rs](https://docs.rs/crate/turbospark-server/0.3.0/source/src/cancel.rs)
- Goose's axum server provides SSE streaming of agent messages plus WebSocket endpoints. — [mintlify goose](https://mintlify.com/block/goose/advanced/server-deployment)

### Inferences
- Pattern for EvoFlux agent turns: the handler creates a `CancellationToken` (tokio-util), spawns the agent turn task with a child token and a bounded `mpsc::channel(N)`, and returns `Sse::new(ReceiverStream).keep_alive(KeepAlive::default())` wrapped in a drop-guard that cancels the token. Decide explicitly whether the agent turn should keep running after the UI disconnects (FastAPI behaviour is usually "generator gets GeneratorExit/CancelledError"). If it should survive reconnects, decouple the turn from the HTTP stream with a broadcast/replay buffer and `Last-Event-ID`.
- (Prior knowledge) For axum WebSockets, call `socket.split()` and run reader and writer tasks under `select!`. Set `max_message_size`/`max_frame_size` on `WebSocketUpgrade`. Send pings for liveness detection, because closed-socket detection on Windows can lag without them.
- SSE must not pass through `tower_http::compression` unless it is configured to flush. Exclude `text/event-stream` from compression (see section 3).

### Gaps
- Did not fetch the official axum `response::sse` docs page in this session to quote KeepAlive defaults.

## 3. Reverse proxy (strangler gateway): HTTP + SSE + WebSocket passthrough

### Takeaway
Two viable options, both on hyper 1: (a) `axum-reverse-proxy` 2.2.0 as an axum fallback service (HTTP/1.1+H2, WebSocket upgrade, tower middleware, retry), or (b) a ~200-line custom proxy using `hyper_util::client::legacy::Client` that streams `Incoming` bodies through untouched, plus `hyper::upgrade::on` for WebSocket. For a strangler gateway where SSE fidelity is critical, a custom handler (or a vetted fork) gives the most control. Pingora is a standalone proxy server framework and too heavy to embed for this use.

### Cited Findings
- axum-reverse-proxy 2.2.0: depends on axum ^0.8, hyper ^1.0, hyper-util ^0.1, tower ^0.5. Supports HTTP/1.1 and HTTP/2 (ALPN) upstreams, preserves trailers, strips hop-by-hop headers per RFC 9110 §7.6.1 (keeps `te: trailers`), and sets X-Forwarded-For/Host only with `into_make_service_with_connect_info`. It handles WebSocket upgrades automatically: bidirectional text/binary, ping/pong, close frames, many concurrent connections. Optional `RetryLayer` replays only requests that never reached upstream. Round-robin and P2C load balancing; rustls by default. — [docs.rs axum-reverse-proxy](https://docs.rs/axum-reverse-proxy)
- The axum-reverse-proxy docs do not mention SSE/streaming-body behaviour. Its `Rfc9110Config/Layer` are deprecated, and its TLS install snippets still show "1.0". — [docs.rs axum-reverse-proxy](https://docs.rs/axum-reverse-proxy)
- Usage is `ReverseProxy::new("/ws", "http://upstream")`, which converts into an axum Router. — [docs.rs axum-reverse-proxy 1.1.0](https://docs.rs/axum-reverse-proxy/1.1.0/axum_reverse_proxy)

### Inferences
- Pitfalls with streaming bodies through a Rust proxy (prior knowledge, verify in tests):
  1. Never collect/buffer the upstream body. Pass `Incoming` through as `axum::body::Body::new(incoming)` so SSE chunks flush as they arrive.
  2. Exclude proxied routes, or at least `text/event-stream`, from `CompressionLayer`, which buffers per encoder block. Also exclude WebSocket upgrades from `TimeoutLayer` and request-body limits.
  3. Remove hop-by-hop headers but keep `Upgrade`/`Connection: upgrade` for the WebSocket path. Forward 101 and then splice both upgraded IOs with `tokio::io::copy_bidirectional`.
  4. Propagate client disconnects. When the downstream drops, dropping the upstream response body closes the upstream connection, which makes Starlette's `StreamingResponse` see a disconnect. Verify Python cancellation actually happens.
  5. Set upstream connect timeout but no total timeout on streaming routes. Disable the HTTP/1 idle-pool reuse quirks if the uvicorn keep-alive is short (uvicorn default keep-alive is 5s), to avoid "connection closed before message completed" races. Retry only idempotent requests.
  6. Inject the bearer token to the Python sidecar (a separate internal secret), and strip/replace the UI's token at the gateway.
- A golden-test harness that hits the same route on Python directly and via the gateway, then diffs status, headers, body and SSE event sequence, gives the strangler migration a safety net.

### Gaps
- No source found confirming axum-reverse-proxy's SSE flush behaviour; it needs a direct test or source read. Did not research pingora or hyper-reverse-proxy maintenance status in this session (prior knowledge: `hyper-reverse-proxy` has been stale for a long time; pingora 0.x is Cloudflare's proxy framework and is server-oriented, not an axum service).

## 4. OpenAPI generation and matching FastAPI's /openapi.json

### Takeaway
utoipa 5.x (latest 5.5.0) + utoipa-axum 0.2 (`OpenApiRouter`, `routes!`) is the most established code-first option and supports OpenAPI 3.1, which FastAPI emits. aide 0.15.1 (3.1.0 only, schemars-based; 0.16 alpha since Nov 2025) is the alternative, with tighter axum type inference. Neither will reproduce FastAPI's schema byte-for-byte automatically: component names (`HTTPValidationError`, `ValidationError`, `Body_<op>_<path>_<method>`), `operationId` formats (`<func>_<path>_<method>`), `title` fields per property, and `anyOf: [{...}, {type: null}]` for Optional are Pydantic-specific. Plan on normalizing and diffing with oasdiff in CI rather than expecting identity.

### Cited Findings
- utoipa: code-first, macro-based. It supports OpenAPI 3.1, has axum integration via utoipa-axum, and the latest version is 5.5.0. utoipa-axum 0.2: `OpenApiRouter` collects `#[utoipa::path]` handlers via `routes!`, and `split_for_parts()` returns `(Router, OpenApi)`. — [docs.rs utoipa 5.5.0](https://docs.rs/crate/utoipa/latest); [docs.rs utoipa-axum](https://docs.rs/utoipa-axum/); [github juhaku/utoipa](https://github.com/juhaku/utoipa)
- utoipa-axum 0.2.0 was last updated around January 2025 per one mirror (maintenance signal is uncertain). — [rust-digger](https://rust-digger.code-maven.com/crates/utoipa-axum)
- aide 0.15.0 was released 2025-06-04, with 0.16.0-alpha.1 on 2025-11-08. 0.15.1 requires axum ^0.8.1 and schemars ^0.9. "Currently only Open API version 3.1.0 is supported." — [lib.rs aide](https://lib.rs/crates/aide); [docs.rs aide 0.15.1 src](https://docs.rs/crate/aide/latest/source/src/lib.rs); [aide 0.16.0-alpha.2](https://docs.rs/crate/aide/0.16.0-alpha.2)
- Vespera is a newer axum-first, zero-config OpenAPI 3.1 generator. Its README contrasts utoipa ("manual annotations, more control") and aide ("more flexible"). It is young (0.1.x). — [docs.rs vespera](https://docs.rs/crate/vespera/0.1.27)
- oasdiff (Go CLI, based on kin-openapi, supports 3.0 and 3.1) has `breaking`, `changelog` and `diff` commands, and a GitHub Action whose `breaking` variant fails on WARN by default. The Tufin fork labels 3.1 support beta. — [github oasdiff/oasdiff](https://github.com/oasdiff/oasdiff); [oasdiff-action](https://github.com/oasdiff/oasdiff-action); [Tufin fork](https://github.com/TuFin/oasdiff)

### Inferences
- Recommended strategy for "Rust OpenAPI must match FastAPI's":
  1. Snapshot FastAPI's `/openapi.json` as the contract.
  2. Generate the Rust spec with utoipa, using `#[schema(as = ...)]` / explicit names to match Pydantic component names, and `#[utoipa::path(operation_id = "...")]` to copy FastAPI operationIds.
  3. Write a small normalizer (sort keys, drop `title`/`description` differences if accepted) and run `oasdiff breaking` plus a strict JSON diff in CI for ported routes.
  4. During the strangler phase, the gateway can serve a merged spec: the Python spec with ported paths replaced by the Rust-generated entries.
- With 361 endpoints, the alternative "contract-first" route is worth weighing: generate Rust types from FastAPI's openapi.json (e.g. typify/progenitor-style codegen, prior knowledge) and serve the stored JSON verbatim. That makes spec identity trivial and moves the risk to keeping handlers in sync.
- utoipa is the safer long-term bet given its adoption. aide's schemars 0.9/1.x basis matches serde attributes more automatically, which helps if JSON Schema output must track serde renames exactly.

### Gaps
- Did not verify utoipa's 2026 release cadence or the aide 0.16 stable release status (the alpha may have stabilized).

## 5. serde patterns for exact Pydantic/FastAPI JSON; validation and 422 bodies

### Takeaway
Reproducing FastAPI JSON is mostly discipline. Use `Option<T>` without `skip_serializing_if` to emit `null` (FastAPI default `response_model_exclude_none=False`), and use `skip_serializing_if` only where Python uses `exclude_none`/`exclude_unset`. Use the "double option" pattern (`Option<Option<T>>` via `serde_with::rust::double_option`) to distinguish missing vs null on PATCH input. Match Pydantic v2 datetime/UUID/enum formats explicitly. For 422s, hand-build FastAPI's `{"detail":[{"type","loc","msg","input","ctx"?,"url"?}]}` from validator/garde errors and serde_path_to_error, and copy Pydantic v2 type codes (`missing`, `int_parsing`, `string_too_short`...).

### Cited Findings
- FastAPI (Pydantic v2) default 422 body is a top-level `detail` array. Each item carries `type`, `loc` (e.g. `["body","price"]`, `["query","limit"]`), `msg` and `input`, plus `url` in some versions. v2 type codes differ from v1 (`int_parsing`, `missing` vs `type_error.integer`). Exact message wording can vary by version, so snapshot real responses. — [agentbench FastAPI error-handling doc](https://huggingface.co/spaces/Nomearod/agentbench/blob/main/data/tech_docs/fastapi_error_handling.md); [technetexperts 422](https://www.technetexperts.com/fastapi-422-unprocessable-entity-fix/amp/); [resumelens](https://www.resumelens.org/blog/fastapi/fastapi-validation-errors-customizing-responses-for-better-ux) (secondary sources)

### Inferences (prior knowledge, verify against EvoFlux's actual responses)
- Pydantic v2 datetime output is ISO 8601: naive datetimes have no offset, and UTC-aware ones serialize as `...Z` in pydantic-core ≥2.x (older versions used `+00:00`). Microseconds appear only when non-zero (`2026-10-30T12:00:00.123456Z`). Use `chrono` or `time` with a custom `serialize_with` to mirror this, and test against real FastAPI output. Python `float` `1.0` serializes as `1.0`, and serde_json also emits `1.0` for f64, which is fine. Integer-valued floats stored as int in Python become `1`, so check those.
- UUIDs: lowercase hyphenated in both (the `uuid` crate's serde default matches). Python `Enum(str)` uses the value, so map with `#[serde(rename = "...")]`/`rename_all`. Key order: FastAPI preserves model field-declaration order, and serde preserves struct field order. Use `serde_json` with the `preserve_order` feature (IndexMap) for `dict` passthroughs.
- Use `#[serde(deny_unknown_fields)]` only where Pydantic models set `extra="forbid"`. Pydantic's default ignores extras.
- Validation crates: `validator` (derive, long-standing) and `garde` (newer, context-aware, better nested-path reporting). garde's error paths map more cleanly to FastAPI's `loc` arrays. Neither emits Pydantic codes, so write an error-mapping layer. Use a custom axum extractor (`ValidatedJson<T>`) that also catches serde deserialization errors via `serde_path_to_error` to produce `missing`/`*_parsing` items with `loc: ["body", ...]`. Override axum's default `JsonRejection` (which returns 400/415/422 plain text) so every rejection returns FastAPI's JSON shape.
- Golden testing: record FastAPI responses for each ported endpoint and assert byte-equality (or canonical-JSON equality) in Rust integration tests.

### Gaps
- Did not fetch the official FastAPI/Pydantic docs for the exact current `url` field presence and datetime `Z` behaviour. Did not fetch validator/garde latest versions.

## 6. Panic isolation, timeouts, limits, tracing, graceful shutdown

### Takeaway
tower-http 0.7.1 provides everything needed as layers: `CatchPanicLayer` (turn panics into 500 JSON matching FastAPI's `{"detail":"Internal Server Error"}`-style), `TimeoutLayer`, `RequestBodyLimitLayer` (also axum's `DefaultBodyLimit`), `CorsLayer`, `TraceLayer`, `SetRequestIdLayer`/`PropagateRequestIdLayer`, `SetSensitiveHeadersLayer` (hide the bearer token in logs), `ValidateRequestHeaderLayer` (bearer auth), `CompressionLayer`, plus newer `metrics`, `csrf` and `on_early_drop` modules. Graceful shutdown is `axum::serve(...).with_graceful_shutdown(signal)`.

### Cited Findings
- tower-http latest is 0.7.1. Modules: `catch_panic`, `timeout`, `limit`, `cors`, `trace`, `compression` (br/deflate/gzip/zstd features, off by default), `request_id`, `sensitive_headers`, `auth`, `validate_request`, `set_header`, `normalize_path`, `metrics`, `csrf`, `on_early_drop`, `decompression`, `follow_redirect` and others. The docs do not mention how compression interacts with SSE. — [docs.rs tower-http](https://docs.rs/tower-http/latest/tower_http/)
- actix-web 4.11 added `HttpServer::shutdown_signal()` (for comparison). — [actix commit](https://git.vbrandl.net/actix/actix-web/commit/2c55d659dda7852f890fec71c7489e1bfce9e502)

### Inferences
- `CatchPanicLayer` only catches panics in the request future. Panics in `tokio::spawn`ed tasks surface as `JoinError`, so wrap background agent tasks in a supervisor that logs and converts `JoinError::is_panic()`. Consider `panic = "unwind"` (the default; do not set `abort` in release or CatchPanic is useless).
- Apply `TimeoutLayer` per-route group (non-streaming JSON routes) rather than globally, so SSE, WebSocket and proxy routes are not killed.
- The `on_early_drop` module (new in tower-http 0.7) is likely directly useful for client-disconnect metrics/cancellation. Check its docs.
- Prometheus: `metrics` + `metrics-exporter-prometheus`, or `prometheus-client`, behind a `/metrics` route (prior knowledge). Keep metric names identical to the Python `prometheus_client` names during the strangler phase so dashboards don't break.
- Shutdown: on Tauri exit, trigger a `CancellationToken`, then `with_graceful_shutdown` drains in-flight requests, then cancel SSE streams (they would otherwise block shutdown forever) and kill the Python child process. On Windows, use a Job Object (e.g. via `command-group`/`win32job`, prior knowledge) so Python dies if the Rust process crashes.

### Gaps
- No explicit source on tower-http 0.7 release date or breaking changes from 0.6.

## 7. Tokio best practices: avoiding executor blocking and an event-loop-lag watchdog

### Takeaway
Use `spawn_blocking` for filesystem-heavy, CPU-bound, sqlite (rusqlite) and sync-SDK work. Enforce it with clippy `disallowed_methods` (`std::fs::*`, `std::thread::sleep`, `reqwest::blocking`, `std::process::Command::output`). Detect long polls in development with tokio-console (`console-subscriber`, needs `--cfg tokio_unstable`). In production, run a lightweight lag watchdog: a task that ticks every 100ms and measures drift, plus `tokio::runtime::RuntimeMetrics` / `tokio-metrics`, exported to /metrics.

### Cited Findings
- tokio-console identifies the blocking task by its growing busy/poll time but cannot give function-level information. Naming tasks via the unstable task builder helps. — [tokio-rs/console discussion #410](https://github.com/tokio-rs/console/discussions/410)
- tokio-console warns about tasks whose first poll exceeds 1s and flags slow polls; the suggested fixes are spawn_blocking/block_in_place. — [carllerche tokio-console notes](https://hackmd.io/a4P75rj0RP6qettxAVzv8w); [compio console example](https://docs.rs/crate/compio/latest/source/examples/console.rs)
- Tokio PR #6256 proposed a sampling "black box" detector that fires when the runtime is blocked longer than a configurable threshold and can dump worker stack traces. — [tokio PR #6256](https://github.com/tokio-rs/tokio/pull/6256) (check whether merged)
- `tokio-blocked` hooks tokio's tracing instrumentation and logs warnings with poll duration, but can only report the spawn site. `hud` is an eBPF profiler (Linux-only, so not usable on Windows/macOS). — [docs.rs tokio-blocked](https://docs.rs/crate/tokio-blocked/latest); [hud](https://awesome.ecosyste.ms/projects/github.com%2Fcong-or%2Fhud)

### Inferences
- Watchdog design (cross-platform):
  - (a) A tokio task loops `interval(100ms)` and records `actual_elapsed - 100ms` as lag into a histogram gauge.
  - (b) A separate OS thread (`std::thread`) checks an `AtomicU64` heartbeat that the tokio task updates. If the heartbeat is stale for over N ms, it logs a warning with the current in-flight request IDs, and in debug builds captures backtraces.
  - (c) Expose `tokio_metrics::RuntimeMonitor` (busy ratio, `mean_poll_duration`, `max_poll_duration`) and `TaskMonitor` for per-route instrumentation.
  This mirrors Python asyncio "slow callback" debug warnings.
- Configure clippy.toml `disallowed-methods` and `disallowed-types` (e.g. `std::sync::Mutex` held across await, which `clippy::await_holding_lock` also catches). Enable `clippy::large_futures` to catch stack bloat from huge state machines.
- `tokio_unstable` is acceptable in debug/dev builds. Avoid relying on it in release, because unstable APIs can break.

### Gaps
- Did not confirm the merge status of tokio PR #6256 or current tokio version (prior knowledge: tokio 1.4x LTS lines).

## 8. How Tauri apps run a Rust backend: in-process vs sidecar

### Takeaway
Three patterns exist:
1. An in-process axum server spawned on `tauri::async_runtime` in `setup()`, bound to 127.0.0.1 on a random port.
2. `tauri-plugin-axum`, which serves an axum Router over a custom URI scheme with no TCP port, but does not support streaming, so it can't do SSE.
3. A separate sidecar binary declared in `externalBin` and spawned by the shell plugin.

For EvoFlux, the in-process axum gateway (pattern 1), which itself spawns Python as a child, is simplest. A separate Rust sidecar binary is better if crash isolation from the UI shell matters or if the backend must also run headless/CLI.

### Cited Findings
- An in-process example starts axum inside Tauri `setup` with `tauri::async_runtime::spawn(run_web_server())` and adds tower-livereload. It is dated 2024 (Tauri 1.5, axum 0.7), so it may be outdated. — [alanwsmith](https://www.alanwsmith.com/en/2b/nx/7i/oj/)
- `tauri-plugin-axum` (0.9.0) exposes an axum Router through `axum://localhost/<path>` (macOS/iOS/Linux) and `http://axum.localhost/<path>` (Windows/Android) without a TCP port. Custom protocols currently do not support streaming, and the plugin must be registered before any WebView is created. — [docs.rs tauri-plugin-axum](https://docs.rs/tauri-plugin-axum/latest/tauri_plugin_axum/); [tauri-plugin-axum 0.9.0](https://docs.rs/crate/tauri-plugin-axum/0.9.0)
- Sidecar pattern: the binary is declared in `externalBin` in tauri.conf.json, spawned from Rust, and the port is passed via env (`sidecar.env("PORT", ...)`). Lifecycle and stdout/stderr must be managed. — [codeforreal: Bun/Deno server in Tauri](https://hn.jakechampion.name/reader/https://codeforreal.com/blogs/using-bun-or-deno-as-a-web-server-in-tauri)
- Goose (Block) runs `goosed`, an axum server, as a separate process behind its desktop app. — [DeepWiki block/goose](https://deepwiki.com/block/goose)

### Inferences
- Because EvoFlux already has a sidecar architecture (Tauri, then the Python FastAPI process), the lowest-risk move is to replace the Python sidecar slot with a Rust gateway binary, `evoflux-server`. That binary then spawns Python as its own child, and the Tauri shell code changes little. Later, the gateway could be linked in-process as a library crate (`evoflux_server::run(config, shutdown_token)`) with no code changes, if the crate is structured that way from day one.
- Pros of in-process: one binary, shared memory, and no port handshake. Cons: a panic or abort, or blocking the shared runtime, can freeze the UI shell. Tauri's own async runtime is tokio, so give the server its own multi-thread runtime if co-hosted.
- Security on localhost: bind 127.0.0.1 only, use a random port plus a per-launch bearer token passed to the webview via a Tauri command, use a strict CORS allowlist (`tauri://localhost`, `http://tauri.localhost` on Windows), and check the Host header to resist DNS rebinding.
- Cross-platform notes: Windows needs a Job Object for child-process cleanup and a `CREATE_NO_WINDOW` flag for spawning Python. On macOS, notarization requires signing every sidecar binary. Tauri's `externalBin` requires target-triple-suffixed filenames (prior knowledge).

### Gaps
- Did not find a well-known open-source Tauri v2 app that embeds an axum server with SSE in production (candidates to check: Jan, Screenpipe, Hoppscotch desktop). Did not verify Zed/Warp internals.
