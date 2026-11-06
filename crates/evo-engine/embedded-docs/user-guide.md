# evo User Guide

This is the evo manual for users and extension authors. It covers installation, configuration, sessions, plugins, remote mode, and troubleshooting.
The current repository and the installed evo binary are authoritative for implementation details.

## 1. Installation

### Install the CLI directly

Requires Rust/Cargo:

```bash
cargo install evo-cli
evo --version
evo --help
```

Install the development version from this repository's source:

```bash
git clone https://github.com/evoelsewhere/evo-harness.git
cd evo-harness
cargo install --path crates/evo-cli --force
```

`cargo install` installs the executable; it is not the same as `evo install`. The latter installs Rust dynamic-library extensions built with `evo-plugin-sdk`.

### Run and build from source

This project is a Rust Cargo workspace, not a Node/npm project; there is no `package.json` in the root directory. From the repository root, run:

```bash
# Start the CLI directly
cargo run -p evo-cli

# Pass arguments to the CLI (everything after `--` belongs to evo)
cargo run -p evo-cli -- -p "Summarize README.md"
cargo run -p evo-cli -- --mode json -p "List the crates in the project"

# Build the release version
cargo build -p evo-cli --release
```

After the build, the Windows executable is at `target/release/evo.exe`; on Linux/macOS it is usually `target/release/evo`. You can also install the local CLI into Cargo's bin directory and use it directly:

```bash
cargo install --path crates/evo-cli --force
evo
```

For an offline example (no API key or network required), use:

```bash
cargo run -p minimal
```

### First run

Interactive mode:

```bash
evo
evo "Explain the directory structure of the current project"
```

Single-shot (print) mode:

```bash
evo -p "Summarize README.md"
evo --mode json -p "List the project's risks"
```

Use `@` to include a file in the first message:

```bash
evo @README.md "Suggest improvements for this project"
```

## 2. Models and credentials

### Credential precedence

When multiple sources are present, the precedence is:

1. `--api-key`
2. `~/.evo/auth.json` (written by `evo auth login`)
3. The `apiKey` of the corresponding provider in `~/.evo/agent/models.json`
4. Environment variables

Anthropic uses `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; OpenAI-compatible providers use `OPENAI_API_KEY`. Checking credentials does not make any network requests:

```bash
evo auth check
evo auth check --provider gateway --json
evo auth login
evo auth logout
```

Do not write keys into a Git repository, project documentation, or a package manifest.

### Custom providers

The configuration file defaults to `~/.evo/agent/models.json`; you can also set the agent configuration directory with `EVO_CODING_AGENT_DIR`:

```jsonc
{
  "providers": {
    "gateway": {
      "api": "anthropic-messages",
      "baseUrl": "https://gateway.example.com",
      "apiKey": "sk-gateway-secret",
      "models": [
        { "id": "custom-claude", "name": "Custom Claude" }
      ]
    },
    "openai-gateway": {
      "api": "openai-completions",
      "baseUrl": "https://api.example.com/v1",
      "apiKey": "sk-openai-secret",
      "models": [
        { "id": "custom-model", "name": "Custom Model" }
      ]
    }
  }
}
```

Select a model:

```bash
evo --model gateway/custom-claude -p "hello"
evo --model openai-gateway/custom-model -p "hello"
evo --provider gateway --model custom-claude -p "hello"
```

When `--model` is not given, evo prefers models that are already authenticated. If standard Anthropic credentials are present, the built-in default model is used; if only a custom gateway is authenticated, the first available model of that gateway is selected.

Anthropic-compatible gateways can also use:

```text
ANTHROPIC_BASE_URL=https://gateway.example.com
ANTHROPIC_AUTH_TOKEN=token
```

## 3. CLI commands

Common global options:

```text
--provider <name>       Provider name
--model <pattern>       Model ID; supports provider/model and a thinking suffix
--api-key <key>         Override credentials for this run
--base-url <url>        Override the model endpoint
--timeout <seconds>     LLM API request timeout (default 600)
--stream-idle-timeout <seconds> Idle timeout for streaming responses (default 300; 0 disables; independent of the total timeout)
--thinking <level>      off/minimal/low/medium/high/xhigh/max
--print, -p             Run once and exit
--mode text|json|rpc    Output mode
--continue, -c          Continue the most recent session
--resume, -r            Pick a past session
--session <id|path>     Use a specific session
--session-dir <dir>     Use a specific session directory
--name, -n <name>       Set the session display name
--tools <list>          Allow only the listed tools
--exclude-tools <list>  Disable the listed tools
--no-tools              Disable all tools
--no-builtin-tools      Disable built-in tools (read/bash/edit/write/docs)
--no-skills             Skip skill discovery
--no-prompt-templates   Skip prompt-template discovery
--no-context-files      Skip AGENTS.md/CLAUDE.md discovery
--no-extensions         Disable extension loading
--extensions-dir <dir>  Additional directory to scan for Rust extensions
--package-only         Load only the current project's packages/resources, excluding global resources
--project-only         Equivalent alias for `--package-only`
--list-models [search]  List available models (optional fuzzy search)
--offline               Disable network checks at startup
--export <file>         Export a JSONL session to HTML
--tui-mode <mode>       TUI buffer: regular or fullscreen
--system-prompt <text>  Replace the default system prompt
--append-system-prompt <text>  Append to the system prompt (repeatable)
--debug-system-prompt   Print each section of the resolved system prompt to stderr
--verbose               Show startup warnings (such as ignored flags)
--server [--port <n>] [--bind <ip>]
                        Headless server (prints a token at startup)
