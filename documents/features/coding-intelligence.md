# Coding intelligence

Coding mode combines a repository-local structural index with repository-local
language servers. The index answers discovery and graph questions from committed
index evidence; LSP answers live semantic questions for an active repository.

## Repository code context

Each repository has a cache-local SQLite index built from source bytes,
tree-sitter parsing, AST-aware chunks, FTS5 and deterministic local vectors.
Twenty-five parsers cover Python, TypeScript/TSX, JavaScript, Go, Rust, Java,
C#, C/C++, Swift, Kotlin, PHP, Ruby, Scala, Dart, Objective-C, Lua/Luau, R,
Pascal, Svelte, Vue, Astro and Liquid. Additional known text formats remain
search-only.

The native `code_context` tool provides a closed action set:

| Need | Action |
|---|---|
| Concept, identifier or source phrase | `search` |
| Syntax shape with metavariables | `grep` |
| Exact symbol definition | `definition` |
| Incoming/outgoing calls | `callers`, `callees` |
| Direct inbound relationships | `references` |
| Transitive inbound impact | `impact` |
| Bounded bidirectional graph | `neighborhood` |

Refresh uses desired-state reconciliation: changed components are replaced
atomically, deleted components are removed, and parse failures retain the last
good snapshot while surfacing a limitation. Queries never mix indexed symbols
with newer working-tree source windows.

Cross-repository links are resolved at query time over only the active Coding
project's authorized repositories. There is no application-database graph or
persisted cross-repository guess.

Detailed storage and ambiguity rules:
[Coding-agent code context](../architecture/coding-agent-code-context.md).

## Code graph UI

The workbench exposes repository/project graph overviews, spatial graph views,
symbol navigation and cross-repository links. Cold spatial projections run in a
separate process lane and are cached by committed index version and limits; a
rebuild can proceed while readers continue to see the last committed graph.

## Language-server intelligence

One `(repository, language)` pair owns one LSP client. Supported operations
include diagnostics, hover, definition/references, document/workspace symbols,
code actions, rename, formatting and organize imports. Server-requested direct
`workspace/applyEdit` is rejected: mutations must become reviewable ChangeSets.

Language-server installation is opt-in. EvoFlux can install a bounded catalog
of pinned npm/uv packages into cache; SDK-coupled servers remain system-managed.
Repository scanning respects ignores, skips symlinked directories and is
bounded.

## Post-edit diagnostics and Problems

After a successful agent `edit`, `write` or `patch` in Coding mode, the hook
captures diagnostics for the current document version and reports introduced
and resolved issues. Multi-file patches produce one combined observation.
Python falls back to Ruff when no LSP is available.

The Problems hub stores a current workspace projection with dismiss/suppress
actions. Static evidence is advisory: behavioral tests remain required.

## Managed language servers

Settings → Language servers lists every supported language with what EvoFlux
can do about it. Fourteen have a pinned install recipe; the rest carry a hint
for installing the server yourself. Recipes install through `npm`, `uv`, `go`,
`rustup` or `gem`, in one of two scopes: `managed` stages the binary into the
EvoFlux cache and resolves it without consulting PATH, while `toolchain` asks a
toolchain that owns its own components — a rustup component, a gem — to add the
server to itself, and confirms it by resolving the server on PATH afterwards.

The row always shows what can be done and why not. A language with no recipe, a
recipe whose prerequisite is absent, and an already-installed server are three
different states with three different sentences, rather than three rows with no
button. Detection reports when its file cap cut the walk short, because a
truncated scan under-reports languages.

An install outlives the request that starts it. `POST .../install` returns the
job's state and the status endpoint reports `install_phase` per language, so a
running install survives navigation and a failed one keeps its installer output
on its own row until dismissed. Compiling installers get a longer budget than
unpacking ones: `go install` builds gopls from source and measured 98s on a warm
network, where npm and uv finish well inside 180s.

## Search Everywhere and editor context

Search Everywhere combines bounded file/symbol/text sources for command-palette
navigation. Editor AI actions first build a preview of selected file/range,
diagnostics and repository context; resulting mutations use ChangeSets and
stale-base checks rather than direct hidden writes.

The exact live-edit contract is in
[Coding semantic intelligence](../architecture/coding-semantic-intelligence.md).

## Source and tests

Primary code: `app/services/code_index/`, `app/agent/tools/builtin/code_context.py`,
`app/agent/lsp_manager.py`, language-server/editor/Problems/search services and
routes, and graph/editor/Problems React components.

The parser contract has dedicated tests per language plus runtime, mutation and
symbol-coverage gates. LSP, ChangeSet, editor, Problems, graph and Search
Everywhere have focused backend and frontend suites.
