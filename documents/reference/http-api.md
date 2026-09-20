# HTTP and streaming API

The FastAPI sidecar serves JSON HTTP routes under `/api`, Prometheus metrics at
`/metrics`, Server-Sent Events for turn/file streams, and WebSockets for
terminal/browser relays. The running build exposes the exact schema at
`/openapi.json` and interactive FastAPI documentation at `/docs`.

## Authentication

When desktop or access-key authentication is configured, send:

```http
Authorization: Bearer <token>
```

Raw media/download navigations may use `?_token=<token>`; middleware removes the
token from the downstream query string to reduce logging exposure. Live/ready
health, metrics and static SPA assets are exempt. WebBridge pairing/relay routes
use narrower scoped credentials where documented by their schemas.

An unconfigured loopback CLI server keeps token middleware disabled. LAN or
external deployments should configure an access key and restrictive CORS.

## Route families

| Prefix | Responsibility | Primary router |
|---|---|---|
| `/api/health` | liveness, readiness and bounded diagnostics | `health.py` |
| `/api/diagnostics` | runtime/platform/path diagnostics | `diagnostics.py` |
| `/api/team` | chat, sessions, files, terminal, projects and Coding workbench | `routes/team/` |
| `/api/team/webbridge` | pairing, browser-panel chat, relay, bindings and Teach | `team/webbridge.py` |
| `/api/asdd` | Agent Spec-Driven: changes, capability specs, approvals, evidence and archive | `asdd.py` |
| `/api/agents` | agent registry and editable/runtime configuration | `agents.py` |
| `/api/skills` | Skill discovery, CRUD and runtime settings | `skills.py` |
| `/api/mcp` | global/plugin server status and global MCP lifecycle | `mcp.py` |
| `/api/plugins` | package inspection/install/editor/credentials/lifecycle | `plugins.py` |
| `/api/settings` | providers, sandbox, Git, browser and Conductor | `settings.py` |
| `/api/code-context` | compatibility single-repository index/query/graph | `code_context.py` |
| `/api/workflows` | definitions, approval, run and execution status | `workflows.py` |
| `/api/scheduler` | task CRUD, pause/resume and trigger | `scheduler.py` |
| `/api/wiki` | validated Markdown tree/file operations | `wiki.py` |
| `/api/dream` | config, manual run/status and lint | `dream.py` |
| `/api/observability` | aggregates including cache read/write token classes, trace pages and trace detail | `observability.py` |
| `/api/commands` | slash-command catalogue/rendering | `commands.py` |
| `/api/snippets` | snippet catalogue/rendering | `snippets.py` |
| `/api/auth` | provider OAuth login/callback | `auth.py` |
| `/api/quote` | cached quote-of-the-day | `quote.py` |
| `/api/settings/remote` | remote access settings | `settings_remote.py` |
| `/api/remote` | connections, pairing links and pairing state | `remote.py` |

## Remote access

Remote access routes manage a user-owned Telegram bot connection and phone
pairing.

### Settings

- `GET /api/settings/remote` returns remote settings (`outbound_data_policy`,
  `outbound_pii_policy`).
- `PUT /api/settings/remote` updates remote settings atomically.

### Connections

- `GET /api/remote/connections` lists connections (0 or 1; v1 allows one per
  installation).
- `POST /api/remote/connections` creates a connection. The request body includes
  the bot token (write-only; never returned in responses). The endpoint verifies
  the token with the Telegram API and stores it in the OS vault.
- `PATCH /api/remote/connections/{id}` updates `label` or `enabled`.
- `PUT /api/remote/connections/{id}/token` replaces the bot token (write-only).
- `DELETE /api/remote/connections/{id}` removes the connection and revokes any
  active pairing.

### Pairing

- `POST /api/remote/connections/{id}/pairing-links` issues a pairing link (and
  optional QR). The link contains a short-lived token the phone bot resolves.
- `GET /api/remote/connections/{id}/pairing` reads the current pairing state
  (`pending`, `paired`, `revoked`).
- `DELETE /api/remote/connections/{id}/pairing` revokes the active pairing.

## Team subresources

The `/api/team` router includes:

- accepted chat/command ingress and per-session SSE;
- session CRUD, history, metadata, duplicate, queue, goal and todos;
- mode-scoped `GET /api/team/leads`, session-aware `GET /api/team/agents`, and
  idle-only `PATCH /api/team/sessions/{session_id}/lead` selection;
- Work folders and shared-folder context;
- workspace files/uploads/media/previews and file-watch SSE;
- Coding projects, workspace authorization/tree/files and worktrees;
- Git, Git AI, code reviews and Git server connections;
- ChangeSets, editor actions/context, LSP/language-server and Problems;
- code-index status/index/query/graph per Coding project;
- terminal and direct-browser WebSockets;
- managed processes and `preview` dev-server targets/start/stop;
- Side Chat messages and stream;
- command-palette search: workspace-scoped
  `POST /api/team/workspace/search-everywhere` and application-wide
  `POST /api/team/search-app`.

