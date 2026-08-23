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
| `/api/observability` | aggregates, trace pages and trace detail | `observability.py` |
| `/api/commands` | slash-command catalogue/rendering | `commands.py` |
| `/api/snippets` | snippet catalogue/rendering | `snippets.py` |
| `/api/auth` | provider OAuth login/callback | `auth.py` |
| `/api/quote` | cached quote-of-the-day | `quote.py` |

## Team subresources

The `/api/team` router includes:

- accepted chat/command ingress and per-session SSE;
- session CRUD, history, metadata, duplicate, queue, goal and todos;
- Work folders and shared-folder context;
- workspace files/uploads/media/previews and file-watch SSE;
- Coding projects, workspace authorization/tree/files and worktrees;
- Git, Git AI, code reviews and Git server connections;
- ChangeSets, editor actions/context, LSP/language-server and Problems;
- code-index status/index/query/graph per Coding project;
- terminal and direct-browser WebSockets;
- Side Chat messages and stream.

Use the OpenAPI document rather than copying request/response field definitions
from this overview.

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
