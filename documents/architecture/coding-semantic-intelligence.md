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
- bounded LSP and allowlisted existing test/lint command verification.

No model or language server writes proposed edits directly.

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
are not written to application logs.

## Git AI

Git actions are also explicit. The service supports self-review, commit-message
generation, commit explanation, PR title/description generation, incoming PR
summaries, merge-conflict proposals, and post-resolution review. Review and
security findings enter Problems; conflict resolutions enter Guarded
ChangeSets.

## Search Everywhere

The command palette merges local actions/settings/agents with asynchronous
repository results for files, folders, symbols, text/code, Git branches and
commits, Problems, skills, workflows, and recent files. Caller-shaped natural
language queries are routed to code graph traversal; known navigation phrases
can route directly to the corresponding action.
