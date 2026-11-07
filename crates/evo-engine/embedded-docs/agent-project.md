# evo Agent Project Structure Guide

This guide is the model-readable default specification. When the task is to "create your own Agent",
"set up the Agent structure", or "add an evo entry point to an existing project" with the evo SDK, organize the project as described here. The default recommendation is a single crate:
the embedded Agent and the global `evo` extension share the same set of tools (see §1); trim the other forms as needed.

Do not write tools first and think about structure later. Decide the form first, then lay out the directories, and wire up the entry points last.

## 1. Choose the form first

| Form | Launch entry point | Direct dependencies | Use case |
| --- | --- | --- | --- |
| Library-embedded Agent | Your `[[bin]]` / service process | `evo-agent` + `evo-ai` (add `evo-tools` if you need the built-in tools) | Run the loop in your own process, with full control over events, tools, and output |
| CLI project | Global `evo` host | None (resources and a cdylib) | You want the ready-made TUI, `-p`/`--mode json`, sessions, and skills |
| Rust extension | Host loads `.evo/extensions/*.dll` | `evo-plugin-sdk` | Add tools/Providers/events to the global `evo` without modifying the host |

A single project **can provide both an "embedded Agent" adapter and a "cdylib extension" adapter at the same time, sharing one tool implementation**.
This is also the form this guide recommends by default: debug locally with the embedded Agent, and for production/interactive use have the global `evo` load
the same extension. Build only one of the two when the requirements are narrow enough.

If the extension also serves as a Web/ACP or other native RPC adapter and needs sessions, workspaces, event replay, or
durable state, you can reuse `evo-extcore = "0.1"` from crates.io. It is an ordinary Rust service library;
it does not replace the `cdylib` ABI of `evo-plugin-sdk`, nor does it provide an HTTP/ACP frontend of its own. Ordinary tool plugins
should keep `evo-plugin-sdk` as their single dependency.

## 2. Recommended directory structure

```text
my-agent/
├── Cargo.toml
├── AGENTS.md                  # Project-level fallback instructions (also read by bare evo)
├── config/
│   └── agent.json             # Project Agent config (system prompt / skill dirs / artifacts)
├── prompts/
│   ├── system.md              # Main system prompt
│   └── append-system.md       # Appended system prompt
├── skills/
│   └── <skill-name>/SKILL.md  # Domain skills, activated dynamically at runtime by description/trigger words
├── src/
│   ├── main.rs                # Embedded Agent / service entry point
│   ├── lib.rs                 # Module exports (+ optional cdylib ABI adapter)
│   ├── config.rs              # Runtime config (environment variables / files)
│   └── tools/
│       ├── mod.rs             # The one tool registry (single source of truth)
│       ├── core.rs            # Single run_tool entry point + domain logic
│       └── content.rs         # AgentTool adapter (used by the embedded Agent)
├── .evo/
│   ├── settings.json          # skillDirs / promptDirs / extensionDirs / defaultTools
│   └── extensions/            # Compiled cdylibs (build output, not committed)
└── tests/
    └── behavior.rs
```

Conventions:

- `.evo/` is evo's project resource directory; **for resources with the same name, the in-project definition takes precedence**
  (project over global, `.evo` over `.evo`, packages last).
- `prompts/`, `skills/`, and `config/` are **ordinary, reviewable source directories**; do not hide them inside `.evo`
  or depend on paths that an extension generates temporarily at runtime.
- `target/`, `.evo/extensions/`, and `artifacts/` are build output; add them to `.gitignore`.
- Write generation constraints into the system prompt as fixed text; do not rely on the model re-inferring them in every session.

## 3. Cargo.toml

When the embedded Agent and the cdylib share one source, a single package declares both `[[bin]]` and `[lib]`:

