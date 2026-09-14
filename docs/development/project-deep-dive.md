# EvoFlux project deep dive and continuation guide

Status: current-state engineering guide

Snapshot: `main` at `77cfd871` (`2026-08-25`)

Audience: contributors preparing to change, test, package, or extend EvoFlux

This guide is the shortest end-to-end mental model of the repository. It
summarizes what EvoFlux builds, how its processes and source tree fit together,
where runtime and development knowledge live, the conventions visible in code
and Git history, and the workflow expected for continued development.

It does not replace the detailed contracts linked throughout the document.
When this guide, current-state documentation, tests, and code disagree, follow
the source-of-truth rules in [Development knowledge used by contributors](#development-knowledge-used-by-contributors)
and reconcile the discrepancy in the same change.

## Executive summary

EvoFlux is a local-first desktop workspace for teams of Work and Coding agents.
It is not primarily a hosted web application. The production product combines:

1. a Rust/Tauri desktop shell that owns native lifecycle and capabilities;
2. a React/TypeScript UI rendered in the Tauri WebView;
3. a local Python/FastAPI sidecar that owns agent execution, policy,
   persistence, workspace authorization, automation, and integrations.

The key architectural idea is that models are replaceable reasoning engines.
EvoFlux owns the durable harness around them: context construction, agent/team
configuration, tools, permission checks, sandboxing, streaming, persistence,
memory, code intelligence, and verification.

The product has two durable execution modes:

- **Work mode** gives a session an isolated EvoFlux-managed workspace and a
  general execution/exploration team.
- **Coding mode** authorizes one repository or a named multi-repository project
  and adds editor, Git, code graph, LSP, Problems, ChangeSet, review, terminal,
  and worktree behavior.

The most important boundaries for future changes are:

- keep FastAPI routes thin and reusable behavior in services/runtime modules;
- keep provider payloads behind provider adapters and generic schemas neutral;
- keep server state in TanStack Query and live/client state in Zustand;
- keep native lifecycle and capabilities in Tauri, but policy and persistence
  in the sidecar;
- keep the application database separate from rebuildable repository indexes;
- treat external/tool/model/memory content as untrusted data;
- update specification, implementation, tests, current docs, and Help together
  when a user-visible contract changes.

## What the project builds

The repository produces four related artifacts:

| Artifact | Output and purpose |
|---|---|
| React application | `web/dist/`; the production UI embedded by Tauri |
| Python wheel | API-only `evoflux` package with the CLI, sidecar code, Alembic resources, and offline seed bundle; it does not embed the web UI |
| Python sidecar bundle | `desktop/sidecar-bundle/`; a standalone runtime assembled for native packaging and never committed |
| Native desktop packages | macOS DMG, Windows current-user NSIS installer, and Linux amd64 DEB |

Version `0.0.8` is declared in the Python, web, and Tauri package metadata. The
Python project description is “Self-hosted AI agents,” but the current product
contract positions EvoFlux as a desktop application; the FastAPI-only wheel and
Vite server are development, integration, and headless API surfaces.

Implemented product areas include streaming multi-agent chat, sessions and
folders, goals, workflows, scheduling, files and previews, terminal/process
control, Side Chat, Git/reviews, code graph/search, optional LSP integration,
scoped memory, a Markdown wiki with Dream consolidation, model providers,
Skills, MCP, plugins, browser/WebBridge integrations, sandbox/permissions, and
local telemetry. The authoritative implementation index is the
[feature catalogue](../features/README.md).

## Architectural mental model

```text
User
  |
  v
Tauri shell (Rust)
  |  native lifecycle, dialogs, tray, browser profile, capabilities, updates
  |  launches sidecar and injects per-launch origin/token
  v
React WebView (TypeScript)
  |  HTTP for commands/data, SSE for agent events, WebSocket for terminals/browser
  v
FastAPI sidecar (Python)
  |-- API routes: validation and transport translation
  |-- services: durable business and integration behavior
  |-- agent runtime: providers, hooks, tools, policy, teams
  |-- workflow/scheduler: automated execution
  |-- SQLModel/Alembic: durable application state
  `-- filesystem stores: config, wiki, workspaces, state, cache
```

### Process ownership

| Concern | Owner | Important entry points |
|---|---|---|
| Native startup and shutdown | Tauri | `desktop/src-tauri/src/main.rs`, `sidecar.rs` |
| Web bootstrap and routing | React | `web/src/main.tsx`, `App.tsx`, `router.ts`, `routes/work.tsx` |
| HTTP application lifecycle | FastAPI | `app/server.py`, `app/api/app.py` |
| Session/team orchestration | Python services/runtime | `app/services/chat_service.py`, `team_manager.py`, `app/agent/mode/team/` |
| Model/tool loop | Agent runtime | `app/agent/agent_loop/core.py` and sibling modules |
| Persistent application state | SQLModel/Alembic | `app/models/`, `app/scheduler/models.py`, `app/migrations/` |
| Repository intelligence | Cache-local service | `app/services/code_index/` |

The desktop shell starts the bundled sidecar on loopback with an ephemeral port
and random bearer token, waits for a handshake and liveness, then makes the
origin and token available to the WebView. The frontend installs same-origin
desktop authentication before other modules capture `fetch`. Cross-origin
requests do not receive the desktop token.

## Repository structure and ownership

```text
app/          Python sidecar, CLI, agent runtime, services, persistence
web/          React/Vite UI embedded in Tauri
desktop/      Rust/Tauri shell and native packaging
seed/         first-install agent and configuration templates
scripts/      development, validation, packaging, and release utilities
tests/        Python backend, integration, CLI, and packaging tests
docs/         only project documentation root
test-artifacts/ checked-in visual evidence for selected tests/reviews
```

Before editing anywhere, read the root `AGENTS.md` and the nearest nested one.
Nested instructions currently exist for `app/`, `app/agent/`, `app/api/`,
`app/services/`, `web/`, `web/src/`, `desktop/`, `desktop/src-tauri/`, `seed/`,
and `scripts/`.

### Backend map

| Path | Responsibility and extension rule |
|---|---|
| `app/api/routes/` | HTTP, SSE, upload, and WebSocket boundary. Validate and delegate; do not accumulate business logic here. |
| `app/api/schemas/` | Shared transport request/response shapes. Any shape change must be traced into frontend parsing and rendering. |
| `app/services/` | Reusable business logic for routes, CLI, scheduler, and agent runtime. |
| `app/agent/agent_loop/` | Per-turn streaming loop, retry/fallback, tool dispatch, checkpointing, and observation limits. |
| `app/agent/hooks/` | Context injection, memory, persistence, streaming, telemetry, diagnostics, and completion behavior. |
| `app/agent/mode/team/` | Lead/member lifecycle, mailboxes, delegation, handoff, todo, continuation, and team concurrency. |
| `app/agent/providers/` | Provider adapters and routing. Provider-specific wire shapes stop here. |
| `app/agent/tools/` | Tool registry, metadata, permission integration, and built-in implementations. |
| `app/agent/skills/` | Skill discovery, collision resolution, settings overlays, and activation. |
| `app/agent/mcp/` | User-global MCP config, process/client manager, and exposed MCP tools. |
| `app/plugin_platform/` | Portable Agent Plugin install/runtime boundary and isolated plugin MCP. |
| `app/workflow/` | Workflow schema, validation, graph, runner, and node handlers. |
| `app/scheduler/` | At/every/cron task persistence and team dispatch. |
| `app/conductor/` | Optional managed-resource and telemetry control-plane client. |
| `app/core/` | Settings, paths, database lanes, auth, logging, metrics, and telemetry. |
| `app/models/` and `app/migrations/` | Application SQLModel metadata and 54-version Alembic history at this snapshot. |
| `app/cli/` | `evoflux` CLI parser and command modules. |

### Frontend map

| Path | Responsibility and extension rule |
|---|---|
| `web/src/router.ts` | Work, Coding, Telemetry, and Scheduler route tree. Settings and Help are overlays. |
| `web/src/routes/work.tsx` | Resolves/restores Work or Coding session focus and synchronizes URL/store state. |
| `web/src/components/TeamChatView/` | Main composition root for chat, sidebars, workbench, SSE hooks, and responsive layouts. |
| `web/src/components/shell/` | Shared application, sidebar, row, menu, and side-panel chrome. Reuse these primitives. |
| `web/src/components/workbench/` | Lazy workbench dock, registry, surfaces, and open-with behavior. |
| `web/src/api/` | HTTP client domains, same-origin token handling, SSE parser, and Tauri boundary. |
| `web/src/queries/` | TanStack Query keys, queries, mutations, and durable server-state caching. |
| `web/src/stores/` | Zustand live-turn and client/UI state. SSE reduction lives with the team store. |
| `web/src/help/locales/` | Localized user-facing Help in English, Vietnamese, and Japanese. |
| `web/src/__tests__/` | Vitest tests for components, API helpers, stores, hooks, Help, and utilities. |

`TeamChatView` and the team store are high-connectivity areas. They are already
split into hooks, reducers, domain clients, and lazy panels; extend those seams
instead of growing a second composition or state path.

### Desktop and packaging map

| Path | Responsibility |
|---|---|
| `desktop/src-tauri/src/main.rs` | Tauri plugins, windows, tray/events, and native command registration |
| `desktop/src-tauri/src/sidecar.rs` | Sidecar discovery, launch, handshake, health, and cleanup |
| `desktop/src-tauri/src/workspace.rs` | Native workspace/filesystem integration |
| `desktop/src-tauri/src/native_messaging.rs` | Browser native-messaging bridge |
| `desktop/src-tauri/capabilities/` | Explicit Tauri command grants |
| `desktop/src-tauri/tauri*.json` | Production, external-dev, and bundled-dev variants |
| `scripts/build_sidecar.py` | Standalone Python runtime assembly |
| `.github/workflows/desktop-packages.yml` | Four-platform packaging, signing, updater, and artifact workflow |

## End-to-end runtime walkthrough

### Startup

1. Tauri creates the application shell and starts or connects to the Python
   sidecar according to the selected development/production configuration.
2. The sidecar reports its chosen loopback port and token through the handshake.
3. FastAPI initializes the workspace roots, validates/migrates the database in
   production, seeds the wiki, initializes telemetry, and exposes the critical
   API before slower optional integrations finish.
4. Optional startup tasks reconcile MCP, plugin MCP, Conductor, agent files,
   scheduler, scoped-memory backfill, Dream scheduling, and retention services.
5. React waits for backend readiness, installs authentication, restores theme,
   appearance, locale, and the last mode route, then mounts the router.

Optional service failure is observable but should not make the critical local
API disappear. Shutdown drains or stops teams, indexes, processes, previews,
language servers, memory extraction, telemetry, and database engines.

### One chat turn

1. `POST /api/team/chat` validates and queues a request, returning `202`.
2. `team_manager` resolves/builds the correct Work or Coding team. Coding
   identity includes the authorized workspace/project, not just a UI mode bit.
3. The session transcript and current checkpoint are loaded from SQLite.
4. Hooks add bounded workspace instructions, project/folder context, selected
   Skills, profile data, scoped memory recall, and other runtime context.
5. A provider adapter translates canonical messages/tools to its own protocol
   and streams text, reasoning, usage, and tool calls back into canonical types.
6. The loop partitions tool calls into concurrency-safe waves and serial
   barriers, with at most ten concurrently executing tools.
7. Permission, sandbox, workspace authorization, and outbound-data policy are
   enforced before the tool/model boundary. Large observations can be offloaded
   to artifacts rather than kept inline.
8. The loop continues through tool results until a final response, explicit
   pause, interruption, recoverable continuation, or terminal error.
9. Checkpoints and hooks persist transcript/usage, update goals/workflows,
   publish SSE events, collect diagnostics, and schedule memory extraction.
10. The frontend loads durable history first, layers the live SSE projection
    over it, and updates Query caches through an explicit invalidation bridge.

SSE is the live projection; SQLite session/message history is the durable truth
used for reconnect and pagination. Bidirectional terminal, direct-browser, and
WebBridge relay channels use WebSockets instead.

### Teams and delegation

Exactly one lead is required per team. Member definitions are lazy blueprints,
not permanent background processes. Delegation creates instances such as
`coder#1`; each gets its own child session, mailbox, history, and lifecycle.
Member text/tools/status are streamed through the parent session without
copying the member's complete model context into the lead. Durable delegation
rows record the work state, while the lead remains responsible for verifying a
handoff before presenting it as complete.

## How knowledge is stored

“Knowledge” has two meanings in this project and they should not be mixed.

### Runtime knowledge used by agents

| Layer | Storage | Role and trust rule |
|---|---|---|
| Working memory | `chat_sessions` and `session_messages` in the application DB | Full durable transcript; provider-visible history may be compacted, but audit history remains. |
| Episodic evidence | `memory_fact_evidence` | Links a fact to the source session/message that established it. |
| Semantic memory | `memory_facts` | Deduplicated facts with explicit user/project/workspace/folder/session scope, confidence, kind, status, origin, and occurrence count. |
| Extraction cursor | `memory_extraction_states` | Retryable lease/cursor so background extraction is idempotent across restarts. |
| Inspectable wiki | Markdown under `EVOFLUX_WIKI_DIR` | Human-readable profile, notes, topics, entities, sources, comparisons, indexes, and Dream logs. Treated as data, not executable policy. |
| Code knowledge | One cache-local SQLite DB per repository | Rebuildable files, chunks, FTS rows, symbols, relations, vectors, and parse errors. Never application DB state. |

Semantic facts are the canonical automatic-recall store. The wiki is an
inspectable consolidation/projection and manual knowledge surface, not the sole
copy of extracted memory. Automatic extraction begins after the configured
completed-lead-response threshold (default behavior starts at three and then
periodically), rejects secret-like content, limits fact count/length, and
coerces invalid broad scopes to the narrowest available safe scope.

Recall searches only compatible scopes and injects a small cited result inside
an explicit untrusted-data boundary. User-global scope is limited to explicit
durable preferences/profile; technical decisions stay project/workspace/folder
or session local. Deleting a session removes its evidence and deletes a fact
only when no other evidence remains.

The wiki is seeded idempotently with:

```text
USER.md             durable profile YAML, injected as bounded data
INDEX.md            Dream-maintained table of contents
LOG.md              chronological Dream log
LINT.md             latest wiki lint result
topics/             concepts
entities/           people, tools, organizations, products
sources/            source summaries
comparisons/        comparison pages
notes/              append-only daily agent/user notes
imports/            raw imported evidence
```

Dream incrementally consolidates top-level sessions and changed notes. Database
watermarks prevent unchanged sources from being processed repeatedly;
filesystem locks and atomic replacement protect cross-process wiki writes.

Repository code indexes live at:

```text
<cache>/code-index/<sha256(canonical-repository-path)[:24]>/code-context.sqlite3
```

They are desired-state caches and may be rebuilt after schema/corruption
checks. Multi-repository links are resolved dynamically over only the
repositories authorized for the active project; no global cross-repository
knowledge graph is persisted.

### Runtime roots and retention

| Root | Typical contents | Recovery expectation |
|---|---|---|
| data | `evoflux.db`, installed plugin registry/private data, durable artifacts | Back up; internal and denied to agents by default |
| config | `.env`, settings, agent Markdown, Skills, MCP, sandbox, workflows | Back up; user-editable and policy-controlled |
| state | logs, per-session JSONL diagnostics, snapshots, OTEL, Conductor queues | Operational evidence; not primary product truth |
| cache | code indexes, model/OAuth cache, previews, LSP packages | Regeneratable |
| wiki | profile, notes, consolidated knowledge | Back up; bounded agent access |
| workspace | Work session files/uploads; Coding uses authorized repositories | User output; retention depends on mode/project |

Development defaults live below `.evoflux/dev/`; production defaults use
XDG-style directories under the user's home. Tests override all roots to
`.tests/`. See the [configuration reference](../reference/configuration.md) for
exact environment variables and precedence.

Session JSONL under `<state>/logs/sessions/<session>/<agent>.jsonl` records
diagnostic events such as model calls, assistant messages, tools, results, and
usage. It is observability data; the SQL transcript remains canonical.

### Development knowledge used by contributors

Use this precedence when deciding what the software is supposed to do:

1. an accepted specification for the planned change;
2. current-state contracts in `docs/features/`, `docs/architecture/`, and
   `docs/reference/`;
3. tests as executable evidence;
4. existing code as implementation evidence;
5. historical material in `docs/plans/`, `docs/analysis/`, `docs/research/`,
   and `docs/releases/` as rationale, not proof of current behavior.

`AGENTS.md` files define contributor process and local invariants. The feature
catalogue maps behavior to owners. Architecture pages define storage, process,
concurrency, and trust boundaries. Reference pages define public API/config/CLI
contracts. Tests do not substitute for an absent product specification.

If code, tests, and current docs disagree during discovery, investigate and
state the discrepancy; do not silently choose the easiest artifact. When a
change ships, current docs must describe the implementation and historical
plans must not be mistaken for the active contract.

## Persistence and database rules

The application database is SQLModel metadata managed by Alembic. At this
snapshot its durable domains include sessions/messages/folders, Coding
workspaces/projects, Git server connections, team delegation, goals, scoped
memory, Dream watermarks, scheduler tasks, workflows/gates, and WebBridge state.

SQLite uses WAL and foreign keys with two deliberate lanes:

- a bounded read engine/pool for read requests;
- one FIFO writer connection for mutations and durable streams.

Never hold a database transaction while scanning the filesystem, invoking Git,
calling a model/network, starting a process, or waiting for SSE. Prepare
external work first, keep the write transaction short, and use explicit
idempotency/optimistic checks where retries are possible.

A schema change is incomplete unless it:

1. updates/imports SQLModel metadata;
2. adds an Alembic revision;
3. passes migration-head and supported upgrade-path tests;
4. updates affected feature/architecture/reference documentation;
5. defines compatibility and rollback behavior.

## Coding conventions

### Python

- Python `>=3.12`, dependency management and commands through `uv`.
- Use `from __future__ import annotations`, `|` unions, strict signature types,
  absolute `app...` imports, Pydantic v2, SQLModel, and async I/O boundaries.
- External/provider payload models normally use `ConfigDict(extra="ignore")`
  for forward compatibility.
- Loguru uses structured templates such as
  `logger.info("event_name key={}", value)`; avoid interpolation that defeats
  structured fields.
- Routes validate/translate. Services/runtime own reusable behavior.
- Provider adapters translate to/from canonical chat, stream, tool, and usage
  schemas; generic API/team code should not recognize provider wire formats.
- Tool changes must account for registry metadata, mode tier, deferred loading,
  permission/sandbox behavior, result bounding/offload, UI rendering, and tests.
- Preserve async cancellation, cleanup, and retry semantics. Tests should use
  injected timing/factories rather than real sleeps or external services.

### TypeScript and React

- ESM only, strict TypeScript, functional components, explicit props, and
  application imports through `@/`.
- The existing files use single quotes and no semicolons; follow surrounding
  formatting rather than introducing a second style.
- TanStack Query owns server state. Zustand/Immer owns live streaming and UI
  state. Components should not create a parallel durable cache.
- API changes flow through domain clients, query hooks/store projection, and
  focused rendering tests.
- Shared shell/workbench primitives own application chrome; new screens should
  compose them rather than hand-roll sidebars or resizable panels.
- `localStorage` keys belong in `STORAGE_KEYS`; numeric z-index literals are
  replaced by the `--z-*` token scale.
- Markdown parsing is centralized in `src/utils/markdown.tsx` and enforced by
  ESLint restricted imports.
- Large workbench panels are lazy-loaded. Preserve the initial chat bundle and
  use small store selectors to avoid unstable render subscriptions.

### Rust and Tauri

- Rust 2021 with minimum Rust 1.77 and Tauri v2.
- Keep lifecycle/auth changes small and platform-aware. Check Windows, macOS,
  and Linux cleanup and process behavior.
- Native commands require matching Tauri capability grants; do not expose a
  broad command because one frontend caller needs a narrow operation.
- Keep production, external-dev, and bundled-dev configuration variants in
  sync when a capability, plugin, or sidecar contract changes.
- Do not commit `target/`, sidecar bundles, generated packages, signing keys,
  or machine-local state.

### Tests and documentation

- Python tests mirror backend ownership under `tests/agent`, `api`, `services`,
  `core`, `workflow`, `scheduler`, `plugin_platform`, `conductor`, and `cli`.
- Frontend unit/component tests live under `web/src/__tests__`; Rust unit tests
  are colocated and desktop/package contracts also have Python tests.
- Test names should describe observable behavior. For non-trivial work, make
  the acceptance-criterion mapping discoverable in the plan, test, or evidence.
- Current behavior goes in `docs/features`, `docs/architecture`, or
  `docs/reference`; proposed/historical work goes elsewhere and is labeled.
- User-visible changes also update localized in-app Help when applicable.

## Commit-message convention

There is no separate commit-lint configuration in this snapshot, so Git
history is the practical convention rather than an independently enforced
contract. Use Conventional Commit-style subjects:

```text
<type>(<scope>): <imperative outcome>
```

Examples from current history:

```text
refactor(memory): add scoped durable learning
fix(db): repair and enforce sqlite foreign keys
fix(code-graph): isolate and cache snapshot builds
perf(chat): stabilize incremental transcript rendering
docs(coding): define semantic intelligence contracts
test(code-graph): close combined mutation gate
chore: bump version to 0.0.7
```

Recommended types are `feat`, `fix`, `refactor`, `perf`, `test`, `docs`,
`chore`, and rarely `style`. Choose a stable product/component scope such as
`agent`, `api`, `browser`, `chat`, `code-graph`, `coding`, `db`, `desktop`,
`git`, `lsp`, `memory`, `providers`, `release`, `sandbox`, `skills`, `ui`,
`web`, or `webbridge`.

Evidence from the latest 200 subjects at this snapshot: 94 `fix`, 56 `feat`,
9 `refactor`, 8 `perf`, 7 `docs`, 6 `test`, 5 `chore`, 1 `style`, and 14 merge
or non-conventional subjects. In other words, scoped conventional subjects are
the dominant style; merge commits and a few legacy/simple subjects are
exceptions. Recent commits generally have concise subjects and no body, so add
a body when compatibility, security, migration, or non-obvious rationale would
otherwise be lost.

Commit discipline for continued work:

- one coherent change/outcome per commit;
- imperative summary, lowercase type/scope, no trailing period;
- keep generated artifacts, secrets, and machine paths out of commits;
- do not mix unrelated cleanup with a feature/fix;
- make specification, implementation, tests, and current docs reviewable as
  one traceable change when they define the same shipped contract.

## Run, test, and build commands

### Install

```bash
uv sync
cd web && bun install --frozen-lockfile
```

### Development

```bash
make run          # FastAPI only; uvicorn default :8000
make dev-web      # FastAPI :8000 + Vite :5173
make dev-desktop  # FastAPI + Vite + Tauri source shell
```

Use `make -C desktop dev-bundled` when validating the packaged-sidecar import,
migration, authentication, resource, or cleanup path. It is slower and is not
the normal edit loop.

### Quality gates

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q

cd web
bun run lint
bun run typecheck
bun run build

cd desktop/src-tauri
cargo check
```

Use the smallest focused suite while iterating, then expand according to the
affected boundary. The repository currently contains a desktop packaging
workflow, not a general all-layer CI workflow, so local quality gates are
especially important and must be reported exactly at handoff.

### Build and package

```bash
make build-web              # web/dist
make build                  # Python wheel
make -C desktop sidecar     # standard sidecar + Office preview engines
make -C desktop sidecar-full  # adds Azure Document Intelligence
make -C desktop build       # native package on the host platform
```

Tagged desktop builds require updater signing inputs. macOS signing/notarization
and Windows Authenticode use CI secrets; Linux packages are updated through the
package manager rather than in-place Tauri replacement. Follow the
[release and packaging contract](release-and-packaging.md) before changing
versioning, signing, sidecar resources, or installer behavior.

## Continued-development workflow

The repository requires Specification-Driven Development (SDD) and uses
Agent-Driven Development (ADD) only where bounded parallel ownership improves
the result. Use this sequence for every non-trivial change.

### 1. Establish a clean evidence baseline

- Read root and nearest nested `AGENTS.md` files.
- Record branch, `git status --short`, and relevant user-owned changes.
- Read the feature catalogue row, current feature contract, architecture and
  reference pages, owning code, migrations, frontend consumers, and focused
  tests.
- Distinguish implemented behavior from plans/research and note any mismatch.

### 2. Classify the change

| Change type | Required preparation |
|---|---|
| User-visible feature, public API/event, persistence, security, compatibility | Full specification with stable AC IDs and verification matrix before implementation |
| Bug against documented behavior | Cite the contract and add a failing regression test; update spec only if ambiguous/changing |
| Internal refactor/performance | Record invariants, measurable outcome, and verification plan |
| Trivial docs/typo/mechanical edit | Clear task scope is sufficient |

When auth, permissions, migrations, concurrency, provider protocol, filesystem
scope, or release behavior is involved, use the stronger path even if the diff
looks small.

### 3. Specify and plan

- Put proposed design in `docs/plans/`; update current-state docs when behavior
  actually ships.
- Define goals, non-goals, user states, API/event/UI contracts, data and trust
  behavior, failure/recovery/idempotency, compatibility, rollback, diagnostics,
  and acceptance criteria.
- Map each AC to implementation owner, test/evidence, and current docs.
- Plan vertical slices that leave the application usable and can be verified
  independently.
- Delegate only disjoint, concrete work with explicit file ownership and ACs;
  the lead still integrates and verifies cross-layer seams.

### 4. Implement at the owning boundary

- Route change: transport validation in `app/api`, durable logic in a service or
  runtime module, response schema plus frontend client/query/store/rendering.
- SSE change: backend envelope, frontend parser, block/store reducer, UI
  acknowledgement, and focused tests move together.
- Persistence change: model metadata, migration, upgrade-path tests,
  compatibility/rollback, and docs move together.
- Tool change: registry/tier/deferred metadata, permission/sandbox, execution,
  result rendering, and tests move together.
- UI change: query/store ownership, shared chrome, mobile behavior, Help, and
  component tests move together.
- Native change: Rust command/lifecycle, capabilities, every relevant Tauri
  config, frontend bridge, desktop tests, and platform smoke evidence.

Do not silently revise accepted behavior to fit the easiest implementation. If
discovery invalidates the specification, stop that slice, revise the spec/plan,
and make the deviation visible.

### 5. Verify in layers

1. run the smallest regression test that proves the change;
2. run the owning directory's lint/type/test command from its `AGENTS.md`;
3. run seam tests for every changed API/SSE/persistence/native boundary;
4. run broader gates in proportion to risk;
5. inspect the final diff for unrelated or generated changes;
6. run `git diff --check`;
7. verify docs links and Help/catalog/reference reconciliation.

Do not claim completion when a required migration, contract consumer, generated
resource, doc link, or affected-layer test remains unresolved. Separate
pre-existing failures from failures introduced by the change with evidence.

### 6. Hand off for the next contributor

Report:

- outcome and ACs satisfied;
- files and public/internal contracts changed;
- exact commands and results;
- assumptions and material decisions;
- remaining risks, blockers, or checks not run;
- confirmation that unrelated work was preserved.

## Common change traces

| If changing... | Trace at minimum... |
|---|---|
| Chat/session behavior | session models and migrations → chat/team service → route/SSE → API client → team store/query caches → chat UI → backend/frontend tests → feature docs |
| Agent provider | provider factory/catalog/capabilities → adapter schemas/streaming → generic canonical schema compatibility → provider tests → Settings/model UI if exposed |
| Tool | registry metadata/tier → implementation → permission/sandbox → observation/offload → SSE/block rendering → tests and Help |
| Memory | extraction/context hooks → scoped-memory service/models → deletion/provenance behavior → wiki projection/Dream → memory tests → memory architecture/feature docs |
| Coding intelligence | workspace/project authorization → repository-local index/LSP service → API → Query/store → editor/graph/Problems UI → parser/service/frontend tests |
| Git/review | workspace authorization and credential boundary → Git/review service → thin route → domain client/query → Git/review panel → destructive-action guard tests |
| Scheduler/workflow | persisted model → runner/scheduler service → team turn boundary → route/tool → frontend projection → restart/idempotency tests → automation docs |
| Desktop startup | Tauri sidecar supervisor → CLI `serve` handshake → FastAPI auth/health → frontend bootstrap → Tauri capabilities/config variants → package smoke tests |

## Known hotspots and practical cautions

- **Session identity is cross-layer.** Work/Coding mode, workspace, project,
  parent/side-chat ownership, model, and permission state must agree across URL,
  store, service, and DB. Do not infer Coding authorization from the current UI.
- **Streaming has two truths with different lifetimes.** SSE is an in-memory
  live projection; the DB is reconnect history. Changes must work during a live
  turn, after refresh, and after process restart.
- **SQLite is deliberately serialized for writes.** Long transactions or hidden
  I/O inside them can stall the whole desktop product even when unit tests pass.
- **Memory is scoped and untrusted.** Never convert a project decision into a
  user-global preference or inject recalled/wiki text as policy.
- **Code indexes are disposable and authorization-scoped.** Do not move them
  into app tables or persist cross-repository guesses.
- **Agent files are user-owned after initialization.** First-party base prompts
  stay in code; seed frontmatter is additive and affects new installs only.
- **Frontend state ownership is intentional.** Query, Zustand, URL state, and
  local storage each have a distinct role. Duplicating state produces difficult
  reconnect and navigation bugs.
- **Optional integrations must degrade visibly.** MCP, plugins, Conductor,
  Dream, browser, document engines, and LSP may be absent; keep the core API and
  chat surface diagnosable.
- **Desktop changes are multi-platform.** A Windows-only fix can still alter
  shared lifecycle or capability configuration used on macOS/Linux.
- **Plans are historical records.** A detailed plan is not evidence that a
  feature shipped; confirm through current docs, code, and tests.

## Suggested first-day walkthrough

For a new contributor, this reading/debugging path gives the fastest useful
model of the project:

1. [Documentation index](../README.md), [feature catalogue](../features/README.md),
   and [system overview](../architecture/system-overview.md).
2. `app/api/app.py` for lifecycle and public router families.
3. `app/services/team_manager.py` and `app/agent/agent_loop/core.py` for team and
   turn execution.
4. `app/models/chat.py`, `app/models/memory.py`, and
   [data/storage architecture](../architecture/data-and-storage.md).
5. `web/src/router.ts`, `web/src/routes/work.tsx`, and
   `web/src/components/TeamChatView/index.tsx` for UI composition.
6. `web/src/stores/useTeamStore/` and `web/src/api/` for history/live state.
7. `desktop/src-tauri/src/sidecar.rs` for the production process boundary.
8. The focused tests beside the area you intend to change.

Then run one mode locally, follow a single chat turn from the network request to
SSE rendering and persisted history, and only after that choose an extension
point. This exposes the cross-layer contracts that are easy to miss in a
directory-only tour.

## Primary references

- [System overview](../architecture/system-overview.md)
- [Backend runtime](../architecture/backend-runtime.md)
- [Web frontend](../architecture/web-frontend.md)
- [Desktop shell](../architecture/desktop.md)
- [Data and storage](../architecture/data-and-storage.md)
- [Memory architecture](../architecture/memory-system.md)
- [SQLite concurrency](../architecture/sqlite-concurrency.md)
- [Application harness](../architecture/application-harness.md)
- [Repository map](../reference/repository-map.md)
- [Configuration](../reference/configuration.md)
- [HTTP API](../reference/http-api.md)
- [Development and testing](setup-and-testing.md)
- [Release and packaging](release-and-packaging.md)

## Snapshot notes

This review inspected the owning instructions, current architecture/feature/
reference documentation, runtime entry points, application models and latest
migration, memory/wiki/index implementations, agent loop/provider/team
boundaries, API router families, frontend router/query/store/composition paths,
Tauri sidecar/package configuration, test layout, build scripts, and the latest
200 Git subjects. The worktree was clean before this documentation was added.

Because this is a living system, refresh the snapshot line and any numeric
observations (version, migration count, provider count, commit distribution)
when they materially change; the linked current-state contracts remain the
preferred durable source.