--connect <host:port>   Remote client TUI (zero local resources)
--token <token>         Remote authentication token (the EVO_SERVER_TOKEN environment variable also works)
```

Subcommands:

```text
evo auth login|check|logout
evo events path|tail    Inspect the extension event log (requires EVO_EVENT_LOG=1)
evo install <crate>
evo uninstall <crate>
evo extension update [name] # Update all eligible extensions, or one by name
evo update                 # Update the evo CLI itself
evo dev [options]          # Develop a Rust extension: build, watch, hot reload
evo dev-local [options]    # Debug only the current Rust extension (isolated mode)
```

### CLI self-update

By default, `evo update` downloads a prebuilt CLI from GitHub Releases and does not need a local Rust/Cargo toolchain.
Stable versions are resolved from the crates.io release records; `evo-release.json` provides the per-platform download URLs, sizes, and
SHA-256 hashes of the archive/executable. After verifying the target platform, integrity, and actual version, it atomically replaces the current CLI.
On Windows the update is staged and the replacement completes after the current process exits. Stable builds never prompt for or automatically select preview builds.

Preview builds come from merges into the `preview` branch; they create a GitHub prerelease but are not published to crates.io.
To try a preview build, explicitly run `evo update preview`; it selects only the latest version among GitHub prereleases.
When a preview build runs a plain `evo update`, it checks crates.io and, if it finds a stable release, prompts you to switch to it.

`evo update --force` reinstalls the resolved version; `evo update --build` explicitly compiles from source with Cargo.
A missing manifest, a failed download, or a failed verification all report an error and keep the existing version; it never falls back to compiling automatically.
`--offline` only reports the cached stable version; preview builds require network access to query GitHub. If an older Release has no manifest,
you can wait for the protocol assets to be backfilled, or explicitly use `evo update --build`.

### Scrolling message history in the TUI

The interactive TUI uses the alternate screen by default, and the application manages transcript scrolling itself. Use `PageUp` / `PageDown`, `Home` / `End`, or the mouse wheel and trackpad to browse message history.

On macOS the behavior differs from the terminal's native scrollback in main-screen mode: an alternate-screen TUI must receive mouse-tracking events for the wheel and trackpad to scroll message history. After entering raw mode, the TUI explicitly re-enables mouse tracking in alternate-screen mode; in main-screen mode, mouse tracking stays off to preserve the terminal's native scrolling and text selection.

If the wheel cannot scroll message history on macOS, check whether `TuiAltScreen::start_readerless` includes the alternate-screen mouse-tracking initialization; do not change macOS global defaults directly.

### macOS keyboard and plugin panels

Terminals that support the Kitty keyboard protocol use flags 7, the same as Evo, which enables modifier-key disambiguation plus key-repeat and key-release events for functional keys. Plain text is kept as UTF-8 input so that Chinese input methods (IMEs) in terminals such as iTerm2 can commit text normally; flag 8, which turns all text into key events, is not enabled. Release events for ordinary character keys (such as Space) are not guaranteed; plugins that rely on press-and-hold should use functional keys for which the terminal supports release events. The protocol is enabled after switching to the active screen and restored before exiting or suspending; on resume, full-screen mouse scrolling is re-enabled as well.

The protocol is also enabled by default on macOS, because `Shift+Enter` depends on it to be distinguished from `Enter`; only terminals whose IME cannot commit text with the protocol enabled (such as Otty) fall back to legacy input. `EVO_KITTY_KEYBOARD=1` forces the protocol on, and `EVO_KITTY_KEYBOARD=0` forces a fallback to legacy input.

In a local Terminal.app, `Shift+Enter` uses the native macOS Shift state to supplement newline detection, while a plain `Enter` still sends. SSH sessions do not read the local machine's Shift state. Terminals that do not support the enhanced keyboard protocol still use legacy input; features that depend on key-release events, such as holding down a shortcut, require terminal support.

When a plugin input box, editor, selector, or history search is open, it receives input first; plugin global shortcuts do not steal key presses from these windows. Keys already taken over by a plugin still receive their matching release events, so the held state does not get stuck. Overlays are laid out by their actual width and avoid the input box and footer; multiple passive panels automatically stack vertically to avoid each other when there is enough space, and when the window is too small, panels that do not fit are temporarily hidden. To keep overlays from covering the chat body, close the panel or use the plugin's sidebar layout.

### Remote mode (`--server` / `--connect`)

Run the agent on a headless server and drive it remotely from another process with the TUI. The client has **no local agent resources at all**.

```bash
evo --server --port 9899          # Server: prints a token at startup
evo --connect 127.0.0.1:9899 --token <token>   # Client