```toml
[package]
name = "my-agent"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "agent"
path = "src/main.rs"

[lib]
name = "my_agent"
path = "src/lib.rs"
crate-type = ["cdylib", "rlib"]   # cdylib for the host; rlib for integration tests

[dependencies]
# Below, `<evo>` stands for the current evo release version; replace it with the actual version number (e.g. `0.1.x`),
# and keep all `evo-*` dependencies on the same version; add or remove third-party dependencies as needed.
evo-agent = "<evo>"
evo-ai = { version = "<evo>", features = ["providers"] }
evo-tools = "<evo>"
evo-plugin-sdk = "<evo>"          # Only needed for the cdylib adapter
tokio = { version = "1", features = ["full"] }
async-trait = "0.1"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
schemars = "0.8"
thiserror = "1"

[dev-dependencies]
# Use the faux provider for offline tests, with no dependency on the network or an API key
```

Boundary rules:

- **Extensions depend only on `evo-plugin-sdk`, never on internal modules of `evo-cli`, `evo-extensions`, or `evo-harness`**
  -- the host links the plugin, not the other way around; otherwise the ABI and versions become coupled.
- The embedded Agent depends only on `evo-agent`/`evo-ai`/`evo-tools` and is decoupled from the extension ABI.
- Add `evo-harness` only when you need sessions, compaction, skills, or context files.

## 4. Single tool registration point

Declare each tool only once; both host adapters derive their own schemas from that one declaration, which prevents two implementations from drifting apart.

`src/tools/mod.rs`:

```rust
pub struct ToolSpec {
    pub name: &'static str,
    pub description: &'static str,
    pub props: serde_json::Value,        // JSON Schema properties
    pub required: &'static [&'static str],
}

pub static TOOLS: std::sync::LazyLock<Vec<ToolSpec>> = std::sync::LazyLock::new(|| {
    vec![ToolSpec {
        name: "lookup",
        description: "Look up symbol definitions in the project.",
        props: serde_json::json!({
            "symbol": {"type": "string", "description": "Name of the symbol to look up"}
        }),
        required: &["symbol"],
    }]
});

/// The single execution entry point shared by all hosts.
pub fn run_tool(name: &str, params: &serde_json::Value)
    -> Result<serde_json::Value, ToolError>
{
    match name {
        "lookup" => lookup::run(params),
        other => Err(ToolError::new(format!("unknown tool `{other}`"))),
    }
}
```

`src/tools/core.rs` holds the shared logic; `src/tools/content.rs` only does orchestration (wrapping `run_tool`
as an `evo_agent::AgentTool`); the cdylib side only does ABI orchestration. None of the three re-implements domain logic.

For each tool, add a unit test asserting that its schema is identical between the two hosts (see §11).

## 5. Embedded Agent

Minimal closed loop: construct the provider/model → `AgentBuilder` → subscribe to events → `prompt`.

```rust
use std::sync::Arc;
use evo_agent::AgentBuilder;
use evo_ai::Provider;

let model = provider.default_model().clone();
let agent = AgentBuilder::new()
    .model(model)
    .system_prompt(compose_system_prompt())     // prompts/system.md + append
    .tools(create_agent_tools())                // Derived from TOOLS
    .stream_fn(make_stream_fn(provider))        // Synchronous wrapper around Provider::stream_simple
    .build()?;

let mut events = agent.subscribe();
agent.prompt(user_input).await?;

while let Some(event) = events.recv().await {
    if matches!(event, evo_agent::AgentEvent::AgentEnd { .. }) {
        break;
    }
    // Forward MessageUpdate / ToolExecutionStart / ToolResult to your UI or logs
}
```

Key points:

- **Call `subscribe` before `prompt`**; otherwise early events will be missed from the broadcast buffer.
- Custom tools implement `evo_agent::AgentTool`: `schema()` returns an `evo_ai::types::Tool`;
  `execute(tool_call_id, params, signal, on_update)` parses the JSON, checks `signal`, and
  returns an `AgentToolResult`. Map parameter parsing failures to structured errors; do not panic.
- Use the faux provider + `InMemoryExecutionEnv` for offline tests: no network, API key, or real filesystem required.
- When you need CLI-level sessions/compaction/skills, use `evo-harness` instead of rebuilding them yourself.

## 6. cdylib ABI adapter (for the global `evo`)

The host loads only the unified C ABI symbol `evo_plugin_register`. The extension uses `export_plugin!`,
registers its capabilities through the same `PluginApi`, and calls `api.declare` to declare priority/platform.
The SDK checks `abi_version` and `struct_size` before registration; if incompatible, it returns a non-zero status and the host reports a load failure.

