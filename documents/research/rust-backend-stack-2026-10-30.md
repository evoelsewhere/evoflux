# Rebuild EvoFlux on axum, rusqlite and rmcp

EvoFlux should migrate to a **Rust gateway built on axum 0.8 + tokio + tower-http** that takes over the current Python sidecar's place in the Tauri shell. Python should remain behind it as a reverse-proxied child process, and routes should move over one at a time (a strangler migration) until Python serves only plugins, the `python` tool and skill scripts. The per-component picks are: **rusqlite** with one dedicated writer thread plus `query_only` reader connections, keeping today's single-writer design and **not adopting BEGIN CONCURRENT yet**; an **in-house provider layer** over `reqwest` and `eventsource-stream`; **rmcp** behind an internal wrapper crate for MCP; and the integration crates that OpenAI's codex-rs and Zed already ship (portable-pty, process-wrap, gix plus the git CLI, notify, ignore, keyring 3.6, pdfium-render, htmd, duckdb, croner, tracing). This matters because the two closest public analogues, Codex CLI and Block's Goose, are both Rust agent runtimes with axum- or tokio-based local servers. Each wrote its own LLM client layer and uses rmcp, so EvoFlux can copy proven architecture instead of betting on young frameworks. The biggest risks are not throughput, which is irrelevant for a single-user localhost backend. They are byte-level contract fidelity with FastAPI/Pydantic (361 endpoints, 422 bodies, SSE event sequences) and Windows-specific plumbing (ConPTY, Job Objects, keyring target names, sandboxing). The migration method should therefore follow published AI-assisted migration practice. Build and validate a dual-target "judge" test suite first. Then port routes behind the gateway in parallel lanes with a shared rulebook. Gate each unit with OpenAPI diffing, differential fuzzing and SSE event-sequence snapshots.

## Codex and Goose already validate one pick per component

The strongest evidence available is what production Rust agent apps actually depend on. Codex's workspace manifest lists `rmcp`, `portable-pty`, `gix`, `notify`, `ignore`, `keyring`, `landlock`, `seccompiler`, `tracing`, `wiremock` and `insta`. It does not list any third-party LLM client crate ([codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)). Goose likewise uses `rmcp` and its own provider trait over `reqwest` ([goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml)). Goose also ships `goosed`, an **axum HTTP/WebSocket server with SSE streaming of agent responses that its desktop app runs as a local sidecar**, which is architecturally the closest match to EvoFlux ([DeepWiki block/goose](https://deepwiki.com/block/goose)). The table below gives the recommended pick per component. The sections that follow justify each one.

