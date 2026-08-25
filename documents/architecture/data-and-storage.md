# Data and storage

EvoFlux separates durable application state, user-managed configuration,
inspectable knowledge, regeneratable cache, logs/telemetry, and per-session
workspaces. This separation is part of the sandbox and backup contract.

## Runtime roots

| Root | Contents | Agent access |
|---|---|---|
| data | Application database, installed plugin registry/data, durable artifacts | Denied by default |
| config | Agents, Skills, MCP, settings, sandbox, provider secrets | Policy-controlled; intended for user editing |
| state | Logs, snapshots, OTEL, telemetry and Conductor queues | Denied by default |
| cache | Code indexes, model metadata, OAuth cache, LSP packages, previews | Denied; regeneratable |
| wiki | `USER.md`, knowledge pages, notes, imports and Dream logs | Allowed through bounded wiki/memory tools |
| workspace | Work session roots and uploads | Active session root; Coding uses authorized repositories |

Exact paths and overrides are in [Configuration](../reference/configuration.md).

## Application database

The main SQLModel/Alembic database stores:

| Domain | Primary tables/models |
|---|---|
| Chat | sessions, messages, folders, Coding workspaces/projects and memberships |
| Teams | durable delegation tasks |
| Goals | objective, budget, elapsed usage, blocker state and version |
| Memory | scoped facts, evidence and extraction state |
| Dream | processed session/note logs |
| Scheduler | task definitions, targets and run status |
| Workflows | approvals, executions, node runs and gate requests |
| Git/reviews | server connection metadata |
| WebBridge | pairings, interactions, tab bindings, Teach drafts and replays |
| Evo Agent Specs (EASD) | rebuildable local run projection and generic delegation execution only; repository YAML is normative |

SQLite is the default embedded database and uses WAL, foreign keys, a bounded
read pool and a single FIFO writer. Production startup automatically migrates
and validates schema compatibility. Refer to
[SQLite concurrency](sqlite-concurrency.md) for transaction rules.

EASD is the explicit product-state exception: the owning repository's
manifest-selected data directory stores shared Intent, lifecycle, Spec/Plan
revisions, missions, evidence, deviations, events, and convergence. SQLite may
materialize those documents for the local runtime but can be rebuilt and never
wins over Git state. See [Evo Agent Specs architecture](evo-agent-specs.md).

## Repository-local code indexes

Each authorized repository has its own SQLite target under the cache root. It
contains source fingerprints/snapshots, AST-aware chunks, deterministic local
vectors, FTS rows, symbols, relations and current indexing errors. It is not
part of the application database and can be rebuilt from repository source.

Multi-repository project links are resolved dynamically across only the
repositories authorized for the active project; no cross-repository guesses are
persisted in application state.

See [Coding-agent code context](coding-agent-code-context.md).

## Memory stores

Memory has three layers:

- current transcript as working memory;
- SQL-backed semantic facts scoped to user, folder, workspace, project or
  session, with evidence linking facts back to source sessions/messages;
- an inspectable Markdown wiki consolidated by Dream.

Automatic recall queries only compatible scopes, treats recalled text as
untrusted data, and injects a small bounded result. Secret-like facts are
rejected during extraction. See [Memory and Dream](../features/memory-and-dream.md).

## Files and artifacts

Work sessions place uploads and generated files under their session workspace.
Large tool observations may be offloaded to data-backed session artifacts with
references in the transcript. Session snapshots support revert/undo boundaries.
Preview output, OAuth responses, model catalog responses, code indexes and
language servers belong in cache because they can be recreated.

Cleanup uses two-phase planning/application and optimistic metadata checks so a
retention pass does not overwrite newer transcript metadata.

## Backup guidance

For a user-controlled backup, prioritize the config root, wiki root, application
data database, and any Work workspace files that matter. State and cache can be
excluded unless logs or offline indexes are specifically required. Persistent
Coding repositories are external user repositories and retain their own backup
and version-control policy.
