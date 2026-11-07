# Code intelligence (language servers)

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-lsp`, engine, desktop UI |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | none |

Status: built (2026-11-06).

The agent's `lsp` tool asks the project's language servers instead of
searching text: errors after an edit, the real definition, every real use,
types and docs, outlines.

## Pieces

- `crates/evo-lsp`
  - `catalog.rs` — 21 servers: rust-analyzer (Rust), TypeScript Language
    Server (TS/JS), Pyright (Python), gopls (Go), clangd (C/C++), csharp-ls
    (C#), Kotlin Language Server, jdtls (Java, on PATH), Intelephense (PHP),
    Ruby LSP, HTML / CSS / JSON (vscode-langservers-extracted), YAML, Bash,
    Dockerfile, Svelte, Lua, Marksman (Markdown), SourceKit-LSP (Swift, with
    the toolchain), Dart. Each: file extensions → language ids, root markers,
    command and arguments, how to install, programs it needs.
  - `install.rs` — where a server is: evo's own install in
    `<agent dir>/lsp/<id>`, then (rust-analyzer) the folder's rustup
    toolchain, then PATH, then a copy shipped with a VS Code-style editor
    (`.vscode`, `.vscode-insiders`, `.cursor`, `.windsurf` extensions).
    Installers: `npm install --prefix`, `go install …@latest` with `GOBIN`,
    `rustup component add`, `dotnet tool install --tool-path`, `gem install
    --install-dir`, or the latest GitHub release (zip, tar.gz or a bare
    binary, picked by platform). No window, 15-minute limit, the output's tail
    kept for the app.
  - `detect.rs` — which languages a project uses: files by extension and root
    markers, four levels deep, skipping dependency and build folders.
  - `client.rs` — LSP over stdio: one writer task, requests matched by id, the
    server's requests answered with defaults (`workspace/configuration`,
    progress tokens, …), published diagnostics (keyed by file, whatever the
    URI spelling), work-done progress and rust-analyzer's `serverStatus`, so
    a request waits for indexing; just after start it gives the server a few
    seconds to begin. Files are opened (and saved, for servers that check on
    save) or updated with their current text before each request.
  - `pool.rs` — one server per (server, project root); the root is the
    chat's folder when it is itself a project (one rust-analyzer for a whole
    Cargo workspace), else the nearest folder with a root marker.
  - `ops.rs` — diagnostics (sorted, errors first, waits for the slower check
    after a quick first report), definition / type definition /
    implementation / references (with each line's text), hover, document
    outline, workspace symbols; positions by `line` + `symbol` (whole word)
    or `character`, converted to UTF-16.
  - `examples/lsp-try.rs` — try any of it from a terminal.
- Engine `crates/evo-engine/src/lsp_tool.rs` — the `lsp` tool (`operation`,
  `path`, `line`, `symbol`, `character`, `query`) and RPC
  `list_language_servers`, `install_language_server {server}` (background,
  progress in the list), `uninstall_language_server {server}`,
  `set_language_server_enabled {server, enabled}` (settings
  `disabledLanguageServers`).
- Desktop — Customize → Code intelligence (`languages-section.tsx`): servers
  for the chat's project first ("Suggested for <folder>", Install all), then
  the rest; each with where it comes from, what it needs (missing programs
  named), the install command, its log or error, a switch, and Uninstall for
  evo's own installs. Once per folder, a chat whose project uses three or
  more files of a language without a server notifies with a link to the
  page. Transcript rows read "Checked for errors · main.rs", "Found
  references · add", ….

## Checked

- With the real rust-analyzer on a scratch Cargo project: diagnostics
  returned the compiler's E0308 with its hints (about 7 s from a cold start),
  references found the definition and three calls with their lines, hover
  returned the signature and doc comment, definition jumped to `math.rs`.
- A real model used the tool on its own (diagnostics and references in
  parallel) and answered correctly.
- Installing from npm and GitHub was not run here: installs download and run
  code from the internet, so they happen when you press Install.
