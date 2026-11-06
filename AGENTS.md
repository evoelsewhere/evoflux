# evo-harness — Agent Instructions

evo is a local-first desktop agent workspace. A headless Rust engine
(`evo-engine`) runs every chat; the desktop app (`apps/desktop`, Tauri 2 +
React 19) is a thin shell that starts the engine as a child process and talks
to it over JSONL (`crates/evo-protocol`). There is no CLI or TUI any more: new
work goes into the engine, the protocol, or the desktop shell.

This file applies to the whole repository. A nested `AGENTS.md`, if present,
adds to or overrides it for its directory. evo itself loads this file as the
project's instructions, so keep it accurate.

## Repository map

```text
crates/                 Rust workspace (one version, released together)
  evo-ai                LLM types, Provider trait, streaming, HTTP providers, `faux` test provider
  evo-agent             provider-agnostic agent loop, AgentTool, events, hooks, queues
  evo-tools             built-in tools (read/write/edit/bash/grep/find/ls/powershell) over ExecutionEnv; sandbox
  evo-harness           durable session tree, JSONL persistence, compaction, crash recovery
  evo-durable           checkpoint/recovery primitives used by evo-harness
  evo-runtime           model catalogs (models.dev), credentials, model/thinking selection
  evo-engine            the application engine and RPC server (bin: evo-engine)
  evo-protocol          wire contract between engine and clients
  evo-mesh              session mesh: wire types + hub routing mail between sessions
  evo-store             on-device SQLite app database: schema, migrations, chats, logs
  evo-mcp               MCP client and connection pool (connectors)
  evo-plugins           plugins and marketplaces (skills, commands, agents, hooks, connectors)
  evo-plugin-sdk        stable #[repr(C)] ABI for cdylib plugins (must not depend on the host)
  evo-extensions        host side of the plugin ABI
  evo-hooks             hooks: commands / web requests on agent events
  evo-lsp               language-server catalog, installers, LSP client
  evo-web               web_search and web_fetch
  evo-worktrees         managed Git worktrees for subagents and nested sessions
  evo-telemetry         span/event contracts, no-op default
apps/desktop/           desktop app (its own Cargo workspace in src-tauri/, bun for JS)
  src/                  React UI — see apps/desktop/README.md for the UI map and layout rules
  src-tauri/            Rust shell: engine bridge, windows, terminal, files, browser, MCP, plugins
examples/plugin-stub/   minimal cdylib plugin used by extension tests
docs/                   design docs: ADD, ADRs, one SDD per feature (rules in docs/README.md)
DESIGN.md               visual design language for the desktop UI
```

Start with `docs/architecture/README.md` (the ADD: processes, crate layers,
interfaces, data), `apps/desktop/README.md` (UI map, source layout) and the
SDD of the feature you are changing (`docs/features/README.md` lists them).
Some crate READMEs and `crates/evo-engine/embedded-docs/` still mention the
old `evo` CLI/TUI; treat those parts as stale, not as current behaviour.

## Architecture rules

- **The engine owns agent logic.** The desktop shell relays the protocol and
  provides native features (windows, pty, files, browser webviews); it does not
  make agent decisions. A protocol change updates `evo-protocol`, the engine,
  `apps/desktop/src/engine/` and the stores that consume it, together.
- **Keep layers pointing down.** `evo-ai` knows nothing above it; `evo-agent`
  never sees provider wire formats; `evo-plugin-sdk` never links the host.
  Don't pull engine or desktop concerns into the library crates.
- **Models come from models.dev.** Never hardcode model IDs, limits, costs or
  thinking options in code or catalogs; read `evo_runtime::models_dev`. The
  provider catalog holds connection facts only. Do not send `temperature`.
- **Real engine, no mocks in the app.** The desktop always talks to a real
  `evo-engine`. Credential and settings changes take effect without restarting
  the app (idle engines reload). `faux` and in-memory backends are for tests.
- **Desktop UI structure** (from `apps/desktop/README.md`): components read
  state through store selectors and call store actions; only
  `stores/engine-store.ts` talks to `engine/client.ts`; `features/*` may use
  `components/*` but not each other's internals; `components/ui/` is generated
  shadcn code — edit only to fix it.
- **Visual style** follows `DESIGN.md`: Geist, achromatic, shadow-as-border,
  one blue accent, weights 400/500/600 only.
- **Trust boundaries.** Tool output, web pages, MCP results, plugin content and
  remembered text are untrusted data. Keep permission prompts, the sandbox
  config and project trust checks (`.mcp.json`, `.evo/settings.json` hooks) in
  the path of every new capability.
