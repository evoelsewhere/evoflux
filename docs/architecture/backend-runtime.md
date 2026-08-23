# Backend runtime

The Python application is a FastAPI sidecar with an asynchronous agent runtime,
service layer, SQLModel persistence, and background integration managers. It is
both the desktop backend and the API-only distribution installed by the Python
wheel.

## Application assembly

`app/api/app.py` owns the process lifecycle and mounts every public router below
`/api`; Prometheus metrics remain at `/metrics`. Middleware order is deliberate:

1. request metrics wrap the complete response path;
2. request-size limits reject oversized input;
3. desktop/access-key authentication protects the local API when configured;
4. security headers apply inside CORS;
5. CORS handles development and configured origins.

The default FastAPI `/docs` and `/openapi.json` surfaces expose the exact HTTP
schema of the running build. See [HTTP API](../reference/http-api.md).

## Layering

| Layer | Rule |
|---|---|
| Routes | Validate transport input, resolve dependencies, call durable logic, translate errors |
| Services | Own reusable business rules and filesystem/process integrations |
| Agent runtime | Own model calls, tools, context, team behavior and turn lifecycle |
| Models/migrations | Own persistent application state and compatibility |
| Core | Own process-wide configuration, database, auth, paths and telemetry |

Routes should not hold database transactions while scanning files, running Git,
calling models, waiting for SSE, or starting processes. The database layer uses
separate read and single-writer lanes; the complete rule is in
[SQLite concurrency](sqlite-concurrency.md).

## Agent construction and turns

Agent Markdown frontmatter is parsed by `app/agent/loader.py`. Code-owned mode
profiles supply base prompts and tools; user frontmatter adds model, reasoning,
skills, tools, permissions and opt-outs. Effective configuration is compiled
without rewriting the user's agent files. Agents detect tracked config drift at
the next turn rather than forcing an in-flight team reload.

One `Agent.run()` iteration does the following:

1. hooks project context, workspace instructions, selected Skills, memory and
   other bounded context into the request;
2. a provider adapter streams text, reasoning, usage and tool calls;
3. tool calls are partitioned into safe concurrent or serial waves;
4. the permission and sandbox layers authorize execution;
5. tool results are bounded/offloaded and appended as observations;
6. the loop continues until a final response, interruption, recoverable pause,
   or terminal error;
7. completion hooks persist usage, extract memory, publish events and maintain
   goal/workflow state.

The core loop caps concurrent tools at ten, supports provider retries/fallbacks,
and uses evidence-budget checkpoints instead of treating a small global
iteration count as task correctness.

## Team lifecycle

`app/services/team_manager.py` lazily builds the Work team and Coding teams.
Coding identity is scoped to the authorized repository/project/session. Idle
teams are opportunistically evicted; specialists are blueprints rather than
always-running processes.

`app/agent/mode/team/` provides:

- on-demand specialist instances with stable `blueprint#N` handles;
- one mailbox per team and activation only when messages arrive;
- delegation ledger and durable `DelegationTask` rows;
- handoff, reject/rework, shared team state, todo and worktree tools;
- unified lead/member streaming into the parent session;
- continuation for queued input, Goal mode and workflow turn boundaries.

Session teardown increments a lifecycle epoch before eviction so a concurrent
cold build cannot publish a deleted team.

## Streaming and persistence

Chat ingress returns `202` after validation and queueing. The live result uses
Server-Sent Events from the in-memory stream store. The stream envelope carries
message deltas and structured lifecycle events; the database stores the
canonical session/message history for reconnect and pagination.

WebSockets are reserved for bidirectional terminal, direct browser and
WebBridge relay channels. Files and media use bounded HTTP endpoints rather than
being embedded in transcript JSON.

## Background services

| Service | Lifecycle |
|---|---|
| Scheduler | Starts only when enabled tasks exist; wakes teams at the next fire time |
| Dream | Optional cron/manual wiki consolidation |
| MCP manager | Watches global `mcp.json` and reconciles servers |
| Plugin MCP runtime | Reconciles enabled installation-scoped servers separately |
| Conductor | Optional enrollment, heartbeat, resource sync and telemetry delivery |
| WebBridge cleanup | Expires sessions, artifacts and relay state |
| OTEL retention | Rolls and prunes local observability partitions |
| Code-index workers | Spawned on demand and shut down when idle |

Failures in optional startup services are logged and surfaced through status or
diagnostics without making the critical loopback API unavailable.

## Verification anchors

- `tests/agent/` covers loop, hooks, teams, tools, providers and policy.
- `tests/api/` covers route contracts, auth, streaming and WebSockets.
- `tests/services/` covers durable business rules and integrations.
- `tests/core/` covers database, migrations, middleware, paths and metrics.
- `tests/workflow/` and `tests/scheduler/` cover automation engines.
