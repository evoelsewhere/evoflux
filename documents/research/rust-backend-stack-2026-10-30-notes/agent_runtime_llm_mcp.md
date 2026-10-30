# Rust Agent Runtime: LLM Providers, Streaming, Tool Calling, MCP (as of 2026-10-30)

Research scope: the Rust crates and reference implementations for rewriting EvoFlux's Python agent runtime (about 200 providers, streaming text, reasoning and tool calls, normalized usage including cache read/write, concurrent tool waves, MCP 2.x client over Streamable HTTP and stdio).
Method: about 19 tool calls. Primary sources were crates.io API JSON, GitHub repos and raw Cargo.toml files, and release notes. Secondary blogs are labelled as such.

## Q1. Rust LLM client crates: coverage of streaming, tools, reasoning, caching, multi-provider; official SDKs; build vs buy

### Takeaway
Neither Anthropic nor OpenAI has an official Rust SDK; every Rust client is community-built. The two most mature multi-provider crates are `genai` 0.7.2 (native protocols, 30+ adapters, reasoning-signature replay, partial cache-usage normalization) and `rig-core` 0.45 (a framework with a fast release cadence). The two largest Rust agent apps, Codex and Goose, both use neither. Each wrote its own thin provider layer over `reqwest` plus SSE parsing. For EvoFlux, with about 200 providers and strict usage and cache-accounting needs, the evidence favours an in-house provider layer. `genai` is useful as a reference, or as a fallback adapter for long-tail providers.

