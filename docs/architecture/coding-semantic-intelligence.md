# Coding Semantic Intelligence

## Scope

Semantic intelligence is repository-local. A language-server process owns one
repository root and rejects documents outside it. Cross-repository discovery
remains the responsibility of `code_context`; semantic rename, code actions,
formatting, diagnostics, and AI ChangeSets never silently expand their write
scope to a sibling repository.

The feature deliberately excludes code completion, next-edit prediction,
debugger/AI-debug modes, Local History, and run/debug configurations.

## LSP contract

The persistent LSP client supports:

- diagnostics tied to the current document version;
- hover;
- code actions and quick fixes;
- repository-local rename;
- document formatting;
- organize imports;
- document and workspace symbols;
- definition and references.

The client stores advertised server capabilities and answers the standard
server-to-client requests required by semantic servers. A server-requested
`workspace/applyEdit` is rejected: all semantic mutations must become a
reviewed ChangeSet.

## Managed language-server lifecycle

Language-server packages are machine-level, regeneratable dependencies under
`EVOFLUX_CACHE_DIR/language-servers`. They are never written into a repository.
The runtime resolves a pinned EvoFlux-managed executable first and falls back
to a compatible executable on the system `PATH`.

Settings → Language servers scans the active project's authorized repository
set for known source extensions. Detection respects `.gitignore`, skips
symlinked directories, and is bounded to 50,000 files per repository. One
managed installation is shared by every repository, while each
`(repository, language)` pair still owns an independent LSP process and
document-version state.

Installation is never automatic. A user confirms one catalog entry, then the
backend installs allowlisted, pinned packages from a fixed public registry into
a staging directory, validates the expected executable, atomically activates
the cache entry, and restarts only clients for that language. Node-based
servers use npm with lifecycle scripts and user npm configuration disabled;
Python uses an isolated uv tool directory. SDK-coupled servers such as clangd,
sourcekit-lsp, Dart, rust-analyzer, and jdtls remain system-managed and expose a
toolchain-specific setup hint instead of invoking an OS package manager. Known
toolchain proxies are probed before being reported ready; for example, a rustup
`rust-analyzer` shim without the installed component remains `missing`.

## Automatic post-edit feedback

Every successful `edit`, `write`, or `patch` mutation in Coding mode triggers
the post-edit diagnostic hook. A multi-file patch produces one aggregated
observation. The hook:

1. captures a pre-edit diagnostic baseline;
2. synchronizes the changed content with its language server;
3. requires a diagnostic publication for the current document version;
4. rejects results when the file hash changes while diagnostics are in flight;
5. reports newly introduced and resolved diagnostics;
6. publishes the complete current snapshot into Problems.

Because `publishDiagnostics.version` is optional in LSP, a server that omits it
is accepted only after a new publication generation arrives following the
corresponding `didOpen`/`didChange`; cached pre-edit diagnostics are not reused.

Python falls back to Ruff when no language server is available. Clean output
explicitly states that static/LSP evidence does not replace behavioral tests.

## Guarded ChangeSets

AI, LSP, review, and Git workflows produce the same ChangeSet contract:

- repository-relative paths only;
- base SHA-256 and optional document version;
- UTF-16-aware conversion of LSP `WorkspaceEdit` text edits;
- multi-file preview through Monaco DiffEditor;
- per-file and whole-set Accept/Reject;
- stale-base validation before any write;
- atomic file replacement with rollback of earlier files on failure;
- optional session snapshot;
- bounded LSP and deterministic existing-project test/lint verification.

Model-provided verification strings never expand execution authority. EvoFlux
derives commands from existing project manifests and lockfiles, shows them in
the ChangeSet review before apply, and invokes them without a shell.

No model or language server writes proposed edits directly.
AI may replace an existing file only when its complete content and SHA-256 were
present in the reviewed context. Truncated or unseen existing files are
rejected; new files remain guarded by expected absence at apply time.
Project-bound Coding sessions may run explicit editor and Git AI actions in any
repository that is a persisted member of that project; arbitrary sibling paths
remain unauthorized.

## Problems hub

Problems normalizes these producers into one repository view:

- LSP;
- Ruff/tsc static diagnostics;
- shell build and test output;
- AI self-review;
- security review;
- Agent Plugin validation.

Each finding keeps source, severity, location, stable rule code, scope,
provenance, optional structured fix, and suppression identity. Users can stage
a fix, add it to a plan, dismiss it, suppress its rule, or send it to the
agent. Re-publishing one producer scope replaces stale findings without
removing unrelated sources.

## Explicit AI editor boundary

The editor never calls a model on keystrokes. A user chooses an AI action,
reviews the assembled context, and explicitly starts the call. Supported
actions are explanation, diagnostic fixing, refactoring, tests,
documentation, problem finding, simplification, pattern conversion, API-change
propagation, and terminal build/test failure explanation.
Action kinds are closed: explanation actions cannot return file changes,
problem scans cannot return mutations, and change actions must return a
Guarded ChangeSet.

`EditorContextEnvelope` contains:

- active file, document version, selection, and cursor symbol;
- current diagnostics and Git hunks;
- related symbols, callers, and callees from repository code context;
- recent agent changes and selected terminal failure;
- applicable `AGENTS.md` files;
- explicitly mentioned files and bounded folder listings;
- provenance and content hashes for every context category.

`.aiignore` is enforced before content enters the envelope. Provider-bound
messages pass through the existing outbound secret/PII policy. Source payloads
are not written to application logs. The preview returns a digest of the exact
envelope; execution is rejected if Git hunks, attachments, instructions, graph
evidence, or other context changed before the user starts the action.

## Git AI

Git actions are also explicit. The service supports self-review, commit-message
generation, commit explanation, PR title/description generation, incoming PR
summaries, merge-conflict proposals, and post-resolution review. Review and
security findings enter Problems; conflict resolutions enter Guarded
ChangeSets. Commit references are resolved to a verified commit SHA before
`git show`; option-like input is never passed through as a revision. Only
conflict-resolution actions may emit file proposals, and every existing target
is bound to the working-file hash captured in the reviewed conflict evidence.

## Search Everywhere

The command palette merges local actions/settings/agents with asynchronous
repository results for files, folders, symbols, text/code, Git branches and
commits, Problems, skills, workflows, and recent files. Caller-shaped natural
language queries are routed to code graph traversal; known navigation phrases
can route directly to the corresponding action.
