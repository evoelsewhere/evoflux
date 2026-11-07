# Code intelligence (language servers) — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | crate `evo-lsp`, engine, desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Agent tools](../agent-tools/spec.md), [Office documents](../office/spec.md) (same install-on-demand pattern) |

## 1. Summary

The agent asks the project's language servers instead of searching text:
errors after an edit, the real definition, every real use, types and docs,
outlines. evo knows a catalog of language servers, finds the ones already on
the computer, installs the others when the person asks, and runs one per
project. The person manages them on one page and is told when a project uses
a language that has no server yet.

## 2. Scope

### 2.1 Goals

- An agent tool, `lsp`, that answers code questions from the language server
  of the file's language: diagnostics, definition, type definition,
  implementation, references, hover, document outline, workspace symbols.
- A catalog of common language servers, each with how to find and install it.
- Use a server already on the computer before installing one.
- Install, uninstall and switch servers off from the app.
- Suggest the servers the chat's project needs.

### 2.2 Non-goals

- Installing anything without the person pressing Install.
- Language servers bundled inside plugins (listed as unsupported by
  [Customize](../customize-skills-plugins-connectors/spec.md)).

## 3. User scenarios

### US-1 The agent checks its edit for errors (priority P1)

The agent wants the compiler's errors for a file it just changed so that it
fixes them before answering.

Acceptance scenarios:

1. **Given** a project whose language server is available, **when** the
   agent asks for diagnostics of a file after an edit, **then** it gets the
   compiler's errors, errors first, with their hints, from the file's
   current text.
2. **Given** the server is still indexing, **when** the agent asks,
   **then** the request waits for indexing instead of returning nothing.

### US-2 The agent finds real definitions and uses (priority P1)

The agent wants the definition, references, type and docs of a symbol so
that it reasons about the real code instead of text matches.

Acceptance scenarios:

1. **Given** a symbol on a line, **when** the agent asks for references by
   line and symbol name, **then** it gets the definition and every call with
   each line's text.
2. **Given** a symbol, **when** the agent asks for hover, **then** it gets
   the signature and the doc comment.

### US-3 The person sets up servers for a project (priority P2)

A person wants the servers their project needs, with no manual setup, so
that the agent can use code intelligence there.

Acceptance scenarios:

1. **Given** a chat in a project, **when** the person opens the code
   intelligence page, **then** the servers for that project are listed first
   with an "Install all" action, then the rest.
2. **Given** a project that uses three or more files of a language with no
   server, **when** a chat runs there, **then** evo notifies once for that
   folder with a link to the page.

### Edge cases

- A server needs a program that is missing: the page names the missing
  programs.
- An install fails: the page shows its log or error.
- A server is switched off: the tool does not use it.
- A file's URI is spelled differently by the server: its diagnostics still
  belong to the file.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The agent has an `lsp` tool with `operation`, `path`, `line`, `symbol`, `character` and `query`; operations: diagnostics, definition, type definition, implementation, references (with each line's text), hover, document outline, workspace symbols. | Given a project with a running server, when the agent calls each operation, then it gets the server's answer. |
| FR-2 | A position is given by `line` plus `symbol` (whole word) or `character`. | Given a line and a symbol name, when the tool runs, then it resolves the symbol on word boundaries. |
| FR-3 | Diagnostics are sorted errors first and wait for the slower check after a quick first report; any request waits while the server is indexing. | Given a fresh server, when diagnostics are asked, then the compiler's errors come back, not an empty list. |
| FR-4 | Before each request the file is opened (and saved, for servers that check on save) or updated with its current text. | Given an edited file, when diagnostics are asked, then they reflect the edit. |
| FR-5 | evo ships a catalog of 21 language servers: rust-analyzer (Rust), TypeScript Language Server (TS/JS), Pyright (Python), gopls (Go), clangd (C/C++), csharp-ls (C#), Kotlin Language Server, jdtls (Java, on PATH), Intelephense (PHP), Ruby LSP, HTML / CSS / JSON, YAML, Bash, Dockerfile, Svelte, Lua, Marksman (Markdown), SourceKit-LSP (Swift, with the toolchain), Dart; each with file extensions, root markers, command, how to install and programs it needs. | The server list names every server. |
| FR-6 | A server is found in this order: evo's own install, then (rust-analyzer) the folder's toolchain, then PATH, then a copy shipped with a code editor's extensions. | Given a server in an editor's extension folder, when evo looks for it, then it is found. |
| FR-7 | The person can install a server from the app; the install runs in the background with progress in the list, and the output's tail is kept for the app. | Given a missing server, when the person presses Install, then it installs and the list shows progress and the log. |
| FR-8 | The person can uninstall a server that evo installed. | Given an evo install, when the person presses Uninstall, then it is removed. |
| FR-9 | The person can switch a server off and on; the choice is saved. | Given a switched-off server, when the agent calls the tool on its language, then that server is not used. |
| FR-10 | One server runs per server and project root; the root is the chat's folder when it is itself a project (one server for a whole multi-package workspace), else the nearest folder with a root marker. | Given a file deep in a project, when the tool runs, then the server starts at the nearest marker folder. |
| FR-11 | evo detects which languages a project uses from file extensions and root markers, four levels deep, skipping dependency and build folders. | Given a mixed project, then each of its languages is detected. |
| FR-12 | The **Customize → Code intelligence** page lists the chat's project servers first ("Suggested for <folder>", Install all), then the rest; each shows where it comes from, what it needs (missing programs named), the install command, its log or error, a switch, and Uninstall for evo's own installs. | Manual check in the running app. |
| FR-13 | Once per folder, a chat whose project uses three or more files of a language without a server notifies with a link to the page. | Manual check in the running app. |
| FR-14 | Transcript rows describe the call in words, e.g. "Checked for errors · main.rs", "Found references · add". | Manual check in the running app. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Installs download and run code from the internet, so they happen only when the person presses Install. | Review: no install path runs without the install command from the app. |
| NFR-2 | Installs open no window and stop after 15 minutes. | Review of the installer; manual install on Windows shows no console window. |
| NFR-3 | Positions sent to servers are converted to UTF-16. | Given a line with non-ASCII text, when a symbol is resolved, then the server gets the right column. |

## 5. Success criteria

- SC-1 On a small project, the agent gets the compiler's error with its
  hints from a cold-started server in seconds (observed: about 7 s).
- SC-2 A real model uses the tool on its own, without being told to, and
  answers correctly from its results.

## 6. Clarifications

### 6.1 Open

n/a — no open questions.

### 6.2 Resolved

- 2026-11-06 — Q: Should evo test installs from npm and GitHub
  automatically? → A: No; installs download and run code, so they happen
  only when the person presses Install (NFR-1).

## 7. History

- 2026-11-06 — Built and checked with a real language server and a real
  model.
- 2026-11-07 — Moved to the spec / plan / tasks format.