| Component | Recommended pick | Main alternative / reason not chosen |
|---|---|---|
| HTTP framework | axum 0.8.x + tokio + hyper 1 + tower-http 0.7 | actix-web 4.12 (own runtime, smaller tower ecosystem) |
| SSE / WebSocket | `axum::response::sse` + `axum::extract::ws`, drop-guard + `CancellationToken` | — |
| Strangler proxy | Custom ~200-line hyper-util proxy (or `axum-reverse-proxy` 2.2 after an SSE flush test) | Pingora (standalone server, too heavy) |
| OpenAPI | utoipa 5.5 + utoipa-axum, diffed against FastAPI's spec with oasdiff | aide 0.15 (schemars-based), contract-first codegen |
| Validation / 422 | serde + `serde_path_to_error` + garde, custom `ValidatedJson` extractor emitting Pydantic v2 shapes | validator |
| Tauri hosting | Separate `evoflux-server` sidecar binary structured as a library crate | In-process axum; `tauri-plugin-axum` (no streaming) |
| SQLite | rusqlite (libsqlite3-sys 0.39, bundled SQLite 3.54) + writer thread + reader pool | sqlx 0.9; Diesel; SeaORM 2.0 (still RC) |
| Concurrent writes | Stay single-writer; revisit BEGIN CONCURRENT only on measured queue waits | Turso MVCC ("not production ready") |
| Migrations | Hand-rolled migrator bridging `alembic_version` (or refinery with a baseline) | rusqlite_migration (`user_version` collides) |
| LLM providers | In-house layer, 4–5 wire protocols, quirks in data | genai 0.7 (reference/fallback), rig 0.45 (framework churn) |
| SSE client parsing | `reqwest::bytes_stream()` + `eventsource-stream` 0.2.3 or a vendored parser | reqwest-eventsource (wrong auto-reconnect semantics) |
| Bedrock | `aws-sdk-bedrockruntime` | SigV4 over reqwest |
| MCP client | rmcp 3.x pinned exactly, wrapped in an `evo-mcp` crate | rust-mcp-sdk |
| PTY | portable-pty 0.9 behind a trait | alacritty_terminal (full emulator) |
| Process trees | tokio::process + process-wrap 9 (Job Objects / process groups) | raw windows-sys |
| Git | gix for local reads, `git` CLI for writes, network, credentials, worktrees | git2/libgit2 |
| File watching | notify 8 + notify-debouncer-full, with rescans | — |
| Search | `ignore` + `grep-searcher`/`grep-regex`; optionally keep bundled `rg` for the agent | — |
| LSP | `lsp-types` + small in-house tokio JSON-RPC client | tokio-lsp, lsp-client-rs (immature) |
| Keyring | keyring 3.6 with `new_with_target` for Python compatibility | — |
| PDF | pdfium-render + bundled Pdfium binaries | pdf-extract/lopdf (fidelity), mupdf (AGPL) |
| HTML → Markdown | htmd 0.5 + scraper pre-cleaning | html2md, fast_html2md |
| DuckDB | duckdb 1.4.x `bundled` (or prebuilt DLL) | — |
| Cron / time | croner 4 (jiff backend for scheduling), chrono elsewhere | jiff-cron |
| Web search | reqwest + scraper against DDG HTML, behind a pluggable provider | no maintained Rust ddgs |
| Sandbox | Port codex-rs's design (Seatbelt / Landlock+seccomp / restricted token + ACL) | birdcage, extrasafe (no Windows) |
| Logs / metrics | tracing + tracing-appender; `metrics` + Prometheus exporter; OTel opt-in | `prometheus` crate |
| Remaining Python | Subprocess workers on bundled python-build-standalone + uv, speaking MCP/JSON-RPC over stdio | PyO3 embedding, WASM |
| Test gates | wiremock, insta, proptest, nextest, llvm-cov, cargo-mutants, cargo-deny, clippy restriction lints, Schemathesis, oasdiff | Dredd (unmaintained) |

## axum wins on ecosystem fit, not on benchmarks