# Or pass the token via an environment variable
export EVO_SERVER_TOKEN=<token>
evo --connect 127.0.0.1:9899
```

The server enables token authentication by default (`--no-token` disables it). The client supports commands such as `/state`, `/model`,
`/thinking`, `/tools`, and `/abort`; `/tree`, `/fork`, `/switch`, `/export`,
`/name`, and `/reload` depend on the local harness and are unavailable in remote mode. For the full protocol, available commands, and
limitations, see [`remote-mode.md`](remote-mode.md).

## 4. Built-in tools

The default tools are Evo's `read`, `bash`, `edit`, and `write`, plus evo's own read-only `docs` documentation lookup tool. On Windows, `powershell` is also registered by default. `docs` can look up the user guide, extension development, Agent project structure, Rust debugging, and architecture notes; `grep`, `find`, and `ls` remain available as library implementations but are not registered by the CLI by default.

The `defaultTools` field (or its short form `default_tools`) in `.evo/settings.json` restricts the startup tool set when
`--tools` is not specified:

```json
{
  "defaultTools": ["read", "bash", "edit", "write", "docs"]
}
```

To restrict the tool scope, explicitly list Evo's four tools:

```bash
evo --tools read,bash,edit,write,docs -p "Inspect and modify the project files"
```

## 5. Project directories and resource precedence

evo prefers its own directories while remaining compatible with the original Evo `.evo` layout:

```text
project/
├── .evo/
│   ├── settings.json
│   ├── SYSTEM.md
│   ├── APPEND_SYSTEM.md
│   ├── skills/
│   ├── prompts/
│   ├── themes/
│   ├── extensions/
│   └── packages/
└── themes/
```

The project's `.evo` holds only what you put there for the project (settings, instructions, resources, and
project-scope packages you install). evo's own working data is never written into the project: sessions go to
`~/.evo/agent/sessions/--<project path>--/` (or `EVO_CODING_AGENT_SESSION_DIR`), and the app database, credentials,
logs, lock files and managed worktrees stay in `~/.evo/agent/` (`EVO_CODING_AGENT_DIR` moves all of it).

The project's `.evo` takes precedence over the project's `.evo`. Global resources live in `~/.evo/agent/` by default, including `settings.json`, `models.json`, `skills/`, `prompts/`, `themes/`, `extensions/`, and `packages/`. When resources with the same name conflict, project resources take precedence over global resources, and `.evo` takes precedence over `.evo`.

The project-level `.evo/settings.json` can add resource directories:

```json
{
  "skillDirs": ["./team-skills"],
  "promptDirs": ["./prompts/shared"],
  "extensionDirs": ["./target/debug"],
  "packages": ["./packages/review-tools"]
}
```

Paths are relative to the project root; `skills`, `prompts`, and `extensions` are short forms of the corresponding `*Dirs` fields. Custom directories are loaded together with `.evo`, `.evo`, and the conventional global directories, with `.evo` taking precedence. The global `~/.evo/agent/settings.json` also supports these fields; there, relative paths are relative to the agent directory.

To load only the current project's packages/resources and exclude global resources, use either of these equivalent flags:

```bash
evo --package-only
evo --project-only
```

Both load the current project's skills, prompts, themes, extensions, and packages, and read the project's `.evo/settings.json`; they do not load global resources automatically. `--local-only` has different semantics: it loads only the extensions explicitly specified with `--extensions-dir` or `--extension`.

The configuration directory can be relocated:

```bash
EVO_CODING_AGENT_DIR=/work/evo-agent evo
```

Sessions are saved under sessions in the agent configuration directory by default; `--no-session` uses a temporary session.

## 6. Rust plugins and packages

Native Rust plugins are `cdylib` crates that depend only on `evo-plugin-sdk` and are loaded dynamically by `evo-extensions`.
For the complete "write a plugin from scratch" workflow, see [`docs/extensions/authoring.md`](../extensions/authoring.md),
which covers the Cargo layout, `export_plugin!`, tool lifecycle, capability detection, testing, and `evo dev`.
If a plugin project also needs the session, workspace, RPC, or durable state shared by the Web/ACP adapters,
it can additionally reuse [`evo-extcore`](https://crates.io/crates/evo-extcore) (`evo-extcore = "0.1"`).
It is an ordinary Rust library, not a `cdylib` entry point, and it does not replace `evo-plugin-sdk`; if you are only building an ordinary CLI tool,
do not pull it in for ABI registration.

```bash
cargo build -p plugin-stub
evo --extensions-dir target/debug -p 'echo "hi"'
```

Install a prebuilt extension (the default; no Rust/Cargo required):

```bash
evo install evo-todo
evo install evo-todo --version 0.2.0
evo install evo-todo --force # Reinstall the same version
```

`evo install <package-name>` installs or upgrades directly; if the target version is already installed, it reports this and skips. Reinstalling the same version or downgrading requires `--force`. Source builds follow the same rule: during local development, if you change the code without changing the version, reinstall with `--force`.

The installer picks the latest non-yanked stable version from crates.io, uses the package's `repository` metadata to find the GitHub repository, and then reads `evo-extension.json` from the `<package-name>-v<version>` Release. It matches the prebuilt file by exact target triple, and verifies the archive size and SHA-256, the SHA-256 of the extracted library file, the platform architecture, and the declared SDK ABI. The library file name is taken from the manifest's `library.path`. Extensions in the same repository can be versioned and released independently.

Specify a custom GitHub repository (a full HTTPS repository URL is also accepted):

```bash
evo install my-extension --github owner/repo --version 1.2.3
evo install my-extension --github https://github.com/owner/repo
```

Custom repositories must also publish using the same distribution protocol. An explicit repository does not depend on crates.io; when the version is omitted, the latest stable version is selected only from that repository's `<package-name>-v<version>` tags. The repository's global latest Release is never used. Later `--force` reinstalls and startup update checks keep the source and verify that the new version's manifest supports the current platform.

Publishers must upload the archives for the declared platforms first and upload the manifest last. If the manifest is not yet published, the target platform is missing, or verification fails, the installation fails; it does not compile automatically or select another version. To compile from source, explicitly use:

```bash
evo install evo-todo --build
evo install evo-todo --build --version 0.2.0 --force
```

The prebuilt installation record includes the version, repository, target platform, source commit, SDK ABI, and checksums; installation and uninstallation use the same transaction mechanism. At load time, the actual plugin entry point and API struct sizes are still verified. Native system runtime library dependencies must still be provided by the operating system.

Packages can ship files needed at runtime alongside the library file, such as the Node worker process `runtime/main.mjs`. The `runtime-assets.json` index at the archive root is generated by the package's release build tooling and lists each file's path, size, and SHA-256. The installer first verifies all content in memory, then writes it to the extension directory transactionally together with the library file, and records it in the installation registry. Upgrades replace these files; uninstalling also removes directories that become empty as a result. Paths must be relative, plain ASCII paths and must not contain `..`, hidden components, `node_modules`, native library suffixes, Windows device names (such as `CON`, `NUL`, `COM1`), components ending in a dot, symbolic links, or files not declared in the index; a single file must not exceed 128 MiB, the total expanded size must not exceed 256 MiB, and the total number of archive entries must not exceed 128. Archives without an index install only the library file. Older evo versions do not support this feature: when they read such an archive they install only the library file instead of rejecting it, so upgrade evo before publishing packages that declare auxiliary files.

Local development:

```bash
evo install my-extension --path ../my-evo-extension --force
```

Use `evo extension update` (recommended) to update all project-linked extensions and global registry/prebuilt extensions,
or `evo extension update <name>` to update one by name. Updates keep the original Cargo build backend or
the explicitly specified GitHub source; development extensions installed globally via `--path` are not updated.
The old command `evo package update [name]` is still supported, but `evo extension update [name]` is recommended
for updating extensions. Project link management still uses `evo package link`,
`evo package list`, and `evo package unlink`; these command names are unchanged.

Use watch mode when developing an extension project:

```bash
cd ../my-evo-extension
evo dev
# Multi-extension workspace: evo dev --package my-extension
# Debug only the current extension: evo dev-local (isolated mode, global extensions not loaded)
```

`evo dev` automatically detects the Cargo `cdylib`, builds it the first time, and loads the versioned artifact from `.evo/extensions/.dev`. Source changes trigger a rebuild and hot reload; running `/reload` manually also rebuilds first. If a build fails, the currently loaded version is kept. For the complete template and boundary rules, see the online extension authoring guide: <https://evo.laofu.online/extension-authoring.md>; for debugging tips, see the `debugging` topic of `docs`.

Installed dynamic libraries live in `~/.evo/agent/extensions` (or the directory specified by `EVO_CODING_AGENT_DIR`) and are loaded the next time evo starts. Plugins register tools, providers, event handlers, and resource handlers through a stable ABI; do not depend directly on private modules of `evo-cli`.

### Web search and fetch

Network tools are provided by the separate [evo-package extensions](https://github.com/evoelsewhere/evo-package)
and are not among the CLI's default built-in tools. Install them as needed, then restart evo:

```bash
evo install evo-websearch
evo install evo-webfetch
```

- `websearch` returns the title, link, and snippet of each search result.
- `webfetch` extracts readable text from public HTTP(S) web pages; it rejects private addresses and oversized responses.
- These two extensions are not interactive browsers; they do not support clicking, login flows, or executing page JavaScript.

### Sub-agents that inherit the main session's configuration

After installing a compatible version of `evo-subagents` and restarting, you can delegate tasks with `delegate_task`:

```bash
evo install evo-subagents
```

A sub-agent uses a snapshot of the main session's currently effective configuration: the model/provider and its private credential binding, thinking,
system prompt, resources, request options, enabled tools, project cwd, and approval hooks. It is not an `evo` child process started by re-reading the default
configuration; credentials are not passed through plugin JSON.

A subtask uses its own in-memory Session and **does not copy or modify the parent chat history**. The host API can narrow the
tool set further but cannot widen it; `delegate_task` is removed from the child tool set, and recursive delegation through aliases is forbidden.
Approvals and `ask_user` use the parent UI; when there is no interactive consumer, they return an explicit denial/error and are never allowed by default.
The subtask is cancelled when the parent run ends or is cancelled, when the session is switched, or when the owning plugin is unloaded/reloaded.
This is not an OS security sandbox; allowed tools such as the shell keep their normal capabilities.

Both the host and the extension must support the corresponding protocol; an older host explicitly requires an upgrade, with no fallback to a child process using the default configuration.
The SDK provides `AgentHarness::create_child`, and extensions integrate through the `GetExecutionContext` and `ChildAgent`
runtime actions. For the full protocol, see `docs/extensions/subagents.md` in the repository:
<https://github.com/evoelsewhere/evo-harness/blob/main/docs/extensions/subagents.md>.

## 7. SDK integration

If you only need to embed an Agent, depend on `evo-agent` and `evo-ai`; add `evo-tools` if you need the built-in tools; add `evo-harness` if you need sessions, compaction, skills, and context files.

```rust
use evo_agent::{Agent, AgentEvent};
use evo_ai::providers::faux::faux_provider;