Use the OpenAPI document rather than copying request/response field definitions
from this overview.

## Agent Spec-Driven (ASDD)

Agent Spec-Driven routes are Coding-scoped, and every one of them identifies a change
by its slug. None takes a content hash, a revision id or a session id.

- `GET /api/asdd/setup` returns per-repository installation state for a
  workspace or Coding Project: `not_initialized`, `upgrade_required`, `ready` or
  `invalid`, with the manifest, catalogue, rules and skills paths, the six
  installed Skill names, and what is missing;
- `POST /api/asdd/setup` installs or repairs. `data_directory` selects the
  repository-relative catalogue (default `documents/asdd`). Repair needs
  `overwrite=true` and never touches a change or a capability spec;
- `GET /api/asdd/changes` lists open changes, archived entries and known
  capabilities for one workspace. A change folder that cannot be read is omitted
  and logged rather than failing the list;
- `POST /api/asdd/changes` creates a change. The slug comes from `change_id` when
  given, otherwise from the title; a collision against an open or archived change
  is a `409`;
- `GET /api/asdd/changes/{change_id}` returns the change, its action rail, and
  its proposal, deltas, design, tasks and evidence as Markdown;
- `POST /api/asdd/changes/{change_id}/approve/{artifact}` records a human
  approval for `proposal`, `specs`, `design` or `tasks` and advances the status.
  An approval the files do not support returns `409` with
  `detail.code = asdd_action_blocked` and the blockers the rail already showed;
- `POST /api/asdd/changes/{change_id}/autopilot` takes `{"enabled": bool}` and
  writes `autopilot` into `proposal.md`. It is a property of the change, not of
  a session, so any chat that opens the change afterwards inherits it. Turning
  it off also clears any `hold`;
- `POST /api/asdd/changes/{change_id}/actions/{action}` returns the prompt and
  Skill that carry out one phase. It says nothing about where the work runs: the
  client sends the prompt to whichever Coding chat is open. With autopilot on,
  `action = autopilot_continue` resolves to whichever phase follows the gate the
  change is standing at, and the prompt carries the autopilot protocol — write
  `auto_approvals`, never `approvals`, and raise a `hold` instead of guessing;
- `POST /api/asdd/changes/{change_id}/ready` and `/archive` mark a verified
  change ready and fold its deltas into `specs/<capability>/spec.md`, moving the
  folder to `changes/archive/YYYY-MM-DD-<change-id>/`. Both re-check every gate;
- `POST /api/asdd/changes/{change_id}/evidence` appends one evidence page;
- `DELETE /api/asdd/changes/{change_id}` removes an unarchived change folder;
- `GET /api/asdd/specs` and `/api/asdd/specs/{capability}` read the capability
  catalogue, parsed into requirements and scenarios.

There is no ASDD stream endpoint. Agents change a catalogue by writing files, so
no request reaches the server to broadcast; clients poll `GET /api/asdd/changes`
and `GET /api/asdd/changes/{change_id}` while a panel is open.

See [Agent Spec-Driven architecture](../architecture/agent-specs.md) for the storage,
trust and concurrency rules, and
[ASDD methodology](asdd-methodology.md) for the normative lifecycle.

## Asynchronous chat contract

Chat/command endpoints normally return `202 Accepted` after validation and
queueing. Subscribe to `GET /api/team/{session_id}/stream` for live output and
load history for reconnect. Side Chat and browser-panel chat have separate
stream endpoints.

The SSE `data` payload is a structured envelope. Event types include content
deltas, tool/activity blocks, member status, permissions, plan review,
questions, queues, usage, goal/workflow updates, errors and completion. Clients
must tolerate additional event fields/types and reconnect using durable history
rather than assuming one uninterrupted socket.

## WebSockets

| Path | Purpose |
|---|---|
| `/api/team/{session_id}/terminal` | bidirectional PTY input/output/resize |
| `/api/team/{session_id}/browser/agent` | direct browser agent commands |
| `/api/team/{session_id}/browser/presence` | visible browser mount/presence |
| `/api/team/webbridge/relay` | extension relay |
| `/api/team/webbridge/agent/{session_id}` | external browser-agent relay |

WebSocket authentication is validated at the endpoint because HTTP middleware
does not wrap the upgraded channel. Protocols are versioned where the desktop
or extension advertises capabilities.

## Error and pagination conventions

Validation errors use FastAPI/Pydantic `422`; missing resources use `404`;
authorization/policy conflicts use `401`, `403` or `409`; database admission may
surface retryable `503 database_busy`. Long lists use explicit `limit`,
`offset` or cursor fields and include a next/has-next indicator.

Never depend on provider-specific raw payloads: Git reviews, model providers,
MCP and agent streams expose normalized EvoFlux schemas.