**axum 0.8.9 (April 2026) is the pick**, with no 0.9 announced ([axum releases](https://github.com/tokio-rs/axum/releases)). Benchmark comparisons are unreliable. Claims that actix-web is 10–15% faster conflict across articles, and TechEmpower was archived in March 2026 ([codercops](https://blog.codercops.com/blog/axum-actix-rocket-rust-web-frameworks-2026)). Either way, the gap does not matter for one local user. What does matter is that the reverse-proxy, OpenAPI and Tauri integration crates all build on the tower/hyper stack. axum also has roughly **462M lifetime downloads against about 80M for actix-web** ([depscope](https://depscope.dev/compare/cargo/actix-web-vs-axum-vs-rocket)).

**Streaming and cancellation.** These matter most for an agent workspace, and the production pattern is clear. NVIDIA Dynamo's axum-based LLM server wraps each SSE stream in a guard that is armed when streaming starts and disarmed on normal completion. If the client disconnects, the guard's `Drop` cancels the engine context ([dynamo-llm disconnect.rs](https://docs.rs/dynamo-llm/latest/src/dynamo_llm/http/service/disconnect.rs.html)). Drop detection works because axum drops the response stream when the client leaves even with no chunk in flight, so it is more reliable than waiting for a write error ([turbospark-server](https://docs.rs/crate/turbospark-server/0.3.0/source/src/cancel.rs)). EvoFlux's handlers should create a `CancellationToken`, spawn the agent turn on a bounded mpsc channel, and return `Sse::new(ReceiverStream).keep_alive(...)` inside such a guard. The team must also decide explicitly whether a turn survives a UI disconnect. If it should, decouple the turn from the HTTP stream with a replay buffer keyed by `Last-Event-ID`.

**Middleware.** tower-http 0.7.1 supplies every layer FastAPI currently provides implicitly: `CatchPanicLayer`, `TimeoutLayer`, body limits, CORS, tracing, request IDs, sensitive-header masking, bearer validation and compression ([tower-http docs](https://docs.rs/tower-http/latest/tower_http/)). Three operational rules follow:

- Apply timeouts per route group, never globally, so SSE, WebSocket and proxied routes are not killed.
- Exclude `text/event-stream` from compression, because the encoder buffers.
- Supervise spawned agent tasks separately, since `CatchPanicLayer` only covers the request future.

**Executor blocking.** This is the main tokio hazard. Ban `std::fs`, `std::thread::sleep` and `reqwest::blocking` in async crates via clippy `disallowed-methods`. Use tokio-console in development; it flags slow polls but cannot pinpoint the function ([tokio-rs/console #410](https://github.com/tokio-rs/console/discussions/410)). Ship a cross-platform lag watchdog (a 100 ms interval tick plus an OS-thread heartbeat check), because eBPF tools such as `hud` are Linux-only ([hud](https://awesome.ecosyste.ms/projects/github.com%2Fcong-or%2Fhud)).

**Contract fidelity with FastAPI.** This is the expensive part. **utoipa 5.5 supports OpenAPI 3.1**, and utoipa-axum's `OpenApiRouter` collects handlers into a spec ([utoipa](https://docs.rs/crate/utoipa/latest)). However, neither utoipa nor aide reproduces Pydantic-specific names, `operationId` formats or `anyOf [..., null]` Optionals on their own. So pin FastAPI's `/openapi.json` as the contract, set names and operation IDs explicitly, and gate CI with oasdiff, whose `breaking` action fails on warnings by default ([oasdiff-action](https://github.com/oasdiff/oasdiff-action)). Validation errors must be rebuilt by hand in FastAPI's `{"detail":[{type, loc, msg, input}]}` shape, using Pydantic v2 type codes such as `missing` and `int_parsing` ([FastAPI error-handling notes](https://huggingface.co/spaces/Nomearod/agentbench/blob/main/data/tech_docs/fastapi_error_handling.md)). That means overriding axum's default plain-text `JsonRejection`. Datetime suffixes (`Z` vs `+00:00`) and null-vs-omitted fields are unverified details: snapshot real FastAPI responses rather than trusting documentation.

**Strangler proxy.** `axum-reverse-proxy` 2.2.0 handles HTTP/1.1, HTTP/2, hop-by-hop stripping and WebSocket upgrades, but **its docs say nothing about SSE flush behaviour** ([docs.rs axum-reverse-proxy](https://docs.rs/axum-reverse-proxy)). Either test it directly, or write a small proxy on `hyper_util`. That proxy must:

- pass `Incoming` bodies through untouched, never buffered;
- splice upgraded WebSocket connections;
- propagate client disconnects so Starlette sees cancellation;
- inject a separate internal bearer token for the Python upstream.

**Hosting inside Tauri.** `tauri-plugin-axum` is ruled out because custom protocols do not support streaming ([tauri-plugin-axum](https://docs.rs/tauri-plugin-axum/latest/tauri_plugin_axum/)). The lowest-risk choice is to drop an `evoflux-server` binary into the existing sidecar slot, as Goose does. That binary spawns Python itself. Structure it as a library crate so it can later be linked in-process with no code changes. Keep the existing localhost hardening: bind to 127.0.0.1, use a per-launch token, a strict CORS allowlist, and Host-header checks.

## Keep the single writer; BEGIN CONCURRENT would not help uuid7 tables

**rusqlite is the right SQLite layer.** Every mainstream crate (rusqlite, sqlx-sqlite, Diesel, SeaORM via sqlx) ends at libsqlite3-sys, and Cargo allows only one crate in a binary to link `sqlite3`. Choosing a crate therefore does not change how a custom SQLite build gets linked; what differs is how much control each crate gives. rusqlite exposes raw handles and extended error codes such as `SQLITE_BUSY_SNAPSHOT`. libsqlite3-sys 0.39.1 bundles **SQLite 3.54.0** and accepts a custom library through `SQLITE3_LIB_DIR`/`SQLITE3_STATIC` ([libsqlite3-sys](https://docs.rs/crate/libsqlite3-sys/latest)). Production desktop apps confirm the pattern of going below sqlx. Zed wrote its own thin wrapper over libsqlite3-sys ([Zed sqlez](https://raw.githubusercontent.com/zed-industries/zed/main/crates/sqlez/Cargo.toml)). Atuin mixes sqlx 0.9 with rusqlite and pins a libsqlite3-sys version range to keep the single link consistent ([Atuin Cargo.toml](https://raw.githubusercontent.com/atuinsh/atuin/main/Cargo.toml)). sqlx's compile-time checking would require a schema snapshot database in CI for 53+ Alembic revisions. Its pooling also adds nothing to a strict FIFO writer.

**The writer design.** Port the current design directly:

- One `std::thread` owns the writer `Connection` and receives `FnOnce(&mut Connection)` closures over a bounded channel. Each closure replies through a oneshot, and the 5-second admission timeout becomes a send deadline.
- A small reader pool runs with `PRAGMA query_only=ON`. Existing crates such as deadpool-sqlite (per-connection threads, panic recovery tested) supply the plumbing ([deadpool-sqlite](https://docs.rs/deadpool-sqlite)).

A useful side effect is that a synchronous closure cannot await network I/O. The repository rule "no Git, network or process work inside a transaction" becomes a compile-time property.

**BEGIN CONCURRENT is not worth adopting in 2026.** It remains an **unmerged branch that SQLite's developers keep current with trunk**. The newest tag seen is `begin-concurrent-3.51` from March 2026 ([SQLite timeline](https://www.sqlite.org/src/timeline?r=begin-concurrent)). Maintainers have said there are "no concrete plans" to merge it, and SQLite's testing guarantees do not cover branches ([SQLite forum](https://sqlite.org/forum/info/84fe63b7b3)). The deeper problem is the conflict model. BEGIN CONCURRENT uses **optimistic page-level locking**: a COMMIT fails with `SQLITE_BUSY_SNAPSHOT` if any page the transaction read changed after it began. The design document itself calls monotonic rowids "terrible for concurrency" because new rows all land on the same page ([begin_concurrent.md](https://www.sqlite.org/src/doc/begin-concurrent/doc/begin_concurrent.md)). EvoFlux's uuid7 keys on rowid tables are time-ordered twice over, in the implicit rowid and in the PK index. So concurrent inserts into one table would conflict almost every time. Only writes to different tables, or updates scattered across the keyspace, would actually run in parallel. Adopting the branch would also make the team responsible for building and testing a custom amalgamation on MSVC, macOS and Linux.

If writer-queue waits (today's 503 rate) ever justify it, the upgrade path is narrow. Grow the writer to K connections running `BEGIN CONCURRENT` inside a retry loop. This is safe only because closures are side-effect-free. Stay in `wal` mode, never `wal2`, so files remain readable by stock SQLite. **Turso is not an alternative yet.** Its own manual calls MVCC "not production ready" and lists no triggers, savepoints or multi-process access. It also says MVCC writes stay invisible to non-MVCC opens until checkpointed ([Turso manual](https://github.com/tursodatabase/turso/blob/main/docs/manual.md)). Turso's row-level conflict detection would remove the uuid7 hotspot ([Turso blog](https://turso.tech/blog/concurrent-writes-on-turso-cloud)), so re-evaluate it in 2027.

**Taking over from Alembic.** Read `alembic_version`, refuse unknown revisions, stamp a Rust baseline, and apply only Rust migrations from then on. Avoid rusqlite_migration, which stores state in `user_version` and has unspecified behaviour if anything else writes that field ([rusqlite_migration](https://docs.rs/rusqlite_migration/latest/rusqlite_migration/)). refinery works with a baseline but locks in checksums ([refinery](https://docs.rs/crate/refinery/0.9.1/source/README.md)). A roughly 150-line custom migrator is the more controllable bridge.

**Tuning.** Use WAL, `synchronous=NORMAL`, `busy_timeout`, and `foreign_keys` set on every connection. Add explicit passive checkpoints, because the WAL "will grow without bound" if readers always overlap ([SQLite WAL](https://www.sqlite.org/wal.html)). On Windows, treat `SQLITE_IOERR_LOCK` as retryable: antivirus software takes transient mandatory locks that surface as I/O errors rather than `SQLITE_BUSY` ([win32lock.test](https://www.sqlite.org/src/artifact/71642fa56e9b06e5)).

## Own the provider layer, borrow rmcp, copy Codex's event-queue core

**No official Anthropic or OpenAI Rust SDK exists.** Every Rust client is community-built ([lib.rs anthropic](https://lib.rs/crates/anthropic)).

The best multi-provider crate is **genai 0.7.2**. It offers 30+ adapters, replay of reasoning signatures across tool turns, and Anthropic tool caching. Its gaps hit EvoFlux directly, though: it reports cache usage as "N/A" for Gemini and Cohere, computes some totals instead of reading them, and states that ergonomics take priority over depth ([rust-genai](https://github.com/jeremychone/rust-genai)). **rig-core** ships a pre-1.0 minor release every one to two weeks; 0.45.0 came out on 2026-10-19 ([crates.io rig-core](https://crates.io/api/v1/crates/rig-core)). Adopting it would also mean adopting its agent abstractions, which conflicts with porting a 77k-line runtime's existing semantics.

The decisive evidence is that **neither Codex nor Goose uses any of these crates**. Codex has its own `model-provider`, `model-provider-info` and `stream-parser` crates on top of `reqwest` and `eventsource-stream` ([codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)). Goose went further and published its providers crate as a reusable component in July 2026 ([Goose roadmap #10579](https://github.com/aaif-goose/goose/discussions/10579)). EvoFlux should do the same. Write four or five wire protocols:

- OpenAI Chat-compatible, which covers the long tail of providers;
- OpenAI Responses;
- Anthropic Messages;
- Gemini;
- Bedrock, via `aws-sdk-bedrockruntime` (1.152, actively released ([crates.io](https://crates.io/api/v1/crates/aws-sdk-bedrockruntime))) for free credential-chain support.

Express the ~200 providers' quirks as data, not code. Use genai as reference code for usage normalization. Bedrock's binary event-stream framing and Gemini's chunked JSON mean the layer needs a frame-decoder abstraction, not just an SSE parser.

**SSE parsing.** Use `eventsource-stream` 0.2.3. It has been frozen since 2022 but has 31.6M downloads, and Codex depends on it ([crates.io](https://crates.io/api/v1/crates/eventsource-stream)). Alternatively, vendor a roughly 200-line parser. Avoid `reqwest-eventsource`: its auto-reconnect would re-POST a model call mid-stream and risk double billing ([crates.io](https://crates.io/api/v1/crates/reqwest-eventsource)). Retry only before the first token, and add your own idle timeout.

**MCP.** rmcp is the settled choice:

- Version 3.8.0 shipped on 2026-10-26, it has 42M downloads, and Codex pins `=3.5.1` while Goose uses 3.4.1 ([crates.io rmcp](https://crates.io/api/v1/crates/rmcp)).
- **rmcp 3.0 implemented spec 2026-07-28**, which removed `Mcp-Session-Id`, the GET stream and `initialize` (replaced by `server/discover`). It keeps a `legacy_session_mode` and the legacy `serve()` path for older servers. `ClientLifecycleMode::Auto` appears designed to negotiate between old and new servers ([rmcp v3.0.0 release](https://github.com/modelcontextprotocol/rust-sdk/releases/tag/rmcp-v3.0.0)).
- EvoFlux's "MCP 2.x" requirement is therefore covered, but the client must support both lifecycles.
- OAuth ships behind the `auth` feature.
- New `InputRequiredResult` returns mean a tool call can pause for elicitation. The tool-wave scheduler therefore needs a "suspended, awaiting user" state.

Wrap rmcp in an internal `evo-mcp` crate and pin its version exactly, because a major bump and a minor every week or two would otherwise ripple through the codebase.

**Runtime architecture.** Mirror Codex:

- Clients submit `Op` values (`UserTurn`, `Interrupt`, `Shutdown`) and consume `EventMsg` streams.
- Every tool call passes through a `ToolRouter` that enforces approvals and picks a sandbox ([codex-rs architecture](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/)).
- Following Goose's Q3 2026 direction, write the loop as a **re-entrant per-turn state machine** from day one rather than one long async function. This makes testing, resume and sub-agents tractable ([Goose roadmap](https://github.com/aaif-goose/goose/discussions/10579)).
- Goose's trick of running built-in tools as in-process MCP servers over a duplex stream unifies built-in and external tools under one dispatcher ([Goose MCP architecture](https://codex.danielvaughan.com/2026/04/07/goose-mcp-native-architecture/)).

**Testing.** Copy Codex's harness, which uses `wiremock` with typed SSE builders: `ev_function_call`, `ev_reasoning_text_delta`, `ev_completed_with_tokens`, and `mount_sse_sequence` for scripted multi-turn loops. A request matcher panics on orphaned tool calls ([codex responses.rs](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/tests/common/responses.rs)). Cancelled tool calls must still produce synthesized results so transcripts stay valid.

**Tokenizers.** Neither Codex nor Goose declares a tokenizer at workspace level. Provider-reported usage plus a byte-based estimate is the production norm.

## Most integrations have a proven crate; Windows sandboxing does not

EvoFlux's integration surface is mostly solved, but Windows needs special care for nearly every item.

**PTY.** Use **portable-pty 0.9**, which is codex-rs's choice for an agent that runs shells. Zed instead forks `alacritty_terminal` because it needs a full emulator, and its history shows repeated Windows PTY fixes ([Zed #8999](https://git.secluded.site/zed/commit/e85d48495283933610011855af8940434867b1a4)).

**Process trees.** Use **process-wrap 9**, the successor to command-group from the watchexec org. It provides Job Objects on Windows, process groups on POSIX and kill-on-drop ([process-wrap](https://docs.rs/crate/process-wrap/9.0.1/source/README.md)). Set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so the whole tree dies with the backend ([windows_job.rs example](https://preview.hex.pm/preview/aube/show/crates/aube-scripts/src/windows_job.rs)). PTY children have to be assigned to the job manually, because portable-pty spawns them itself.

**Git.** Split the work: **gix** for fast local reads and the **git CLI** for writes, network operations and worktrees. Codex uses gix 0.89 with minimal features. Zed's git crate carries no libgit2 and depends on an `askpass` crate, which points to CLI calls with credential prompts routed to the UI ([Zed crates/git](https://raw.githubusercontent.com/zed-industries/zed/main/crates/git/Cargo.toml)). gix releases roughly every two weeks ([gix-worktree](https://docs.rs/crate/gix-worktree/0.58.0)), so pin it exactly.

**File watching.** Use **notify 8 plus notify-debouncer-full**. Its docs warn that events can be missed on very large trees ([notify docs](https://docs.rs/notify/latest/i686-pc-windows-msvc/notify)), and Zed carries a patched fork, so design for periodic rescans.

**Search.** Both Zed and Codex use the **`ignore`** walker. Embed `grep-searcher` and `grep-regex` for the in-app search UI. Optionally keep a bundled `rg` for the agent's shell tool, since models already know its flags.

**LSP.** No Rust LSP client crate is mature. Both editors fork `lsp-types` ([Zed Cargo.toml](https://raw.githubusercontent.com/zed-industries/zed/main/Cargo.toml)). Write a small tokio JSON-RPC client on top of it.

**Keyring.** This is a concrete migration trap. keyring-rs 3.6 writes Windows credentials under the target name `username.service` ([keyring windows.rs](https://docs.rs/crate/keyring/latest/source/src/windows.rs)). Python keyring writes `service`, or `username@service` on collision ([jaraco/keyring Windows.py](https://raw.githubusercontent.com/jaraco/keyring/main/keyring/backends/Windows.py)). Use `Entry::new_with_target` with a fallback chain, or users lose stored API keys on upgrade.

**Documents.** **pdfium-render** gives parity with pypdfium2 because it uses the same engine, at the cost of shipping a Pdfium binary per platform ([pdfium-render](https://www.lib.rs/crates/pdfium-render)). **htmd 0.5** is a turndown port that passes turndown's tests and converts a 1.37 MB page in about 16 ms ([htmd](https://docs.rs/crate/htmd/latest)). Check its output against markdownify with golden tests.

**DuckDB.** The `bundled` feature compiles C++ for minutes and **omits ICU** ([duckdb README](https://docs.rs/crate/duckdb/1.4.4/source/README.md)). Cache builds with sccache or link a prebuilt DLL.

**Cron.** **croner 4** now supports a jiff backend for DST-correct scheduling. It no longer bundles chrono-tz, so add that crate for named time zones ([croner MIGRATION](https://docs.rs/crate/croner/4.0.0/source/MIGRATION.md)).

**Web search.** No maintained Rust ddgs exists. DuckDuckGo's HTML endpoint returns **HTTP 202 as a soft block** that generic success checks miss ([rust_scrapling](https://docs.rs/crate/rust_scrapling/latest/source/src/fetchers/search.rs)). Make search a pluggable provider with fallbacks.

**Observability.** Use tracing, tracing-subscriber and tracing-appender, matching Codex's exact stack. Pin opentelemetry crates as one matched set, since the project is still pre-1.0 and traces are beta ([opentelemetry-rust #1678](https://github.com/open-telemetry/opentelemetry-rust/issues/1678)).

**Sandboxing.** This is the one area without an off-the-shelf answer. The only complete open-source reference is codex-rs (Apache-2.0):

- macOS: Seatbelt.
- Linux: Landlock and seccomp, plus bubblewrap.
- Windows: a restricted token whose restricting SIDs include a synthetic `sandbox-write` SID. Write ACLs apply only on workspace roots, and network is blocked by firewall rules. It can still fail on locked-down corporate machines with `CreateRestrictedToken failed: 87` ([Codex Windows sandbox](https://codex.danielvaughan.com/2026/05/14/codex-cli-windows-sandbox-engineering-restricted-tokens-acls-elevated-architecture/)).

These details come from a third-party write-up. Verify them against `windows-sandbox-rs` before adapting the code. Plan tiered fallbacks on Windows: approval policy only, then Job Object limits, then ACLs.

## Host leftover Python as killable stdio workers, not embedded interpreters

**Plugins, the `python` tool and skill scripts belong in subprocess workers.** Run them on a bundled **python-build-standalone** interpreter and speak JSON-RPC (ideally MCP) over stdio. python-build-standalone moved to Astral's stewardship in December 2024. It underpins uv, Rye and rules_python and has passed 70M release downloads ([Astral](https://astral.sh/blog/python-build-standalone)). Bundling it with a uv binary lets EvoFlux create a venv per plugin on demand. This design gives crash isolation, killability through the same Job Object and process-group machinery, no GIL inside the gateway, and support for any wheel. Figma's long-running Node host with Rust children over stdio shows the process-per-worker boundary holds up in production ([Figma](https://www.figma.com/blog/rust-in-production-at-figma/)).

**PyO3 embedding** is the alternative. Bakken & Baeck's Parviocula uses it to host an ASGI app inside axum ([Bakken & Baeck](https://bakkenbaeck.com/tech/converting-a-project-from-python-to-rust-piece-by-piece)). For EvoFlux it would bring back GIL contention and let a segfault take down the gateway. Reserve it, if used at all, for small trusted hot-path helpers.

**WASM** (componentize-py) gives the strongest sandbox but historically cannot load native extensions such as NumPy or pandas ([Fermyon](https://www.fermyon.com/blog/introducing-componentize-py)). Its 2026 status is unconfirmed, so it is not viable for general plugins.

**Packaging.** On macOS, every nested executable and `.dylib` in the bundled Python must be signed with hardened runtime. A missing entitlement on a nested helper is a common notarization failure ([Tauri macOS signing notes](https://stuffbucket.github.io/skills/catalog/tauri-bundling-macos-signing/)).

## A validated judge suite must exist before the first route moves

**Migrate incrementally with both systems running.** That is how successful rewrites have gone. OpenAI kept merging fixes into the TypeScript Codex "until the Rust version is at experience and feature parity" ([Devclass](https://devclass.com/2025/06/02/node-js-frustrating-and-inefficient-openai-rewrites-ai-coding-tool-in-rust/)). Dropbox treated randomized and deterministic-simulation testing as a core feature of its Nucleus rewrite, mocking time, filesystem and network under a custom executor ([Dropbox Tech](https://dropbox.tech/infrastructure/-testing-our-new-sync-engine)). Bakken & Baeck ran their integration suite with axum replacing uvicorn before porting a single route ([Bakken & Baeck](https://bakkenbaeck.com/tech/converting-a-project-from-python-to-rust-piece-by-piece)).

**Set success criteria honestly.** The famous Rust wins were narrow hot paths. Discord's Read States removed GC latency spikes ([Discord](https://discord.com/blog/why-discord-is-switching-from-go-to-rust)), and Pingora reported about 70% less CPU ([Cloudflare](https://blog.cloudflare.com/how-we-built-pingora-the-proxy-that-connects-cloudflare-to-the-internet/)). A 167k-line orchestration backend will gain mainly in packaging, startup and memory. EvoFlux should define success in those terms. No published post-mortem of a 100k+ line FastAPI backend fully migrated to Rust was found, so EvoFlux is on less-charted ground than the case studies suggest.

**Run the migration the way Anthropic's July 2026 guide describes:**

- **Judge first.** Build a harness that passes on the original and fails on deliberately broken code.
- **Compiler and test errors as the work queue.** Parallel fixer agents pull from it.
- **One build daemon.** It batches patches so cargo stays out of each agent's loop.
- **A rulebook.** Recurring review findings become rules, and affected batches are regenerated rather than hand-patched.
- **Stress test before the full run.** A 3-file trial found two critical issues before the full run.
- **Budget for reruns.** Their large ports were run end to end three times.

In the Bun port, about **1M lines passed all existing tests before merge, and 19 regressions surfaced afterwards** ([Anthropic](https://claude.com/blog/ai-code-migration)). That is a sober reminder that green CI is not parity. Airbnb's 3.5k-file test migration found that **retrying with error feedback beat prompt engineering** ([InfoQ](https://www.infoq.com/news/2025/03/airbnb-llm-test-migration/)).

**EvoFlux's specific weak point.** Only about 17% of its Python tests exercise HTTP. So the "gap inventory" step is critical: mine the in-process tests for error codes, edge cases and side effects, and convert them into HTTP contract cases before each unit is ported.

**Verification stack, per ported unit:**

1. **Spec gate.** oasdiff must report no breaking change between FastAPI's pinned spec and the Rust spec.
2. **Dual-target contract suite.** The same suite runs against `PY_BASE_URL` and `RS_BASE_URL`, using normalized JSON diffing and **insta** snapshots with redactions.
3. **Differential fuzzing.** Run **Schemathesis** against both backends with the same seed ([schemathesis](https://schemathesis.readthedocs.io/)).
4. **Agent streams.** Diff event sequences after normalizing token-chunk boundaries.
5. **Shadow traffic.** For dogfood GET traffic, use Diffy's primary/secondary/candidate split so that only differences beyond the measured noise count ([opendiffy/diffy](https://github.com/opendiffy/diffy)).
6. **Rust-side gates.** cargo-nextest, cargo-llvm-cov, `cargo mutants --in-diff` (which also proves the judge catches mutations), cargo-deny, and clippy restriction lints (`unwrap_used`, `disallowed-methods`, `await_holding_lock`) denied in handler crates ([Clippy lints](https://rust-lang.github.io/rust-clippy/master/index.html)).

**Release.** Keep tauri-plugin-updater's keypair and `latest.json` endpoint stable. That signature is separate from OS code signing ([DEV: Tauri release automation](https://dev.to/tomtomdu73/ship-your-tauri-v2-app-like-a-pro-github-actions-and-release-automation-part-22-2ef7)). Watch for the NSIS bug where a same-version reinstall does not replace the sidecar ([tauri #15134](https://github.com/tauri-apps/tauri/issues/15134)). Add an upgrade test: install N−1, create data, auto-update, then run the contract suite against the Python-era database. The new version must also kill any lingering old Python sidecar.

## Conclusion

Most of the hard technical decisions in this migration have already been tested by others. The integration crates are ones codex-rs and Zed already depend on, so choosing them carries little risk. EvoFlux's real risks are elsewhere. One is **contract equivalence**: Pydantic serialization quirks, 422 shapes, SSE ordering, and the 83% of behaviour that current tests cover only in-process. The other is **Windows**: ConPTY, Job Objects, keyring target names, antivirus I/O locks, and the immature restricted-token sandbox. So effort should go into the judge suite and Windows CI before porting volume, not into weighing frameworks.

BEGIN CONCURRENT turns out to be a non-goal rather than a deferred optimization. EvoFlux's uuid7-on-rowid schema would create page-level conflicts on every hot table. The single-writer closure design, by contrast, enforces "DB work only" in the type system. If write concurrency ever becomes a measured bottleneck, the better next steps are schema changes (random keys on hot tables) or Turso's row-level MVCC once it matures, not a custom SQLite branch.

Finally, the end state should make MCP over stdio the single protocol for everything outside the Rust core: Python plugins, skill scripts, and built-in tools via in-process duplex servers. That gives EvoFlux one dispatcher, one sandbox and permission path, and one cancellation model for every tool.