### Cited Findings
- **No official SDK found.** A search for official Anthropic or OpenAI Rust SDKs returned only crates that describe themselves as unofficial: `openai_rust_sdk`, `anthropic-api`, `anthropic-rs` (no releases), and `anthropic` (last release 0.0.8 in Sept 2024, so stale). — [docs.rs openai_rust_sdk](https://docs.rs/openai_rust_sdk/latest/openai_rust_sdk/); [docs.rs anthropic-api](https://docs.rs/anthropic-api); [lib.rs anthropic](https://lib.rs/crates/anthropic); [GitHub anthropic-rs](https://github.com/abdelhamidbakhta/anthropic-rs)
- **OpenAI Assistants API sunset.** The `openai_rust_sdk` docs say OpenAI deprecated the Assistants API, with shutdown on 2026-08-26, and that Responses and Conversations are the recommended path. — [docs.rs openai_rust_sdk](https://docs.rs/openai_rust_sdk/latest/openai_rust_sdk/)
- **`genai` crate stats.** Version 0.7.2, updated 2026-10-28, 544k total downloads (255k recent). Repo is jeremychone/rust-genai, which has about 923 stars, 196 forks and 35 open issues. — [crates.io API genai](https://crates.io/api/v1/crates/genai); [GitHub rust-genai](https://github.com/jeremychone/rust-genai)
- **`genai` providers.** Over 30 adapters, including OpenAI (Chat and Responses), Anthropic, Gemini (including the Interactions API), Ollama local and cloud, Groq, xAI, DeepSeek, Mistral, Cohere, Together, Fireworks, Vertex, Bedrock, OpenRouter and Zai. Generic OpenAI-compatible endpoints use `genai_{n}` adapters configured through `GENAI_{n}_ENDPOINT` and `GENAI_{n}_API_KEY`. — [GitHub rust-genai](https://github.com/jeremychone/rust-genai)
- **`genai` features:**
  - streaming, including a `ChatStreamEvent::Heartbeat` event, a raw `ChatFrameSink`, and stream header and read timeouts
  - function calling
  - reasoning-effort suffixes on model names
  - preservation of thought signatures and signed thinking blocks across tool turns for Anthropic, Gemini and OpenRouter
  - Anthropic tool caching via `Tool::with_cache_control`
  - customization hooks: `ServiceTargetResolver` (endpoint, auth, model), `AuthResolver`, `ModelMapper`, and injection of your own `reqwest` client
  — [GitHub rust-genai](https://github.com/jeremychone/rust-genai)
- **`genai` Bedrock.** Two adapters, `bedrock_api` and `bedrock_sigv4`. The 0.7.0 notes add streaming usage from metadata and replay of signed and redacted reasoning across tool turns. — [GitHub rust-genai](https://github.com/jeremychone/rust-genai)
- **`genai` limitations:**
  - Cache usage shows as "N/A for now" for Gemini and Cohere.
  - Some totals are computed rather than reported.
  - Gemini streaming usage is assumed to be cumulative.
  - The project says ergonomics take priority over depth, and points to async-openai or ollama-rs for broader API coverage.
  - The `rustls-tls` and `native-tls` features are mutually exclusive.
  — [GitHub rust-genai](https://github.com/jeremychone/rust-genai)
- **`async-openai` crate stats.** Version 0.42.2, updated 2026-10-10, about 10.0M total downloads (3.17M recent). Repo is 64bit/async-openai. It is the most-downloaded OpenAI-specific crate. — [crates.io API async-openai](https://crates.io/api/v1/crates/async-openai)
- **`rig-core` crate stats.** Latest stable is 0.45.0 (2026-10-19), with 0.46.0-rc.1 on 2026-10-23. Earlier releases: 0.44.0 (Oct 7), 0.43.0 (Sep 30), 0.42.0 (Aug 17). About 3.9M total downloads (1.98M recent). Repo is 0xPlaygrounds/rig. It is still pre-1.0 with a minor release every 1–2 weeks. — [crates.io API rig-core](https://crates.io/api/v1/crates/rig-core)
- **`aws-sdk-bedrockruntime` crate stats.** Version 1.152.0, updated 2026-10-28, 6.3M total downloads (2.2M recent). It is the official AWS SDK crate, actively released. — [crates.io API aws-sdk-bedrockruntime](https://crates.io/api/v1/crates/aws-sdk-bedrockruntime)
- **Codex does not use a third-party LLM client.** The codex-rs workspace has no `async-openai`, `genai` or `rig` dependency. It has its own crates: `codex-api`, `codex-client`, `http-client`, `model-provider`, `model-provider-info`, `models-manager`, `ollama`, `lmstudio`, `responses-api-proxy`, `aws-auth`, `websocket-client` and `utils/stream-parser`. It depends directly on `reqwest = "0.12"` and `eventsource-stream = "0.2.3"`. — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- **Goose does not use a third-party LLM client either.** Its workspace (`crates/*`, version 1.57.0) does not list `async-openai`, `genai`, `rig`, `eventsource-stream` or `reqwest-eventsource` at workspace level. It uses `reqwest = 0.13.2` and `tokio = 1.48`. — [goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml)
- **Goose providers crate.** Goose has its own `Provider` trait (third-party docs mirror, path `crates/goose/src/providers/base.rs`). In July 2026 the Goose team published its providers crate as a reusable component with UniFFI bindings for Python and Kotlin. — [Goose Roadmap 2026 Q3, discussion #10579](https://github.com/aaif-goose/goose/discussions/10579); [mintlify goose architecture (secondary)](https://www.mintlify.com/block/goose/development/architecture)

### Inferences
- The two production Rust agents studied both build their own provider layer. This is strong evidence for writing a thin in-house layer for EvoFlux. Reasons:
  1. exact control over cache_control placement and cache-read/write usage fields
  2. reasoning-block replay rules that differ per provider
  3. provider quirks, which the Python runtime already encodes for about 200 providers
- A practical shape is three or four wire protocols covering about 200 providers:
  - OpenAI Chat Completions-compatible, which covers most hosted, routed and local providers (OpenRouter, Groq, Together, Ollama's OpenAI endpoint, LM Studio)
  - OpenAI Responses
  - Anthropic Messages
  - Gemini
  - Bedrock Converse/ConverseStream via `aws-sdk-bedrockruntime`, or SigV4 over reqwest
  Per-provider quirks would live in data and config (the Codex `model-provider-info` pattern), not in code.
- `genai` is worth reading as a reference for its usage-normalization table and reasoning-signature replay. It could also serve as a stop-gap adapter. Its admitted gaps in cache-usage normalization (Gemini, Cohere) matter for EvoFlux's cache accounting.
- `rig` is a full framework (agents, RAG, vector stores) with frequent pre-1.0 breaking releases. Adopting it would mean adopting its agent abstractions, which conflicts with porting an existing 77k-line runtime's semantics. Its provider modules are better treated as reference code.
- For Bedrock, using the official `aws-sdk-bedrockruntime` crate gets credential-chain support (SSO, profiles, IMDS) for free. The trade-off is a heavy dependency tree. Codex instead has a dedicated `aws-auth` crate.

### Gaps
- I did not verify rig's specific feature coverage (reasoning tokens, prompt-cache usage fields, tool-streaming deltas) from its source or docs.
- Not researched: the `llm` crate (graniet/llm), `langchain-rust`, `tiktoken-rs` and `tokenizers` stats.
- I could not confirm whether `async-openai` 0.42 fully supports Responses API streaming events. It covers OpenAI only, so it would not solve the multi-provider need anyway.
- No primary-source evidence that Anthropic or OpenAI plan a Rust SDK. The finding is absence of evidence, from search only.

## Q2. SSE client parsing in Rust: eventsource-stream vs reqwest-eventsource, robustness

### Takeaway
`eventsource-stream` 0.2.3 is a tiny, frozen (2022) but heavily used SSE line parser over any byte stream, and Codex depends on it directly. `reqwest-eventsource` 0.6.0 (Mar 2024) adds reconnect and retry semantics that are wrong for LLM POST streams. The recommended pattern is `reqwest` `bytes_stream()` → `eventsource-stream` (or a ~200-line in-house parser), plus your own idle-timeout, error-mapping and no-retry-after-first-token policy.

### Cited Findings
- **`eventsource-stream`:** version 0.2.3, published 2022-02-17 with no release since. 31.6M total downloads, 14.7M recent. — [crates.io API eventsource-stream](https://crates.io/api/v1/crates/eventsource-stream)
- **`reqwest-eventsource`:** version 0.6.0 (2024-03-29); previous releases 0.5.0 (2023-10) and 0.4.0 (2022-02). 12.4M total downloads, 2.5M recent. — [crates.io API reqwest-eventsource](https://crates.io/api/v1/crates/reqwest-eventsource)
- **Codex** uses `eventsource-stream = "0.2.3"`, not `reqwest-eventsource`, and has its own `utils/stream-parser` crate. — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- **`genai`** exposes stream header and read timeouts, plus a heartbeat event. This suggests idle-timeout handling is needed in practice. — [GitHub rust-genai](https://github.com/jeremychone/rust-genai)

### Inferences
- Both SSE crates are effectively in maintenance freeze. Since an SSE parser is small (spec-defined line framing), vendoring or writing one is low-risk and removes a stale dependency. Codex's separate `stream-parser` crate hints they did some of this.
- Avoid `reqwest-eventsource` auto-reconnect for model calls. Retrying a POST mid-stream could double-bill or duplicate output. Retry should happen at the request level, only before the first event.
- Some providers do not use SSE: Bedrock uses AWS event-stream binary framing, and Gemini can return chunked JSON arrays without `alt=sse`. A provider layer needs a "frame decoder" abstraction, not only SSE.

### Gaps
- No public robustness benchmarks or bug reports were reviewed for either crate (for example, CRLF handling, multi-line `data:` fields, or a BOM at stream start).

## Q3. MCP in Rust: official rmcp SDK status, spec support, transports, OAuth; alternatives

### Takeaway
`rmcp` (modelcontextprotocol/rust-sdk) is the de facto standard. It is at 3.8.0 (2026-10-26), has about 42M downloads, ships a release every 1–2 weeks, and is used by both Codex (rmcp 3.5.1 pinned) and Goose (rmcp 3.4.1). rmcp 3.0 (2026-07-28) implements MCP spec 2026-07-28, which made Streamable HTTP sessionless and removed `initialize`. It keeps legacy-session APIs for older servers, which matters for an "MCP 2.x" client that talks to many existing servers. OAuth is built in behind the `auth` feature.

### Cited Findings
- **rmcp release cadence.** 3.8.0 on 2026-10-26, 3.7.0 on 10-22, 3.6.0 on 10-20, 3.5.1 on 10-05, 3.5.0 on 09-28, 3.4.x in Sept, 3.2.0 on 08-31. 42.2M total downloads, 23.9M recent. — [crates.io API rmcp](https://crates.io/api/v1/crates/rmcp)
- **rmcp 3.0.0 (28 July 2026)** adds support for MCP 2026-07-28. It is preceded by 3.0.0-beta.1 through beta.5 and follows rmcp 2.2.0. The migration guide is GitHub discussion #969. — [rmcp v3.0.0 release](https://github.com/modelcontextprotocol/rust-sdk/releases/tag/rmcp-v3.0.0)
- **Streamable HTTP changes in 3.0:**
  - Removed: `Mcp-Session-Id`, the standalone GET stream, DELETE termination, and `Last-Event-ID` resumption.
  - `stateful_mode` is renamed `legacy_session_mode`.
  - `subscriptions/listen` replaces the GET stream and resources subscribe.
  - `initialize` is replaced by `server/discover`. Clients opt in via `serve_with_lifecycle` with `ClientLifecycleMode::Discover` or `Auto`, while `serve()` keeps legacy initialization.
  - `ping`, `logging/setLevel` and `notifications/roots/list_changed` are removed under 2026-07-28, but remain for legacy sessions.
  - `call_tool`, `get_prompt` and `read_resource` now return MRTR-aware enums (`InputRequiredResult`).
  - The experimental tasks API moved to the `io.modelcontextprotocol/tasks` extension.
  - MSRV is 1.88.
  — [rmcp v3.0.0 release](https://github.com/modelcontextprotocol/rust-sdk/releases/tag/rmcp-v3.0.0)
- **OAuth in 3.0:**
  - authorization startup consolidated around `AuthorizationRequest`
  - `resolve_metadata`, which returns provenance
  - support for pre-registered clients
  - DCR credentials bound to the issuing AS (SEP-2352)
  - scope accumulation on step-up (SEP-2350)
  - a missing `issuer` rejected by default
  - rejected refresh tokens distinguished from transient failures
  — [rmcp v3.0.0 release](https://github.com/modelcontextprotocol/rust-sdk/releases/tag/rmcp-v3.0.0)
- **Feature flags.** The README lists an `auth` (OAuth 2.0) feature and `transport-streamable-http-server`, among others. — [docs.rs rmcp 3.0.1 README](https://docs.rs/crate/rmcp/3.0.1/source/README.md)
- **Codex:** pins `rmcp = "=3.5.1"` to a git revision and wraps it in its own `rmcp-client` crate, plus `codex-mcp` and `ext/mcp`. — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- **Goose:** `rmcp = { version = "3.4.1", default-features = false, features = ["schemars"] }`. Its July 2026 roadmap commits to helping rmcp support the new stateless spec and aligning Goose's MCP client, built-in servers and extensions to it. — [goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml); [Goose Roadmap 2026 Q3](https://github.com/aaif-goose/goose/discussions/10579)
- **Goose built-in extensions** are themselves MCP servers, reportedly run in-process over `tokio::io::DuplexStream`. Transports are STDIO and SSE/Streamable HTTP, with one client per server. — [danielvaughan blog, secondary](https://codex.danielvaughan.com/2026/04/07/goose-mcp-native-architecture/); [mintlify goose architecture, secondary](https://mintlify.com/block/goose/concepts/architecture)
- **Alternatives:**
  - `rust-mcp-sdk` 2.0.0 exists on docs.rs. — [docs.rs rust-mcp-sdk](https://docs.rs/crate/rust-mcp-sdk/2.0.0)
  - `rmcp-server-kit` 1.3.2 is a third-party server-side helper on top of rmcp. — [docs.rs rmcp-server-kit](https://docs.rs/crate/rmcp-server-kit/1.3.2/source/CHANGELOG.md)

### Inferences
- Use `rmcp` and wrap it behind an in-house `mcp-client` crate, as Codex does with `rmcp-client`. The wrapper isolates EvoFlux from breaking changes; rmcp had a major bump in July and minors every 1–2 weeks.
- Pinning an exact version, as Codex does with `=3.5.1`, is prudent.
- EvoFlux's "MCP 2.x" requirement (interpreted as the 2025-era specs: 2025-03-26 and 2025-06-18 Streamable HTTP with sessions) is still covered through rmcp's legacy `serve()` path and `legacy_session_mode`. `ClientLifecycleMode::Auto` appears designed to negotiate between old and new servers.
- Goose's pattern of running built-in tools as in-process MCP servers over a duplex stream is a clean way to unify built-in and external tools under one dispatcher.
- With MRTR (`InputRequiredResult`), tool calls can pause for elicitation. The agent loop's tool-wave scheduler must support a "suspended, awaiting user input" state.

### Gaps
- The 3.0 release notes did not mention stdio or child-process transport changes. I did not verify that the client-side `TokioChildProcess` transport and the Streamable HTTP client feature flag names are unchanged in 3.8; check the 3.8 README.
- Windows-specific stdio issues (process-group kill, `.cmd` shims for npx) were not researched.
- I did not read migration guide #969.

## Q4. Architecture of open-source Rust agent apps (Codex, Goose, Zed, Warp)

### Takeaway
Codex is the best reference for EvoFlux: a ~150-member Cargo workspace with a clean `protocol` / `core` / front-end split. It uses an async submission-queue/event-queue model (`Op` in, `EventMsg` out), a central `ToolRouter` that enforces approvals and picks a sandbox, and per-OS sandboxes. Goose is MCP-native, is being refactored into a re-entrant per-turn state machine and a developer kit, and now lives under the Linux Foundation's Agentic AI Foundation (AAIF). Zed's public contribution is ACP (Agent Client Protocol) rather than a reusable runtime.

### Cited Findings
- **Codex rewrite rationale** (from GitHub Discussion #1174 by maintainer Fouad Matin, as reported by secondary sources, mid-2025):
  - zero-dependency install, since the TS version required Node 22+
  - native sandboxing: Seatbelt and Landlock had needed FFI shims in Node
  - performance and maintainability as complexity grew
  - an extensible wire protocol so other languages can drive the core
  The npm TS package remains as a wrapper. — [devclass (Jun 2025)](https://devclass.com/2025/06/02/node-js-frustrating-and-inefficient-openai-rewrites-ai-coding-tool-in-rust/); [danielvaughan blog (Mar 2026, secondary)](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/)
  - Caveat: one comparison blog's startup benchmarks lacked verifiable sourcing and were excluded. — [mer.vin](https://mer.vin/2025/12/ai-cli-tools-comparison-why-openai-switched-to-rust-while-claude-code-stays-with-typescript/)
- **Codex workspace members** (current main) include `core`, `core-api`, `protocol`, `app-server`, `app-server-protocol`, `exec`, `exec-server`, `execpolicy`, `tui`, `tools`, `hooks`, `skills`, `rmcp-client`, `codex-mcp`, `sandboxing`, `linux-sandbox`, `bwrap`, `windows-sandbox-service`, `network-proxy`, `process-hardening`, `secrets`, `keyring-store`, `rollout`, `state`, `thread-store`, `agent-roles`, `agent-graph-store`, `agent-message-board-client`, `ext/agent`, `ext/mcp`, `ext/memories`, `ext/web-search`, `model-provider`, `model-provider-info`, `models-manager`, `ollama`, `lmstudio`, `codex-api`, `codex-client`, `otel` and `utils/*`.
  - Key dependencies: `tokio = "1"`, `tokio-util = "0.7.18"`, `landlock = "0.4.4"`, `seccompiler = "0.5.0"`, `wiremock = "0.6"`, `insta = "1.46.3"`.
  — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- **Codex concurrency and tools:**
  - Clients submit `Op` values (`UserTurn`, `Interrupt`, `Shutdown`) and consume `EventMsg` streams. The TUI and IDE front-ends are pure event consumers.
  - `codex-app-server` is a JSON-RPC 2.0 bridge for IDEs.
  - All tool calls pass through `ToolRouter`, which enforces approval policy and selects a sandbox. `UnifiedExecProcessManager` manages process lifecycles.
  — [danielvaughan blog (Mar 2026, secondary)](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/)
- **Codex sandboxing:**
  - macOS: Seatbelt (`sandbox-exec`)
  - Linux: Landlock + seccomp (plus a `bwrap` crate in the current workspace)
  - Windows: restricted token + ACLs
  - modes: `read-only`, `workspace-write`, `danger-full-access`, applied to the whole process tree of a tool call
  — [danielvaughan blog, secondary](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/); [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml)
- **Goose:**
  - Rust core (agent loop, extensions, tool execution) with a TypeScript/React desktop UI.
  - Sessions persist as JSONL; history search uses SQLite.
  - "Adversary mode" (Mar 2026) is a reviewer agent that vets sensitive tool calls.
  - In late 2025 the Linux Foundation formed AAIF, bringing MCP, Goose and AGENTS.md under neutral governance. The repo now appears under the `aaif-goose` org.
  — [danielvaughan blog (Apr 2026, secondary)](https://codex.danielvaughan.com/2026/04/07/goose-mcp-native-architecture/); [Goose discussion #10579](https://github.com/aaif-goose/goose/discussions/10579)
- **Goose Q3 2026 roadmap** (2026-07-20):
  - unroll the agent loop into a re-entrant state machine that advances one turn at a time, with the conversation as the state
  - compose it from independent operations: model call, tool approval and execution, compaction, elicitation, retries, subagents
  - split into crates and become a "developer kit" (GDK), with the desktop app kept as a reference client
  - stated benefits: testability, embedding in event-driven systems, mid-session customization, horizontal scaling
  — [Goose Roadmap 2026 Q3](https://github.com/aaif-goose/goose/discussions/10579)
- **Zed and ACP.** The `agent-client-protocol` crate (v0.11.x) implements both sides of ACP, a JSON-RPC 2.0-over-stdio protocol by Zed Industries for editor ↔ agent communication. It powers Zed's external-agent integration. — [docs.rs agent-client-protocol 0.11.1](https://docs.rs/crate/agent-client-protocol/0.11.1/source/README.md); [agentclientprotocol.com Rust](https://agentclientprotocol.com/libraries/rust)

### Inferences
Recommended crate layout for EvoFlux, mirroring Codex:
- `evo-protocol`: serde types for Ops and Events, shared with the desktop UI
- `evo-providers`: wire protocols plus provider-info data
- `evo-mcp`: an rmcp wrapper
- `evo-tools`: router, wave scheduler, approvals
- `evo-sandbox`: per-OS sandboxing
- `evo-core`: agent loop as a state machine (the Goose direction)
- `evo-hooks` and `evo-skills`
- `evo-teams`: multi-agent delegation, analogous to Codex `agent-roles`, `agent-message-board` and `ext/agent`
- `evo-store`: rollout and session persistence

Other lessons:
- The submission/event-queue boundary (`Op` / `EventMsg`) maps directly onto a desktop app: the UI process submits Ops and renders Events. It also makes the core front-end-agnostic.
- Writing the loop as a re-entrant per-turn state machine, as Goose is now doing, rather than one long async function makes deterministic testing, persistence/resume and multi-agent orchestration much easier. It is worth doing from day one, not as a later refactor.
- If EvoFlux wants to host external agents or be hosted by IDEs, ACP (`agent-client-protocol`) is the emerging interop standard alongside MCP.

### Gaps
- No primary source was found on Zed's internal `language_model` / `agent` crates, or on Warp's agent architecture (Warp is closed-source). This research did not cover them.
- Codex's exact tool-call concurrency policy (parallel tool calls, any max-concurrency limit) was not found. Check `codex-rs/core/src/tools/` directly.
- The original Codex Discussion #1174 was not fetched; its contents come via secondary reports.

## Q5. Deterministic testing of agent loops and cancellation

### Takeaway
Codex's test suite is the reference pattern. It uses `wiremock` 0.6 `MockServer` with typed SSE event builders (`ev_function_call`, `ev_reasoning_text_delta`, `ev_completed_with_tokens`, …), sequenced per-request responses, and request-capture matchers that assert invariants such as no orphaned tool calls. It adds `insta` snapshots for the UI. Cancellation in Codex is a first-class `Op::Interrupt`. Its dependency on `tokio-util` is consistent with `CancellationToken`-style propagation, though this was not confirmed from source.

### Cited Findings
- **Mounting helpers in `codex-rs/core/tests/common/responses.rs`:**
  - `start_mock_server()`
  - `mount_sse_once`, `mount_sse_once_match`
  - `mount_sse_sequence(server, bodies)`, which serves one body per request in order
  - `mount_function_call_agent_response`
  — [codex responses.rs](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/tests/common/responses.rs)
- **SSE builders in the same file:**
  - `sse(events)`, `sse_completed`, `sse_failed`
  - text and reasoning events: `ev_response_created`, `ev_output_text_delta`, `ev_reasoning_text_delta`, `ev_reasoning_summary_text_delta`
  - tool-call events: `ev_function_call`, `ev_custom_tool_call`, `ev_exec_command_call`
  - completion: `ev_completed_with_tokens`
  — [codex responses.rs](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/tests/common/responses.rs)
- **Request capture.** A `ResponseMock` matcher records every request and runs `validate_request_body_invariants`, which panics on orphaned or unmatched tool calls and outputs. Request inspectors include `body_json`, `tool_by_name`, `function_call_output`, `instructions_text` and `header`. There are also WebSocket test servers (`start_websocket_server`, `gate_response_event`) for gating event timing. — [codex responses.rs](https://raw.githubusercontent.com/openai/codex/main/codex-rs/core/tests/common/responses.rs)
- **Test layout.** `codex-rs/core/tests` has `common/`, `suite/`, `all.rs` (a single integration-test binary), `responses_headers.rs`, `mcp_trace_propagation.rs` and `windows_sandbox.rs`. — [GitHub codex core/tests](https://github.com/openai/codex/tree/main/codex-rs/core/tests)
- **Other test tooling.** Codex has `cloud-tasks-mock-client`, `app-server-test-client` and `test-binary-support` crates, and `insta` snapshots are required for TUI changes. Goose also uses `wiremock = 0.6`. — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml); [danielvaughan blog](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/); [goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml)
- **Cancellation.** Codex exposes `Op::Interrupt` and `Op::Shutdown` as submissions. — [danielvaughan blog, secondary](https://codex.danielvaughan.com/2026/03/28/codex-rs-rust-rewrite-architecture/)

### Inferences
- **Recommended test strategy for EvoFlux:**
  1. Per wire protocol, build typed SSE fixture builders (Anthropic `content_block_delta`, `thinking_delta`, `message_delta` usage, and so on). Golden-record real streams once, store them as `.sse` fixtures, and replay them through wiremock.
  2. Use `mount_sse_sequence` to script multi-turn tool loops.
  3. Add a request-invariant matcher: every tool_use must have a tool_result, cache_control breakpoints must be in the expected positions, and there must be at most 4 breakpoints for Anthropic.
  4. For concurrency-wave tests, use `tokio::time::pause()` with fake tools that await gates (like Codex's `gate_response_event`) so ordering is deterministic.
  5. Run everything as a single `tests/all.rs` binary, which keeps build times down.
- **Cancellation design.** Use one `tokio_util::sync::CancellationToken` per turn with child tokens per model call and per tool call. Model streams `select!` on token or next chunk. Dropping the reqwest response future aborts the HTTP request. Tool subprocesses need explicit process-tree kill: process groups on Unix, Job Objects on Windows. MCP calls should send `notifications/cancelled`. Tool results for cancelled calls must still be synthesized ("cancelled by user") so the transcript stays valid; this is the invariant Codex's tests enforce.

### Gaps
- I did not verify from Codex source how `Op::Interrupt` propagates (CancellationToken vs `AbortHandle`) or how cancelled tool outputs are recorded.
- No sources were reviewed for record/replay crates (for example, VCR-style crates for reqwest).

## Q6. Tokenizer / token counting crates

### Takeaway
Not researched in this pass. Notably, the Codex workspace declares neither `tiktoken-rs` nor `tokenizers` at workspace level. This suggests a production agent can rely on provider-reported usage plus heuristic estimates rather than local tokenizers.

### Cited Findings
- `tiktoken-rs` and `tokenizers` do not appear in codex-rs `[workspace.dependencies]`, and neither appears in Goose's workspace dependency list. — [codex-rs Cargo.toml](https://raw.githubusercontent.com/openai/codex/main/codex-rs/Cargo.toml); [goose Cargo.toml](https://raw.githubusercontent.com/block/goose/main/Cargo.toml)

### Inferences
- For compaction triggers and context budgeting, use provider-reported usage from the previous turn plus a bytes/4-style estimate for new content. Add `tiktoken-rs` (OpenAI BPE) or HF `tokenizers` only if exact pre-flight counts are required. Anthropic and Gemini expose count-tokens endpoints, which are more accurate than any local tokenizer for those models.

### Gaps
- Not researched: crates.io versions, maintenance and download stats for `tiktoken-rs` and `tokenizers`, and whether the two might be declared in member crates' own Cargo.toml (only workspace root files were checked).