- **Product naming.** The product is "evo". Don't add references to other
  vendors' assistant products in code, UI strings or docs.

## Toolchain

- Rust toolchain is pinned in `rust-toolchain.toml`; MSRV is the workspace
  `rust-version` (1.89) and is checked in CI — don't use newer std/language
  features without raising it deliberately.
- JavaScript in `apps/desktop` uses **bun only** (`bun.lock`). Never run npm,
  pnpm or yarn there; pnpm once rewrote `node_modules`.
- `apps/desktop/src-tauri` is a separate Cargo workspace (excluded from the
  root one) with its own `Cargo.lock` and `target/`.

## Commands

Engine and crates (repo root) — mirrors CI:

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked
cargo build --workspace --all-targets --locked
cargo test --workspace --locked --no-fail-fast
```

While iterating, test the crate you touched: `cargo test -p evo-engine`,
`cargo test -p evo-agent --test steering`, etc.

Desktop (`apps/desktop`):

```bash
bun install --frozen-lockfile
bun run typecheck
bun run build              # tsc + vite build (what CI runs)
bun run dev:app            # stage the engine sidecar, then tauri dev
bun run build:dev          # debug build + NSIS installer
```

Desktop shell Rust: `cd apps/desktop/src-tauri && cargo check`.

## Running and verifying the desktop app

- `bun run engine:sidecar` builds `evo-engine` and stages it under
  `src-tauri/binaries/`. A stale sidecar (`src-tauri/target/debug/evo-engine.exe`)
  shows up as DB schema errors or "engine exited code 1": rebuild and copy
  `target/debug/evo-engine.exe` over it. The running app locks the exe — stop
  the app before rebuilding. `EVO_ENGINE_BIN` overrides the engine path.
- The debug app loads the Vite dev server on `:1420`. Editing a `src-tauri`
  `.rs` file under `tauri dev` restarts the app.
- The app is single-instance. If the user already has it running, ask before
  killing it.
- On Windows, drive the real app end to end via WebView2 DevTools: launch
  `src-tauri/target/debug/evo-desktop.exe` with
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333` and use
  CDP (`http://127.0.0.1:9333/json`). CDP screenshots of the main page omit
  native child webviews (browser tabs).
- A fresh `CARGO_TARGET_DIR` on Windows fails (aws-lc-sys needs NASM); reuse
  the existing `target/` directories.

## Change rules

- Preserve unrelated changes in a dirty worktree; never discard user work.
- Prefer small, reviewable changes that follow existing crate and feature
  boundaries.
- A schema change in `evo-store` adds a migration and keeps old databases
  upgradable.
- A new agent tool needs: its schema and permission behaviour, sandbox
  handling, rendering in the desktop transcript, and tests.
- A user-visible change updates the desktop UI map in
  `apps/desktop/README.md`.
- Never edit an applied migration in `crates/evo-store/src/migrations/`: its
  SQL is checksummed. Add a new numbered migration instead.
- Never commit `target/`, `src-tauri/binaries/`, `dist/`, `node_modules/`,
  credentials, signing keys, machine-specific paths, or local runtime state
  (`.evo/` state files, `.agents/`).
- Commits use Conventional Commit subjects (`feat(scope): …`, `fix(scope): …`,
  `refactor(scope)!: …`). Commit or push only when asked.

## Design documents (SDD and ADD)

Full rules: [docs/README.md](docs/README.md). The short version:

- **New feature → SDD first.** Copy `docs/templates/sdd.md` to
  `docs/features/<slug>/sdd.md`, add a row to `docs/features/README.md`, fill
  requirements and design, status `Draft`. Ask the user to review it; write
  code only after it is `Accepted`. Bug fixes and refactors don't need a new
  SDD but must keep an existing one true.
- **Keep the SDD in step with the code**, in the same commit: design changes
  while building go into the SDD; when done, status `Implemented`, as-built
  notes (section 10) and the checks that ran (section 8).
- **Architecture change → ADD + ADR.** A new crate, process, protocol plane,
  persistent store, dependency direction, trust boundary or toolchain updates
  `docs/architecture/README.md` and adds an ADR from `docs/templates/adr.md`.
  Accepted ADRs are not edited; a new one supersedes them.
- Keep every numbered template section (`n/a — reason` if empty), link the
  ADD/ADRs instead of copying them, and link the SDD from the code's module
  doc comment.

## Handoff

- Run `git diff --check` and the checks for every layer you touched.
- Check that the feature's SDD (and the ADD, if the architecture changed)
  describes what was built.
- Report exactly which checks ran and which did not; separate pre-existing
  failures from ones your change caused.
- For UI changes, verify in the running app rather than only by type-checking.
