# Code intelligence (language servers) — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

## 1. Context and constraints

- The engine runs each chat in its own process
  ([ADD 4](../../architecture/README.md#4-process-view)), so each engine owns
  the language servers its chat uses.
- Language servers speak LSP over stdio. Positions in LSP are UTF-16 code
  units.
- Servers come from many places: their own installers (npm, `go install`,
  `rustup`, `dotnet tool`, `gem`), GitHub releases, a rustup toolchain, PATH,
  or a copy shipped inside a VS Code-style editor's extensions.
- Installing downloads and runs code from the internet, so it happens only
  when the person presses Install.
- Some servers report readiness late: rust-analyzer reports `serverStatus`,
  others work-done progress; diagnostics may arrive in two passes (a quick
  one, then the slower check).

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The `lsp` tool, the server pool and installs live in the engine; the desktop only shows the page and the notice. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-lsp` is a library with no engine or desktop dependency; the engine wraps it in `lsp_tool.rs`. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | New RPC commands (`list_language_servers`, `install_language_server`, `uninstall_language_server`, `set_language_server_enabled`) ship with their desktop callers. |
| Models come from models.dev; no hardcoded model facts | n/a | No model facts involved. |
| Real engine in the app; settings and credentials reload live | ok | `disabledLanguageServers` is a setting read by the engine; no app restart. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | The tool is read-only toward the project; installs run only on the person's Install press (NFR-1). |
| Desktop UI structure and `DESIGN.md` | ok | The page is a Customize section; it reaches the engine through the engine store. |

## 3. Design

### 3.1 Overview

```text
 agent ──lsp tool──► engine (lsp_tool.rs) ──► evo-lsp pool ── one server per (server, root)
                          │                        │
                          │                        └─ client.rs: LSP over stdio
                          │
 desktop Customize → Code intelligence ──RPC──► list / install / uninstall / enable
 engine-store (once per folder) ──list_language_servers──► notice with link to the page
```

`evo-lsp` holds the catalog, the installers, project detection, the stdio
client, the pool and the operations. The engine exposes them as the `lsp`
tool and four RPC commands. The desktop shows the page and a one-time notice.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-lsp/src/catalog.rs` | 21 servers; each: file extensions → language ids, root markers, command and arguments, how to install, programs it needs. HTML / CSS / JSON come from `vscode-langservers-extracted`. | FR-5 |
| crate | `crates/evo-lsp/src/install.rs` | Where a server is: evo's own install in `<agent dir>/lsp/<id>`, then (rust-analyzer) the folder's rustup toolchain, then PATH, then a copy shipped with a VS Code-style editor (`.vscode`, `.vscode-insiders`, `.cursor`, `.windsurf` extensions). Installers; no window, 15-minute limit, the output's tail kept for the app. | FR-6, FR-7, FR-8, NFR-1, NFR-2 |
| crate | `crates/evo-lsp/src/detect.rs` | Which languages a project uses: files by extension and root markers, four levels deep, skipping dependency and build folders. | FR-11 |
| crate | `crates/evo-lsp/src/client.rs` | LSP over stdio: one writer task, requests matched by id, the server's requests answered with defaults (`workspace/configuration`, progress tokens, …), published diagnostics keyed by file whatever the URI spelling, work-done progress and rust-analyzer's `serverStatus` so a request waits for indexing; just after start it gives the server a few seconds to begin. Opens (and saves, for servers that check on save) or updates files with their current text before each request. | FR-3, FR-4 |
| crate | `crates/evo-lsp/src/pool.rs` | One server per (server, project root); the root is the chat's folder when it is itself a project (one rust-analyzer for a whole Cargo workspace), else the nearest folder with a root marker. | FR-10 |
| crate | `crates/evo-lsp/src/ops.rs` | Diagnostics (sorted, errors first, waits for the slower check after a quick first report), definition / type definition / implementation / references (with each line's text), hover, document outline, workspace symbols; positions by `line` + `symbol` (whole word) or `character`, converted to UTF-16. | FR-1, FR-2, FR-3, NFR-3 |
| crate | `crates/evo-lsp/examples/lsp-try.rs` | Try any of it from a terminal. | — (developer aid) |
| engine | `crates/evo-engine/src/lsp_tool.rs` | The `lsp` tool and the RPC commands; settings `disabledLanguageServers`. | FR-1, FR-7, FR-8, FR-9 |
| desktop UI | `apps/desktop/src/features/customize/languages-section.tsx` | **Customize → Code intelligence**: suggested servers for the chat's folder with Install all, then the rest; source, needs, install command, log or error, switch, Uninstall. | FR-12 |
| desktop UI | `apps/desktop/src/stores/engine-store.ts` (`suggestCodeIntelligence`) | Once per folder, the notice that links to the page. | FR-13 |
| desktop UI | `apps/desktop/src/components/ai-elements/tool.tsx` | Transcript row labels ("Checked for errors · main.rs", "Found references · add", …). | FR-14 |

### 3.3 Interfaces

Agent tool `lsp` (the model sees it):

```text
lsp {
  operation,   // diagnostics | definition | type definition | implementation |
               // references | hover | document outline | workspace symbols
  path,        // the file
  line?,       // the line
  symbol?,     // whole word on that line
  character?,  // column, instead of symbol
  query?       // for workspace symbols
}
```

RPC commands (engine):

| Command | Params | Effect |
| --- | --- | --- |
| `list_language_servers` | — | the chat's folder, detected languages (server and file count), every server with its state (installed, installing, missing programs, install kind, log) |
| `install_language_server` | `{server}` | installs in the background; progress shows in the list |
| `uninstall_language_server` | `{server}` | removes evo's own install |
| `set_language_server_enabled` | `{server, enabled}` | writes `disabledLanguageServers` |

Older desktops that do not call these commands still get the `lsp` tool.

### 3.4 Data and storage

- evo's installs: `<agent dir>/lsp/<id>`.
- Setting `disabledLanguageServers` in the agent settings.
- The pool's running servers live as long as the chat's engine.
- The desktop remembers that a folder was already suggested in browser
  storage (`evo.lsp-suggested:<folder>`).

### 3.5 Behaviour

1. The agent calls `lsp` on a path. The engine picks the server for the
   file's extension, finds the project root (FR-10) and gets or starts that
   server from the pool.
2. Just after start the client gives the server a few seconds to begin, then
   waits on work-done progress or `serverStatus` until indexing ends.
3. The file is opened (or saved) or updated with its current text, and the
   request is sent; positions are converted to UTF-16.
4. For diagnostics, the client waits for the slower check after a quick
   first report, then returns them sorted, errors first.

Install: the RPC starts the installer in the background — `npm install
--prefix`, `go install …@latest` with `GOBIN`, `rustup component add`,
`dotnet tool install --tool-path`, `gem install --install-dir`, or the latest
GitHub release (zip, tar.gz or a bare binary, picked by platform). No
window, 15-minute limit; the output's tail is kept for the page.

### 3.6 Errors and edge cases

- Server missing a required program: the list names the missing programs;
  the notice is not raised for such servers.
- Install failure or timeout: the page shows the log or error.
- Diagnostics published under a different URI spelling are matched to the
  file.
- Server requests the client does not handle get default answers so the
  server does not stall.

### 3.7 Security and trust

- Installs download and run code from the internet; they run only from the
  person's Install press (NFR-1), never on the agent's request.
- Servers run with the person's permissions on the project's files; the tool
  only reads answers from them.
- Server output reaches the model as tool results and is untrusted data.

### 3.8 Configuration

| Key | Type | Default | Where | Applies |
| --- | --- | --- | --- | --- |
| `disabledLanguageServers` | list of server ids | empty | agent `settings.json` | through `set_language_server_enabled`; edited by the switch on the page |

## 4. Alternatives considered

n/a — the old design notes record no alternatives.

## 5. As-built notes

- Built 2026-11-06 as designed.
- Installing from npm and GitHub was not run as part of the checks: installs
  download and run code from the internet, so they happen when the person
  presses Install.
