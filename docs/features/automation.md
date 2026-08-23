# Goals, workflows, and scheduler

EvoFlux provides three complementary automation levels: a durable autonomous
Goal attached to one conversation, a structured approved Workflow graph, and a
time-based Scheduler that dispatches prompts to a target team.

## Durable Goal mode

`/goal <objective>` creates or replaces the session's durable objective. The
goal stores status, optional token budget, used tokens, active elapsed time,
pause reason, blocker fingerprint/streak, version and completion time.

Commands include status, budget, pause, resume and stop. After a normal turn,
the lead can continue through hidden internal turns until it completes the
goal, reaches a token budget, the user pauses/stops it, or the same concrete
blocker is reported on three consecutive goal turns. Optimistic versions
prevent concurrent controls from overwriting newer state.

Goal mode never expands the session's permission, sandbox, model or workspace
scope. Progress is persisted and streamed to the UI.

## Workflows

Workflow definitions are YAML files discovered from the active Coding
workspace's `.evoflux/workflows/` and the global config `workflows/` directory.
The schema defines name, Work/Coding scope, typed inputs, graph nodes/edges,
outputs and optional UI layout.

Implemented v1 node kinds:

| Kind | Behavior |
|---|---|
| `agent` | Inject a lead turn with an optional specialist set and capture structured output |
| `tool` | Invoke a native or MCP tool with rendered arguments |
| `gate` | Pause for a bounded human choice |
| `input` | Ask a bounded user question and continue with the answer |
| `switch` | Route on a rendered value |
| `transform` | Build output fields from templates |
| `notify` | Publish a visible notification/progress event |
| `foreach` | Execute one allowed body node over bounded items |

Reserved `workflow` and `wait` kinds validate so future files retain schema
compatibility, but the current runner refuses to execute them.

Definitions are validated against graph structure, live agent/tool names,
scope and destructive-tool lint. Approval is hash-bound: editing an approved
definition invalidates approval. Only an approved Workflow may execute direct
tool nodes without per-call prompts; its workspace sandbox and manifest are the
authorization boundary.

One live execution is allowed per session. Runtime state drives agent turn
boundaries and gates; database execution/node/gate rows provide durable audit
and restart reconciliation. A restart marks orphaned running/waiting executions
failed because in-memory continuations cannot be safely reconstructed.

## Scheduler

Scheduled tasks support:

- one-time `at` timestamps;
- fixed `every` intervals;
- five-field cron expressions;
- explicit IANA timezones;
- Work targets, Coding workspace targets, or compatible Coding projects;
- pause, resume, manual trigger, update and delete.

Each enabled task owns an asyncio sleeper until `next_fire_at`, then dispatches
its prompt to the matching team lead and records session/run/error status. A
Coding target is validated at create/update/fire time so deleted or hidden
projects do not receive work. Windows ships `tzdata` so browser-selected IANA
zones work in the sidecar.

Agents can manage tasks through the built-in `schedule` tool; users can use the
standalone Scheduler page or workbench panel.

## Source and tests

Primary code: goal model/service/hooks and `app/agent/mode/team/team.py`;
`app/workflow/`, workflow models/routes; `app/scheduler/`, scheduler routes and
Scheduler React surfaces.

Focused suites: `tests/agent/mode/team/test_goal_*`, goal service/hook tests,
`tests/workflow/`, `tests/api/routes/test_workflows.py`, `tests/scheduler/`, and
scheduler API/frontend tests.