let model = faux_provider().model("echo");
let mut agent = Agent::builder(model)
    .system_prompt("You are a helpful assistant.")
    .build();

let mut events = agent.subscribe();
agent.prompt("Hello from evo").await?;
while let Some(event) = events.recv().await {
    if matches!(event, AgentEvent::AgentEnd { .. }) {
        break;
    }
}
```

Custom tools implement `evo-agent::AgentTool`; providers implement `evo-ai::Provider`. With `faux provider` and `InMemoryExecutionEnv`, you can test the Agent loop without a network, an API key, or a real file system.

## 8. Troubleshooting

### Model not found or API errors

Run `evo auth check` and confirm the provider, `models.json`, environment variables, and `baseUrl`. Use `--provider` and the full `provider/model` to avoid ambiguity between models with the same name. API errors keep the diagnostic text returned by the provider; check the endpoint, authentication headers, and model ID first.

### Extension fails to load

Confirm that the Rust plugin is a `cdylib` and matches the current platform; temporarily point `--extensions-dir` at the build output directory. When loading fails, keep the full error message output by the host, and check whether the extension declares capabilities that the host does not provide.

### Extension event handler not triggered, or startup aborted

```bash
export EVO_EVENT_LOG=1
evo            # Record all extension event handler invocations
evo events tail   # Follow the log; check whether result is Continue or Error/Abort/Panic/Timeout
```

The log is at `~/.evo/logs/events.jsonl` by default (override with `EVO_EVENT_LOG_PATH`). If an
extension returns a veto (`EVENT_HANDLER_ABORT`) during the `BeforeTuiStart` phase, the CLI aborts startup with exit code `3`
and prints the reason.

### Resources do not appear on the welcome screen

Confirm that the files are in `.evo` (or the compatible `.evo`) or in the global `~/.evo/agent`. Use `evo --debug-system-prompt` to view the final system prompt, skills, and resource counts; for resources with the same name, first check whether `.evo` is overriding `.evo`.

### Cannot connect in remote mode

Confirm that the server was started with `evo --server --port <port>` and that the token is correct (or provided via
`EVO_SERVER_TOKEN`). The client is display-only and does not load any local providers/tools/extensions;
session files live on the server.

## 9. Development, testing, and releases

Run formatting, checks, and tests:

```bash
cargo fmt --all
cargo check --workspace
cargo test --workspace
```

Publish crates in dependency order:

```text
evo-telemetry → evo-ai → evo-agent → evo-tools → evo-harness →
evo-plugin-sdk → evo-extensions → evo-tui → evo-cli
```

Everyday contributions do not need manual version bumps. Merging ordinary changes into `main` and passing CI does not automatically prepare a
Release PR; a maintainer must go to `Actions → CI → Run workflow`, select `main`, and enable
`prepare_release`. Only merging an eligible Release PR publishes a release. Release notes are maintained in a single root-level
`CHANGELOG.md`; `docs/release-vX.Y.Z.md` files are no longer created. For the full process, including how documentation-only changes are handled without a release,
see `docs/maintaining/releasing.md` in the repository:
<https://github.com/evoelsewhere/evo-harness/blob/main/docs/maintaining/releasing.md>.

After modifying the model-readable documentation source `docs/evo-tool/`, run `sh scripts/sync-embedded-docs.sh` and commit
the generated documentation snapshot. Documentation-only updates do not require a version bump or a tag. The website must still be deployed separately; committing or merging
documentation does not mean the live website has been updated.

## 10. Documentation entry points

- Online documentation: <https://evo.laofu.online/docs.html>
- Source repository: <https://github.com/evoelsewhere/evo-harness>
- Rust API: <https://docs.rs/evo-agent>, <https://docs.rs/evo-plugin-sdk>

- Packages and extension authoring guide: <https://evo.laofu.online/extension-authoring.md>
- Remote mode: <docs/remote/user-guide.md>
- Rust extension and agent debugging: the `debugging` topic of the `docs` tool inside `evo`

When the online documentation and the installed version disagree, the Git tag for that version and the documentation in the repository are authoritative.
