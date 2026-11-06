# evo — a Rust-native coding-agent runtime

[![crates.io](https://img.shields.io/crates/v/evo-cli.svg)](https://crates.io/crates/evo-cli)
[![downloads](https://img.shields.io/crates/d/evo-cli.svg)](https://crates.io/crates/evo-cli)
[![docs.rs](https://docs.rs/evo-cli/badge.svg)](https://docs.rs/evo-cli)
[![license](https://img.shields.io/crates/l/evo-cli.svg)](#license)
[![MSRV](https://img.shields.io/badge/MSRV-1.89-blue.svg)](#install)
[![CI](https://github.com/evoelsewhere/evo-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/evoelsewhere/evo-harness/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/evoelsewhere/evo-harness?style=flat)](https://github.com/evoelsewhere/evo-harness/stargazers)
[![Latest release](https://img.shields.io/github/v/release/evoelsewhere/evo-harness)](https://github.com/evoelsewhere/evo-harness/releases/latest)

`evo` is a library-first coding-agent runtime written in Rust, plus a terminal
agent built on top of it. Eleven composable crates span provider adapters, a
durable crash-resumable agent loop, a terminal UI, and a stable plugin ABI — so
the same code works as an embedded SDK or as a ready-to-run `evo` command.

![evo interactive session](docs/images/evo-interactive.png)

<sub>Interactive TUI. See [`docs/guides/user-guide.md`](docs/guides/user-guide.md) for the full command surface.</sub>

![evo SDK demo — an agent loop and a real tool round-trip, offline with the faux provider](docs/images/evo-sdk-demo.gif)

<sub>The agent loop and a real `write` tool round-trip, recorded with no API key and no network — the same path the tests take. Source of truth is [`demo/sdk.tape`](demo/sdk.tape); regenerate with `task demo`.</sub>

## Three ways to use it

| You want | Depend on | Start at |
| -------- | --------- | -------- |
| A working terminal coding agent | nothing | `cargo install evo-cli` |
| Your own agent inside your process | `evo-agent` (+ `evo-ai`, `evo-tools`) | [`examples/minimal`](examples/minimal) |
| A tool/provider that extends every session | `evo-plugin-sdk` | [`examples/plugin-stub`](examples/plugin-stub) |

The three share one implementation. Build your tools once, debug them inside an
embedded agent, and ship the same code as a `cdylib` plugin that the global `evo`
loads. See [`docs/agent/project-structure.md`](docs/agent/project-structure.md) for the recommended
project layout.

## Install

**Prebuilt binary** (no Rust toolchain needed):

```bash
curl -fsSL https://raw.githubusercontent.com/evoelsewhere/evo-harness/main/scripts/install.sh | sh
```

Verifies the published SHA-256 checksum and installs to `/usr/local/bin` or
`~/.local/bin`. Preview first with `--dry-run`.

**From crates.io** (requires Rust 1.89+):

```bash
cargo install evo-cli
evo --version
```

**From source:**

```bash
git clone https://github.com/evoelsewhere/evo-harness.git
cd evo-harness && cargo run -p minimal   # offline agent, no API key required
```

Real output of the two offline examples — no credentials, no network, identical
bytes every run. Regenerate with `task demo-transcript`:

```text
$ cargo run -q -p minimal
minimal example: 2 messages after run
  - user
  - assistant
assistant reply: Hello from the faux provider!
AgentEnd observed.

$ cargo run -q -p tools-example
tools example: 4 messages after run
wrote out.txt (28 bytes): "hello from the tools example"
AgentEnd observed; tool ran against OsExecutionEnv.
```

## Quick start

### The CLI

```bash
export ANTHROPIC_API_KEY=...          # or OPENAI_API_KEY, or ~/.evo/agent/models.json
evo                                   # interactive TUI
evo -p "summarize the README"         # one-shot
evo --mode json -p "list the crates"  # machine-readable event stream
```

Sessions persist as JSONL and survive a crash mid-run; `evo` resumes from the
last committed frame rather than replaying the turn. Custom Anthropic or
OpenAI-compatible gateways are declared in `~/.evo/agent/models.json` and
selected with `--model <provider>/<model>`.

### Runtime diagnostics

To investigate slow model preparation, context construction, tool execution, or
persistent assistant-frame writes, temporarily enable stderr diagnostics:

```bash
EVO_AGENT_DIAGNOSTICS=1 EVO_FRAME_DIAGNOSTICS=1 \
  evo -p "reproduce the issue" 2>evo-diagnostics.log
```

`EVO_AGENT_DIAGNOSTICS` reports context, request, tool, and session append
latencies. `EVO_FRAME_DIAGNOSTICS` reports durable frame batching, flush barriers,
and writer failures. Diagnostics are disabled when the variables are unset or
set to `0`; they do not change the JSONL format. See
[`docs/debugging/rust-debugging.md`](docs/debugging/rust-debugging.md) for the
field reference. The built-in read-only `docs` tool can retrieve it with
`{"topic":"debugging","query":"EVO_FRAME_DIAGNOSTICS"}`.

### Request timeouts and model compatibility

`--timeout 600` limits a whole LLM request, including its streamed response.
`--stream-idle-timeout 300` independently limits silence between response body
bytes after the response starts. Every non-empty chunk resets the idle timer,
including SSE keepalives and partial frames. A stalled stream produces a
retryable error; the configured retry policy controls whether it is retried.
Healthy streams may run longer than the idle timeout, up to the total deadline.
Use `--stream-idle-timeout 0` to disable the idle timer. You can also set
`"streamIdleTimeout": 300` (seconds) in `~/.evo/agent/settings.json`; the CLI flag
takes precedence. `httpIdleTimeout` only expires unused pooled connections and
does not control an active response.

For providers with `"api": "openai-completions"`, put compatibility flags in
each model's `compat` object in `~/.evo/agent/models.json`, for example:

```json
"compat": {
  "thinkingFormat": "deepseek",
  "requiresReasoningContent": true
}
```

`requiresReasoningContent` replays assistant thinking in `reasoning_content`,
including an empty string for assistant messages without thinking. The evo name
`requiresReasoningContentOnAssistantMessages` is accepted as an alias; if both
are present, the evo spelling wins and conflicting values produce a warning.
`thinkingFormat` supports `"openai"` (the default request
shape) and `"deepseek"` (also sends `thinking: { "type": "enabled" | "disabled" }`
for reasoning-capable models). `supportsReasoningEffort: false` suppresses
`reasoning_effort` if the gateway does not accept it. `requiresThinkingAsText`
instead places thinking in ordinary text content. Unknown compat fields and
invalid values produce warnings naming the provider and model; invalid compat
objects are ignored. Other evo thinking formats are not currently supported.

### The SDK

Build an agent against a deterministic in-process provider — no API key, no
network, no flakiness:

```rust
use evo_agent::AgentBuilder;
use evo_ai::providers::faux::{FauxProvider, FauxScript};
use evo_ai::Provider;

#[tokio::main]
async fn main() {
    // `FauxProvider::new` already returns an `Arc<Self>`.
    let provider = FauxProvider::new(FauxScript::new().with_text("Hello from the faux provider!"));
    let model = provider.default_model().clone();

    let agent = AgentBuilder::new()
        .model(model)
        .system_prompt("You are a helpful assistant.")
        .stream_fn(make_stream_fn(provider))
        .build()
        .expect("agent builds");

    let mut events = agent.subscribe();
    agent.prompt("hi").await.expect("prompt completes");

    while let Ok(ev) = events.try_recv() {
        let _ = ev; // AgentEvent::{MessageUpdate, ToolEnd, AgentEnd, …}
    }
    println!("{} messages after the run", agent.state().messages.len());
}
```

`make_stream_fn` bridges the synchronous `StreamFn` contract to the async
provider — the full version is in [`examples/minimal/src/main.rs`](examples/minimal/src/main.rs)
(`cargo run -p minimal`).

## Crates

Ten workspace crates, one shared version. Dependency direction is one-way
and enforced in review:

```
evo-telemetry → evo-ai → evo-agent → evo-tools → evo-harness
```

Five crates sit outside that chain:

- `evo-tui` depends on no other `evo-*` crate.
- `evo-runtime` provides embeddable model catalogs, provider-scoped credentials and execution bindings on top of `evo-ai`.
- `evo-plugin-sdk` is a leaf too (it has no `evo-*` deps), but it is not only
  the host's plugin contract: `evo-tools` also reads its env-var names, so the
  host and its plugins cannot disagree about the strings they exchange across
  the ABI. That edge is names-only — nothing is linked or called.
- `evo-extensions` is `evo-plugin-sdk` plus `evo-ai`/`evo-agent`, since it hosts
  plugins that run tools.
- `evo-cli` depends on all nine of the others, which is how the `evo` binary
gets the TUI, the harness and the plugin loader at once.

| Crate | What it is |
| ----- | ---------- |
| [`evo-telemetry`](https://crates.io/crates/evo-telemetry) | Span/event contracts with a no-op default — instrumentation is opt-in, and pulls in no tracing or OpenTelemetry backend |
| [`evo-ai`](https://crates.io/crates/evo-ai) | Provider-agnostic message, streaming and tool-schema types; Anthropic + OpenAI-compatible + `faux` providers |
| `evo-runtime` | Embeddable model catalog, credential resolution, model selection and private execution bindings (not yet published) |
| [`evo-agent`](https://crates.io/crates/evo-agent) | The agent loop: `AgentTool`, events, hooks, queues, cancellation |
| [`evo-tools`](https://crates.io/crates/evo-tools) | `read`/`write`/`edit`/`bash` (+ `grep`, `find`, `ls`, `powershell`) and the `ExecutionEnv` seam |
| [`evo-harness`](https://crates.io/crates/evo-harness) | Session tree, JSONL persistence, compaction, crash recovery, the run loop |
| [`evo-tui`](https://crates.io/crates/evo-tui) | Terminal UI primitives: components, layout, editor, transcript rendering |
| [`evo-cli`](https://crates.io/crates/evo-cli) | The `evo` binary: TUI, one-shot and JSON modes, config, plugin loading |
| [`evo-plugin-sdk`](https://crates.io/crates/evo-plugin-sdk) | The stable `#[repr(C)]` ABI contract for plugins. No `evo-*` deps; only `serde_json`, behind a default `json` feature that can be turned off |
| [`evo-extensions`](https://crates.io/crates/evo-extensions) | Host-side plugin loader and the async-across-ABI tool bridge |

Every crate has its own README and docs.rs page. The `crates/evo-*`
directories and the published crate names use the same `evo-` prefix.

## Why evo

Most coding agents are CLIs. `evo` is a **runtime with a CLI attached**, which
changes what you can build with it:

- **Embeddable.** The agent loop is a library. `evo-agent` + `evo-ai` is enough
  to run an agent inside your own process, with your own event handling and
  output — no shelling out to a tool and scraping stdout.
- **Testable offline.** A deterministic `faux` provider and an in-memory
  execution environment are first-class, not mocks bolted on. `evo-ai` puts its
  real HTTP providers behind a `providers` feature flag, so your test suite
  cannot silently depend on the network for the paths you exercise.
- **Durable.** Sessions are a tree with JSONL persistence and per-frame
  progress. A crash mid-tool-call resumes instead of losing the turn or
  double-executing the tool.
- **Extensible across a stable boundary.** Plugins are Rust `cdylib`s behind a
  hand-written, panic-contained C ABI with version negotiation — the ABI
  survives compiler and crate version skew, so extensions do not break on every
  release.
- **One implementation, two surfaces.** The global CLI and an embedded agent load
  the same tools. You do not maintain a plugin and a library variant separately.

### How it compares

Structural differences against other terminal coding agents. Facts about other
tools are as of 2026-09 and change often — check their documentation; only the
`evo` column is maintained here.

| | evo | Claude Code | Codex CLI | opencode | aider |
| --- | --- | --- | --- | --- | --- |
| Language | Rust | TypeScript | Rust | TypeScript/Go | Python |
| Source available | ✅ MIT | ❌ | ✅ | ✅ | ✅ |
| Usable as an embedded library | ✅ | ❌ | ❌ | ⚠️ | ⚠️ |
| First-class plugin ABI | ✅ | hooks/MCP | ❌ | plugin API | ❌ |
| Headless server + remote client | ✅ | ⚠️ | ✅ | ✅ | ⚠️ |
| Provider-agnostic gateways | ✅ | ❌ | ❌ | ✅ | ✅ |

If you want the most polished single-vendor experience, use the vendor's tool.
`evo` is for people who want to own the loop.

## Performance

Measured on Windows 11 (x86_64), rustc 1.97.1, `--release`. Both scripts
rebuild and re-measure on your own machine.

`sh scripts/bench.sh` — standalone numbers:

| Metric | Value |
| ------ | ----- |
| Release binary size | **21.8 MiB** |
| `evo --version` wall time | **~17 ms** median |
| RSS once the agent is ready | **12.0 MiB** |

`node scripts/bench-vs-evo.mjs --evo <path-to-evo>` — against native Evo on the same
machine, both offline, each with a fresh isolated config directory:

| Metric | evo (Rust) | evo (TypeScript) | Difference |
| ------ | ---------: | --------------: | ---------- |
| `--version` | **17.5 ms** | 169.5 ms | **9.7× faster** |
| Cold start | **17.7 ms** | 189.5 ms | **10.7× faster** |
| RSS at ready | **12.0 MiB** | 91.5 MiB | **7.6× smaller** |
| Install footprint | **21.8 MiB** (one binary) | ~385 MiB (+ ~91 MiB Node) | **~18–22× smaller** |

**Cold start** is spawn → the agent answering its first command: process creation
plus full initialisation, excluding teardown and any LLM work. evo's `--version`
(17.5 ms) and cold start (17.7 ms) are effectively equal, so startup is process
creation, not initialisation; Evo is dominated by Node boot.

Isolation caveat: evo reads `EVO_CODING_AGENT_DIR` / `EVO_OFFLINE`, native Evo reads
`EVO_CODING_AGENT_DIR` / `EVO_OFFLINE`. Set the matching pair for each, or evo
silently loads the machine's global plugins.

Method, raw per-run numbers, and what is *not* measured (LLM latency, tool-loop
throughput, long sessions, TUI frame cost) are in
[`docs/performance/benchmark-vs-evo.md`](docs/performance/benchmark-vs-evo.md).

## Plugins

Plugins are Rust `cdylib` libraries behind a stable `#[repr(C)]` ABI. A plugin
can register tools, providers, slash commands, event handlers, markdown
renderers and discovered resources.

```bash
evo install evo-todo                    # prebuilt extension; no Rust toolchain needed
evo install my-ext --path ../my-ext     # local, for development
evo extension update [name]             # all eligible extensions, or one by name
evo dev                                 # build + watch + live reload
```

Use `evo extension update` to update all project-linked extensions and globally
installed registry/prebuilt extensions, or `evo extension update <name>` to select
one by name. Updates preserve the original Cargo build backend or explicit GitHub
source. Global development installs made with `--path` are excluded. The old
`evo package update [name]` remains compatible; prefer `extension update` for
extension updates. Project linking commands remain `evo package link`,
`evo package list`, and `evo package unlink`.

The host loads project `.evo/extensions`, then global
`~/.evo/agent/extensions`, then any `--extensions-dir`.

For a new Rust plugin, start with [`docs/extensions/authoring.md`](docs/extensions/authoring.md)
and `examples/plugin-stub`. Use `evo-plugin-sdk` for the `cdylib` ABI. If the plugin
project also needs reusable session, workspace, native RPC or durable-runtime logic
for a Web/ACP adapter, add [`evo-extcore`](https://crates.io/crates/evo-extcore)
(`evo-extcore = "0.1"`). It is a normal Rust library, not the `cdylib` entry point,
and it does not replace `evo-plugin-sdk`; a simple tool plugin should not add it
unnecessarily.

Ready-to-install extensions live in the companion
[`evoelsewhere/evo-package`](https://github.com/evoelsewhere/evo-package) repository.

### Optional web and subagent tools

```bash
evo install evo-websearch                # websearch: titles, URLs and snippets
evo install evo-webfetch                 # webfetch: readable text from public pages
evo install evo-subagents                # delegate_task: host-managed child agents
```

Restart evo after installation. These are independent extensions, not default
CLI tools. Web search/fetch do not provide browser clicks, login flows or page
JavaScript execution.

Subagents inherit a snapshot of the parent's current model/provider binding,
thinking level, prompt, resources, request options, active tools, cwd and
approval hooks. Credentials stay inside the host. Children use independent
in-memory sessions without copying or modifying the parent history; their tool
set can only be narrowed, and recursive delegation is rejected. Parent approvals
remain in effect, and parent completion or cancellation stops the child. This is
not an OS sandbox. Use compatible host and extension versions; unsupported hosts
fail explicitly rather than starting a subprocess with different defaults.

The SDK entry point is `AgentHarness::create_child`; extensions use
`GetExecutionContext` and `ChildAgent` runtime actions. See the
[subagent protocol](https://github.com/evoelsewhere/evo-harness/blob/main/docs/extensions/subagents.md)
for lifecycle, limits and compatibility details.

### Authoring an extension

```rust
use evo_plugin_sdk::{export_plugin, StbStringRef};

export_plugin!(|api| {
    if let Some(declare) = api.declare {
        declare(StbStringRef::from_str(r#"{"priority":60,"platforms":["linux"]}"#));
    }
    // register tools / handlers through `api`
    0
});
```

Start from [`examples/plugin-stub`](examples/plugin-stub) — a complete plugin
with the full `execute`→`poll`→`cancel`→`destroy` lifecycle — and read
[`docs/extensions/authoring.md`](docs/extensions/authoring.md) for the safety
rules, which are load-bearing rather than stylistic.

## Remote mode

```bash
evo --server                        # headless agent over TCP, prints an auth token
evo --connect host:port --token T   # TUI client with zero local agent resources
```

The client holds no provider, tools, extensions or session files — all agent
work happens on the server, so a thin terminal anywhere can drive a beefy
machine. See [`docs/remote/user-guide.md`](docs/remote/user-guide.md).

## Project status

| | |
| --- | --- |
| Current release | **[0.1.0](https://github.com/evoelsewhere/evo-harness/releases)** (eleven crates, published together) |
| Stability | `evo-ai`, `evo-agent`, `evo-tools`, `evo-harness`, `evo-plugin-sdk` are the intended stable surface |
| MSRV | 1.89 |
| Platforms | Linux, macOS, Windows (CI runs the suite on Linux) |
| Binary release targets | Linux (x86_64/aarch64), macOS (Intel/Apple silicon), Windows (x86_64) |

`evo` is a self-contained Rust coding-agent stack. No Node component is
required and none is loaded.

## Documentation

- [User guide](docs/guides/user-guide.md) — commands, config, sessions, skills
- [Architecture](docs/architecture/overview.md) — how the crates fit together and why
- [Building an agent project](docs/agent/project-structure.md) — recommended structure
- [Extension authoring](docs/extensions/authoring.md) — plugin templates and ABI rules
- [Subagents](https://github.com/evoelsewhere/evo-harness/blob/main/docs/extensions/subagents.md) — configuration inheritance, permissions and lifecycle
- [Remote mode](docs/remote/user-guide.md) — protocol, tokens, limitations
- [Roadmap](ROADMAP.md) · [Changelog](CHANGELOG.md)
- [docs.rs](https://docs.rs/evo-cli) for per-crate API docs

## Contributing

Issues and PRs are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) for the
build/test commands and the repository layout, and the
[roadmap](ROADMAP.md) for what is already planned. Security problems should go
through [SECURITY.md](SECURITY.md), not a public issue.

The whole test suite runs offline: `cargo test --workspace --locked`.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

The `evo-*` crates are a Rust-native coding-agent stack.

## Star history

[![Star History Chart](https://api.star-history.com/svg?repos=evoelsewhere/evo-harness,evoelsewhere/evo-package&type=Date)](https://www.star-history.com/#evoelsewhere/evo-harness&evoelsewhere/evo-package&Date)