```rust
evo_plugin_sdk::export_plugin!(|api| {
    let Some(register_tool) = api.register_tool else {
        return -1;                         // Capability detection: fail explicitly if the slot is missing
    };
    // Build the StableToolSchema and the execute/poll/cancel/destroy
    // function table from the same TOOLS declaration, then call register_tool(...).
    let _ = register_tool;
    0
});
```

The tool lifecycle is fixed as `execute → poll → cancel → destroy`: `execute` allocates a per-call
handle, `poll` must be non-blocking and respond to the cancellation flag, `cancel` only sets the flag and does not free anything, and `destroy` is called
exactly once by the host and frees the handle. Nothing may unwind across any `extern "C"` boundary.

**Copy the skeleton from `examples/plugin-stub/src/lib.rs` first**, then replace the schema and domain logic;
do not redesign the ownership protocol. For the full ABI, capability detection, event handling, resource discovery, and release checks, see
the `authoring` topic in `docs`.

## 7. Project resources: prompts, skills, AGENTS.md

- `prompts/system.md`: the main system prompt; put responsibilities, workflow, and quality gates here (e.g. "for each content item, first
  `read` the corresponding skill's `SKILL.md`"). Injected at runtime via `--system-prompt` or config.
- `prompts/append-system.md`: the appended section, for environment-/project-specific constraints.
- `skills/<name>/SKILL.md`: domain skills. The model selects them dynamically from the `name`/`description` in
  `<available_skills>` at startup; **do not maintain a hard-coded topic→skill mapping**.
  Discovery (`loaded`) is not the same as use; the real evidence of activation is a complete `read` of that `SKILL.md` first.
  The frontmatter also supports `disable-model-invocation: true`: such a skill is not included in
  `<available_skills>` and can only be invoked explicitly by the user via `/skills <name>`.
- `AGENTS.md`: fallback instructions at the project root, also read by bare `evo`. Keep it consistent with the
  core constraints in `prompts/system.md`; when you change one, update the other.
- The system prompt and skills are loaded as a snapshot **at the start of each session**; restart the session after changes, since existing sessions are not hot-swapped.

## 8. `config/agent.json` (project convention)

`.evo/settings.json` is the evo host's native configuration. `config/agent.json` is the **project's own**
convention file, read by the embedded Agent launcher or wrapper scripts, so that "system prompt / skill directories / artifact directory /
default provider" live in one place:

```json
{
  "system_prompt": "prompts/system.md",
  "append_system_prompt": "prompts/append-system.md",
  "skills_dir": "skills",
  "skill_dirs": ["skills"],
  "extension_dirs": [".evo/extensions"],
  "disable_context_files": true,
  "artifacts_dir": "artifacts",
  "provider": "<default-provider>"
}
```

Fill in the values above according to the providers and directories your project actually uses; do not copy the example verbatim. `config/agent.json`
is not native evo configuration, only a convention of this project's launcher. Also use `.evo/settings.json` so the host
discovers resources natively:

```json
{
  "skillDirs": ["./skills"],
  "defaultTools": ["read", "bash", "edit", "write", "docs"]
}
```

`disable_context_files: true` prevents the wrapper launcher from being polluted by the `AGENTS.md`/`CLAUDE.md` of a parent repository;
when needed, turn context files off explicitly with `--no-context-files`.

## 9. Launching and the development loop

There are two sets of entry points; the scripts are only responsible for pinning the cwd, compiling, and forwarding arguments. Choose the script language per platform
(Windows `.ps1`/`.cmd`, Unix `.sh`, or a single runner such as Taskfile/just/make);
both sets of entry points keep the same responsibilities:

- **Embedded Agent**: a launch script → `cargo run --bin agent` (this project's process, talking directly to the SDK).
- **Global host**: a build script compiles the cdylib and copies it into `.evo/extensions`, then a launch
  script starts the global `evo`. The scripts should:
  1. Pin the working directory to the project root, to avoid loading another project's skills;
  2. Let the host **scan `.evo/extensions` natively**; do not also pass the same `--extensions-dir`;
  3. Pass `prompts/system.md` and `prompts/append-system.md` to the host explicitly;
  4. Choose a default provider/model only when no higher-priority setting exists, and print its source but **never print the API key**;
  5. Fail closed: fail up front when `--no-tools`, `--no-skills`, `--no-extensions`, or a
     `--tools` allowlist missing `read` is detected -- these prevent loading the content extension or reading skills.
- On Windows, a loaded DLL cannot be overwritten in place: compare SHA256 before copying and skip if the bytes are unchanged;
  if the file is in use, report an actionable error such as "stop the running evo and retry" instead of failing silently.

Edit loop: when changing a Rust extension, use `evo dev` (watch + hot reload, with versioned staging into
`.evo/extensions/.dev`); to debug only the current extension, use `evo dev-local` (isolated mode). Do not manually copy
the Cargo target DLL to a fixed filename.

## 10. Agent as a service (optional)

When running the Agent as a long-lived service, `main.rs` exposes an API using the HTTP framework the project already uses (e.g. `axum`, `actix-web`,
etc.; pick any one), adding message-queue consumers (MQTT/Kafka/NATS, etc.) when needed:

- `main.rs` only does orchestration: initialize `tracing` → load `Config::from_env()` → build `AppState`
  → start the HTTP server and hook up graceful shutdown.
- All configuration goes through environment variables (`.env.example` records the key names; **never commit real secrets**).
- Keep task/run state in a shared `Arc<TaskStore>`, and keep API handlers thin.
- When a container is needed, provide a multi-stage `Dockerfile`; the runtime stage carries only the binary and CA certificates,
  with `EXPOSE`/`CMD` pointing at the `main.rs` entry point.

## 11. Testing and release

- `cargo fmt --check`, `cargo clippy --all-targets`, and `cargo test` all pass.
- Write `rlib` unit tests for the domain logic; write at least one host smoke test for ABI registration/loading.
- Assert that **the schemas of the two hosts are identical**: the Agent schema and the ABI JSON derived from the same `TOOLS`
  must be equal, to prevent drift.
- `evo dev --no-watch` compiles, loads, and registers the expected tools; the clean install path of `evo install <crate> --force`
  succeeds.
- When providing a `cdylib`, `crate-type` includes `"cdylib"`, the library exports
  `evo_plugin_register`, and it depends on the published `evo-plugin-sdk`.
- The `README` documents the tool schemas, permission boundaries, persisted files, network access, supported platforms, and how to uninstall;
  paths stay consistent across `AGENTS.md`, `config/agent.json`, `prompts/`, `skills/`, and `.evo/settings.json`.

## 12. Creation checklist

1. Choose the form (embedded / CLI / cdylib; recommended: embedded + cdylib from one source).
2. Create the directories: `src/tools/`, `prompts/`, `skills/`, `config/`, `.evo/`.
3. Declare `[[bin]]` in `Cargo.toml` and (if a cdylib is needed) `[lib] crate-type`.
4. Write the tool registry `TOOLS` + the single `run_tool`, then write the two adapters.
5. Write `prompts/system.md` and `AGENTS.md`, keeping their constraints consistent.
6. Write `config/agent.json` and `.evo/settings.json`.
7. Wire up the embedded Agent entry point; when the global host is needed, copy the ABI skeleton from `examples/plugin-stub`.
8. Add scripts: build the extension, launch the embedded Agent, launch the global evo.
9. Add schema-alignment tests and at least one end-to-end smoke test.
10. Use `--debug-system-prompt` to confirm that the project prompts and dynamic skill routing make it into the final composed prompt.

## 13. Model execution rules

When the model receives a task to "create an evo Agent project / set up the Agent structure":

1. First call `docs` to query `agent` (this guide); for extension development query `authoring`, for debugging query `debugging`.
2. Read the current repository's existing `Cargo.toml`, SDK version, and neighboring project conventions; do not guess APIs.
3. Lay out the directories and the single tool registration point first, then write the adapters, and wire up the entry points last.
4. Prefer copying the minimal skeletons in the repository (`examples/minimal`, `examples/plugin-stub`).
5. Use the faux provider for offline tests, and `evo dev --no-watch` for a real loading smoke test.
6. Do not claim that unverified ABI/capabilities are fully compatible; document degraded behavior truthfully.
