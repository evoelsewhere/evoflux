# EvoFlux Workflows — Design & Implementation Plan

> Status: PROPOSED (v2 — revised after 3-lens adversarial review: correctness, completeness, enterprise/security)
> Date: 2026-07-08
> Scope: User-authored deterministic workflows for both `forge` (normal) and `coding` modes
> Companion: `documents/analysis/claude-code-vs-evoflux.md`

---

## 1. Executive summary

Today, multi-step work in EvoFlux is decomposed by the **lead LLM at its own discretion** (via `team_delegate`). Users cannot define a repeatable, system-enforced pipeline such as *"receive ticket → pull Jira → fan out analysis agents → synthesize → human approval → fix"*. Skills describe processes but cannot enforce them; commands expand to a single message; `/loop` repeats one fixed prompt; the scheduler fires prompts on a timer but is completion-blind.

This plan introduces **Workflows**: file-based, user-authored pipeline definitions executed by a deterministic engine, where **control flow lives in code and intelligence lives inside each step**. Every run is a first-class `ChatSession`, so streaming, history, sidebar, and notifications work unchanged.

Design maxim: **determinism at the orchestration layer, agency inside the step.**

### Goals

- Users author workflows as YAML files (editable via UI or by agents themselves) scoped globally or per-workspace.
- Steps: deterministic tool calls (incl. MCP, e.g. Jira), single-agent runs with typed outputs, parallel fan-outs, human approval gates, and conditionals.
- Runs are durable: survive process restart and team eviction, with a step-level audit trail whose source of truth is the DB (never in-memory state).
- Triggers: manual (UI/slash), scheduler (cron), inbound webhook (enterprise), agent-initiated (lead tool) — all gated by a server-enforced trust model from day one.
- Full integration with every existing subsystem (§8 matrix).

### Non-goals (this iteration)

- Visual drag-and-drop DAG editor (Phase 4; the YAML schema is designed so a canvas can be layered on later).
- Cross-machine distributed execution (the SSE store and team caches are single-process by design — `app/services/memory_stream_store.py:1-10`; we stay within that model).
- A general-purpose scripting language in definitions (no user JS/Python in YAML; the escape hatch is a `tool` step calling a plugin-registered function).
- Multi-tenant RBAC. EvoFlux is a single-user desktop product gated by the desktop-token middleware (`app/api/app.py:150`). "Enterprise-ready" here means durability, auditability, security hardening, cost control, and operational tooling — not user management.
- Exactly-once side effects. Steps have **at-least-once** semantics on crash recovery (§6.5); the design mitigates but cannot eliminate this, and says so honestly.

---

## 2. Current-state findings that shape the design

Verified against the codebase (file:line); these are the load-bearing constraints:

| # | Finding | Consequence for design |
|---|---|---|
| F1 | The team turn-completion barrier `_try_emit_done` (`app/agent/mode/team/team.py:455-486`) runs after **every** agent activation and dispatches a priority chain: queued user messages → `/loop` iteration → DoneEvent. | The workflow engine plugs in as a new branch in this chain — **after queued messages, before the `/loop` branch** (run sessions reject `/loop`, so the branch order is unambiguous). Output capture for the just-finished step runs unconditionally **before** yielding to queued messages (§6.2). |
| F2 | `_activate_loop_message` (`team.py:621-689`) is a working template for injecting a synthetic user turn: `init_turn(keep_subscribers=True)` → persist `HumanMessage` → status SSE → `queued_turn_start` SSE → `mailbox.send`. | Step activation copies this sequence with a computed prompt. `keep_subscribers=True` keeps one continuous SSE stream across steps. |
| F3 | `/loop` state is in-memory only and dies on restart **and** on 30-minute idle team eviction (`team.py:301-302`, `app/services/team_manager.py:93-96,120`). It treats agent `error` state as completion and re-fires blindly (`team.py:463-465`), and decrements budget before the iteration is guaranteed to start (`team.py:626` vs `630-649`). | Workflow run state is DB-persisted with startup rehydration (scheduler pattern), and must NOT inherit these warts: explicit failure branches, mark-running-before-advance, rehydrate-on-resurrection. |
| F4 | The scheduler is the persistence blueprint: DB row status machine, overdue-fire-on-startup (`app/scheduler/scheduler.py:123-155`), deterministic session via `uuid5` (`scheduler.py:517`), post-hoc `ChatSession.scheduled_task_name` stamping used by the sidebar (`scheduler.py:576-592`). | `WorkflowRun` mirrors `ScheduledTask` lifecycle. Runs stamp `chat_sessions.workflow_run_id` (plain indexed column, no FK — see F13). |
| F5 | `Agent.run()` is directly callable without a team — proven by the dream service (`app/services/dream.py:1454-1460`) — with per-run tools, model override, `interrupt_event`, hooks, and contextvar-scoped services wired as `member.py:1077-1139` demonstrates. Caveats: `max_iterations` is a constructor attribute, not a `run()` parameter (`core.py:312`); the loop exits only on no-tool-calls / `<sleep>` / interrupt. | Phase 2 `agent`/`fanout` steps run members directly via `Agent.run()` + `asyncio.gather`. Per-step `max_iterations` is set on the freshly materialized agent object (direct execution only; rejected at validation time for lead-driven steps). Step termination uses a **per-step-attempt** event, never the run-level cancel event (§6.3). |
| F6 | There is **no forced structured output**: no `tool_choice`/`response_format` anywhere; provider request builders whitelist fields (`app/agent/providers/openai/completions.py:192-225`). The proven mechanism is pydantic-validated tool arguments with error-round-trip retry (`app/agent/tools/registry.py:229-235`), exemplified by `HandoffArtifact` + its server-side quality gate (`app/agent/mode/team/handoff.py:59-292`). | Step output contracts = a per-step `submit_result` tool generated from `output_schema`, validate-retry bounded. **Phase 2 only** — there is no per-turn tool-injection channel into lead-driven runs today (`member.py:1053` hardcodes `get_injected_tools`; `team.py:1704-1731` is workflow-unaware), so Phase 1 captures handoff artifacts / final text instead (§6.2). |
| F7 | Human gates exist as SSE event + `asyncio.Future` + HTTP reply endpoint, interrupt-safe: `ask_user` (`app/agent/ask_user.py:66-118`) and plan approval (`app/agent/plan.py:97-156`). Pending futures are in-memory only. | `gate` steps get a `WorkflowGateService` with the same Future pattern **plus a DB row from Phase 1** (park/expiry must survive restart — the flagship exemplar contains a gate, so gate durability cannot be deferred). |
| F8 | MCP tools are programmatically callable without an LLM: `mcp_manager.call_app_tool(server, tool, args)` returns structured `CallToolResult` (`app/agent/mcp/manager.py:391-412`); OAuth for remote servers is supported. There is **no inbound webhook surface** in `app/`. | `tool` steps call `call_app_tool` (structured; not the text-flattening `MCPTool._invoke`). The webhook trigger is net-new and gets its own hardening (§7.1). MCP has **no idempotency concept** — `call_app_tool` forwards arguments verbatim — so retry safety is a policy problem (§6.5), not a parameter. |
| F9 | Permission approval is enforced in a `wrap_tool_call` hook (`app/agent/hooks/stream_publisher.py:201-264`), not in the executor — direct calls bypass user approval. Permission mode is a mutable per-session field (`PATCH /sessions/{id}/permission-mode`, `chat.py:993`). | Explicit execution-policy layer (§7.3), server-enforced from Phase 1. The PATCH endpoint is guarded on run sessions. |
| F10 | Mode plumbing: coding sessions are workspace-pinned (409 on mismatch, `chat.py:220-233`); coding teams cached per `(workspace, session_id)`; projects fan `extra_workspace_paths` in (`chat.py:236-247`); **normal sessions may opt into a custom workspace** (`PUT /team/{sid}/workspace`, `app/api/routes/team/files.py:226-262`) without becoming coding sessions. | `mode` binding follows the scheduler contract (`app/scheduler/schemas.py:50-53`), except: normal-mode runs MAY carry an optional `workspace` binding mirroring the existing session opt-in (stamped on the run session the same way). |
| F11 | File-based user-content stack (frontmatter parse, multi-root precedence discovery, mtime-cache, atomic CRUD, builtin read-only guard, settings UI) exists three times: skills, commands, snippets. Workspace roots take precedence and **shadow global names** (`app/agent/tools/builtin/skill.py:48-72`). | Workflow definitions are the fourth instantiation — but name-shadowing from a cloned repo is an attack vector, so the trust model (§7.3) shows provenance and gates workspace-root definitions server-side from Phase 1. |
| F12 | The custom-SSE-event recipe is proven by `loop_status` — but its history hydration reads **live team state** and returns nothing when the team is evicted (`chat.py:1103`, "a cache miss is simply no loop" `chat.py:1068`). | `workflow_status` follows the push recipe, but **hydration is DB-derived** (runs/steps/gates rows), never from live runner/team objects. The run API is the source of truth the UI rehydrates from after restart/eviction. |
| F13 | SQLite connections never enable `PRAGMA foreign_keys` (`app/core/db.py:56-71`) — FKs are declared but unenforced. The lead always gets `QueuedMessageInjectionHook`, which splices queued user messages **into the currently running turn** (`member.py:957-965`, `hooks/queued_injection.py:36-108`), and `_try_activate_queued_after_lead_turn` (`team.py:542-567`) activates queued messages while members are still busy. `TitleGenerationHook` fires on any first turn, with only a `[Scheduled Task:` prefix skip (`app/agent/hooks/title_generation.py:133-141`). | Schema avoids circular FKs (§5). Run sessions **suppress** mid-turn queued injection and early queued activation so user input lands at step boundaries, keeping step outputs uncontaminated (§6.1). Title hook gets a `workflow_run_id` skip (run titles are set at creation). |

---

## 3. Concepts and terminology

| Term | Definition |
|---|---|
| **WorkflowDefinition** | A YAML file describing inputs, triggers, defaults, and an ordered step graph. Identified by `name` per discovery root; identified for execution by **content hash**. |
| **WorkflowRun** | One execution of a definition snapshot. DB-persisted. Owns exactly one run `ChatSession`. |
| **Step** | A node: `kind ∈ {tool, agent, fanout, gate, switch}`, with `retry`/`timeout_s`/`on_error`, producing a JSON output persisted per attempt. |
| **StepRun** | DB record of one step attempt (status, timestamps, rendered-prompt hash, output, error, usage). The audit trail. |
| **Gate** | Human-in-the-loop step. Parks the run; DB-backed; survives restart; expires per policy. |
| **Trigger** | `manual`, `slash`, `schedule`, `webhook`, `agent` (lead tool). |
| **Binding** | Execution context: `mode` (+ `workspace`/`project_id`; optional workspace for normal per F10), optional `isolation: worktree`. |
| **Capability manifest** | The statically resolved set of tools, MCP servers, skills, agents, env references, and destructive-tool presence for a definition hash. What the user approves. |

---

## 4. Workflow definition format

### 4.1 Storage and discovery

Fourth instantiation of the user-content pattern (F11). Discovery roots, precedence order:

1. `{workspace}/.EvoFlux/workflows/` — per-repo, travels with git. **Untrusted until approved** (§7.3): shadowing a global name never executes without a fresh per-hash approval that displays provenance.
2. `{EVOFLUX_CONFIG_DIR}/workflows/` — global (`settings.WORKFLOWS_DIR`).
3. `app/agent/builtin_workflows/` — bundled read-only examples (`bug-triage`, `pr-review`, `weekly-report`).

Implementation: `app/services/workflows_fs.py` cloning `app/services/commands.py:66-296`; `ensure_workspace_initialized` creates the global root.

### 4.2 Schema (v1)

```yaml
# .EvoFlux/workflows/bug-triage.yaml
schema_version: 1
name: bug-triage
description: Triage a Jira bug end-to-end and open a fix PR
mode: coding                    # normal | coding. Normal MAY add an optional
                                # workspace binding at trigger time (F10).
isolation: none                 # none | worktree (coding only)

inputs:
  - name: ticket_id
    type: string                # string | number | boolean | enum. File/attachment
    required: true              # inputs are NOT supported in v1 (§8 Attachments row).

triggers:
  manual: true
  slash: true
  schedule: false
  webhook:
    enabled: true
    secret: ${JIRA_WEBHOOK_SECRET}   # MANDATORY when enabled (validation error
                                     # otherwise); resolved via the existing
                                     # ${VAR}/.env mechanism (mcp/config.py:94-114)
    bind:
      ticket_id: issue.key

defaults:
  model: null                   # validated against the model registry at save time
  thinking_level: null          # per-step override below; null → session default
  fast: false                   # service-tier fast mode where the provider supports it
  permission_mode: auto         # ask | accept-edits | plan | auto. `bypass` is
                                # FORBIDDEN in definitions (§7.3).
  step_timeout_s: 900
  max_run_duration_s: 7200
  max_tokens: 2000000           # hard run budget; checked at step boundaries (§7.4)

steps:
  - id: fetch
    kind: tool
    tool: mcp_jira_get_issue
    args: { key: "{{inputs.ticket_id}}" }
    retry: { attempts: 3, backoff_s: 5 }
    on_error: fail              # fail | continue | goto:<forward_step_id>

  - id: analyze
    kind: fanout
    items: [explorer, debate]   # static lists only for agent selection; templated
    as: agent_name              # item lists are allowed only when the inner step
    step:                       # declares an explicit tools: allowlist (§7.3)
      kind: agent
      agent: "{{agent_name}}"
      prompt: |
        Analyze this bug from your specialty.
        Ticket: {{steps.fetch.output.summary}}
        Description: {{steps.fetch.output.description}}
      output_schema:            # Phase 2+: submit_result tool (F6). Phase 1
        type: object            # validates but does not enforce; capture falls
        required: [root_cause_hypotheses, affected_files, confidence]
        properties:
          root_cause_hypotheses: { type: array, items: { type: string } }
          affected_files: { type: array, items: { type: string } }
          confidence: { type: number, minimum: 0, maximum: 1 }
      tools: [code_search, code_overview, read, grep]
      thinking_level: high
      max_iterations: 40        # direct execution only (Phase 2+); validation
                                # rejects it on lead-driven steps (F5 caveat)
    join: all                   # all | any | first_success
    concurrency: 4

  - id: synthesize
    kind: agent
    agent: architect
    prompt: |
      Synthesize the analyses into one root-cause verdict and fix plan.
      Analyses: {{steps.analyze.outputs | json}}
    output_schema:
      type: object
      required: [verdict, fix_plan]
      properties:
        verdict: { type: string }
        fix_plan: { type: array, items: { type: string } }

  - id: approve
    kind: gate
    title: "Approve fix plan for {{inputs.ticket_id}}"
    body: "{{steps.synthesize.output.verdict}}"
    choices:
      - { label: approve, action: continue }
      - { label: reject,  action: fail }      # continue | fail | goto:<step_id>
    timeout_s: 86400
    on_timeout: fail            # gates guarding destructive steps MUST fail on
                                # timeout — enforced statically (§7.3)

  - id: fix
    kind: agent
    agent: coder
    prompt: |
      Implement the approved fix plan. Verify with tests before finishing.
      Plan: {{steps.synthesize.output.fix_plan | json}}
    tools: [read, grep, edit, write, patch, shell, python, code_search]
    retry: { attempts: 1, on_interrupted: park }   # park (default for destructive
                                                   # steps) | retry (§6.5)

outputs:
  verdict: "{{steps.synthesize.output.verdict}}"
  fixed: "{{steps.fix.output}}"
```

### 4.3 Templating

- Mustache-style `{{ ... }}` over `inputs`, `steps.<id>.output(s)`, `run`, and `env` (globally allowlisted names only — the allowlist lives in **settings**, never in the definition). Filters: `json`, `truncate:N`. No arbitrary expressions.
- Rendered step-by-step at activation time. The rendered prompt's hash is persisted on the `StepRun`; the full rendered text spills to the run's artifact dir (§5) for audit.
- `env.*` interpolation is refused: (a) into anything persisted as step output, and (b) into `tool` step args targeting remote (HTTP) MCP servers, unless the specific reference was part of the approved capability manifest (§7.3) — closing the secret-exfiltration channel.
- Implementation: `app/workflow/template.py` (~120 lines; generalizes the `$ARGUMENTS` discipline of `commands.py:299-312` to dotted paths).

### 4.4 Validation (save time)

Pydantic models in `app/api/schemas/workflows.py`:

- Cross-field rules per the scheduler contract (F10) + normal-mode optional workspace; `isolation: worktree` requires coding; unique step ids; `goto:` forward-only.
- `output_schema` validated as JSON Schema; converted at run time via `create_model` (registry machinery, `registry.py:273-334`).
- `model`/`defaults.model` names validated against the model registry; unknown → save-time error. Run-time provider-unconfigured failures name the provider (mirroring MCP `auth_required` treatment).
- `permission_mode: bypass` rejected. `max_iterations` rejected on lead-driven steps.
- **Path-sensitive destructive-gate analysis** (§7.3): every path from entry to a step whose tool allowlist intersects the destructive set (`{edit, write, patch, rm, shell, python, bg}` — the plan-mode intercept list, `tool_executor.py:39-41`) must pass through a `gate` whose `on_timeout` is `fail` and which cannot be bypassed via `goto`/`on_error: continue`. Required for `webhook`/`schedule`/`agent` triggers; warning-only for `manual`/`slash`.
- Templated `agent:`/`tool:` names are rejected in definitions with unattended triggers (webhook/schedule); fanout inner steps must declare explicit `tools:`.
- Definition **content hash** computed at save; the capability manifest (§7.3) is resolved and stored alongside.

---

## 5. Data model and migrations

New alembic revision `000000XX_create_workflows.py`. Note: FKs below are declarative only — SQLite FK enforcement is off (F13); integrity is maintained by the service layer, matching the existing codebase posture.

```
workflow_runs
  id               UUID PK (uuid7)
  definition_name  str, indexed
  definition_hash  str, indexed
  definition_snapshot JSON       -- full parsed definition at trigger time
  session_id       UUID NULL, unique, indexed   -- set right after the run session
                                                -- is created (creation order: run row
                                                -- → session row → backfill session_id;
                                                -- no circular FK)
  mode / workspace / project_id
  trigger          str           -- manual|slash|schedule|webhook|agent
  trigger_meta     JSON          -- webhook delivery id, scheduler task id, raw-payload
                                 -- artifact pointer (§7.2)
  inputs           JSON
  status           str           -- pending|running|waiting_gate|paused|interrupted|
                                 -- completed|failed|cancelled|budget_exceeded
  current_step_id  str NULL
  outputs / error  JSON/str NULL
  usage_totals     JSON NULL     -- aggregated tokens/cost across steps
  control_log      JSON          -- append-only [{ts, action, actor, detail}] for
                                 -- pause/resume/cancel/force-fail/permission-override
  created_at / started_at / ended_at

workflow_step_runs
  id / run_id (indexed) / step_id / fanout_index / attempt
  status           str           -- running|succeeded|failed|skipped|cancelled|
                                 -- waiting|interrupted
  agent_name       str NULL
  member_session_id UUID NULL    -- child ChatSession for direct runs (Phase 2)
  prompt_hash      str NULL      -- rendered prompt hash; full text in artifact spill
  turn_span        JSON NULL     -- {first_message_id, last_message_id} of the step's
                                 -- own turn — output capture resolves ONLY within
                                 -- this span (§6.2)
  output / error / usage JSON NULL
  started_at / ended_at

workflow_gates
  id (request_id) / run_id / step_id
  title / body / choices JSON
  status           str           -- pending|replied|expired|cancelled
  reply            JSON NULL     -- {choice, comment, replied_at}
  expires_at       datetime NULL
  created_at / replied_at

workflow_definition_approvals
  definition_hash  str PK
  name / root      str           -- provenance: which discovery root & path
  manifest         JSON          -- capability manifest as approved
  approved_at      datetime

workflow_webhook_deliveries
  delivery_key     str PK        -- provider delivery id or body hash
  definition_name  str, received_at datetime
  -- swept by the retention task (§7.4)
```

Plus `chat_sessions.workflow_run_id UUID NULL` — **plain indexed column, no FK** (the `scheduled_task_name` precedent). Member sub-sessions use `parent_session_id` = run session, as team members do today.

Large values: step outputs capped (default 256 KB); oversized outputs, rendered prompts, and raw webhook payloads spill to `session_artifact_dir(run_session_id)/workflow/…` (`app/agent/artifacts.py:17-28`) with DB pointers — consistent with "artifacts under XDG data, never in the coding workspace".

---

## 6. Execution engine

New package `app/workflow/` (`models`, `registry`, `runner`, `steps`, `template`, `gates`, `triggers`, `policy`).

### 6.1 Runner lifecycle (Phase 1 — lead-driven steps)

1. **Trigger** → `runner.start(...)`:
   - Enforce trust: definition hash must be approved for its provenance (§7.3) — server-side, on every trigger path including slash/scheduler/agent.
   - Validate binding like the scheduler (`scheduler.py:40-55`); project → `extra_workspace_paths` (`coding_project_service.py:223-227`); `isolation: worktree` → create via the worktree route's service path (`worktrees.py:292-359`).
   - Insert `workflow_runs` (pending) → create the run `ChatSession` (title `"{name} · run #N"`, `workflow_run_id` stamped) → backfill `session_id`. Enforce concurrency caps (§7.4): over-cap runs stay `pending` in a bounded FIFO.
   - Boot the team as the scheduler does: `get_or_start_coding_team(workspace, f"workflow:{run.id}", ...)` or `get_or_start_team()`.
2. **Step advancement** — one new branch in `_try_emit_done`, placed **after** `_activate_queued_user_messages` and **before** `_activate_loop_message` (consistently; `/loop` is rejected on run sessions):
   - The branch calls `WorkflowRunner.on_turn_complete(session_id)` which FIRST captures the just-finished step's output within its recorded `turn_span` (§6.2) and persists the `StepRun` — **before** any yield to queued user messages, so human steering can never be mis-captured as a step output.
   - It then checks the interrupt flag (§6.4): an interrupted turn marks the attempt `interrupted` and applies policy instead of advancing.
   - Then it advances: render next step, inject a synthetic turn via the F2 sequence, mark the new `StepRun` `running` **before** injection (F3 wart fixed); injection failure → attempt `failed` → `on_error`.
3. **Run-session turn discipline** (F13 fixes — new, explicit engine edits):
   - `QueuedMessageInjectionHook` is **not installed** on run sessions, and `_try_activate_queued_after_lead_turn` skips them: user messages posted mid-step queue normally and activate at the step boundary (after output capture), where they take priority over the next step. The run resumes after the user's turn. This preserves "human steering mid-run" with clean step outputs.
   - **Inline steps** (`tool`/`gate`/`switch`) don't use the team, but the runner keeps the session logically busy for their duration (sets/restores the team's active-turn flag) so `has_active_user_turn()` (`team.py:332-334`) stays truthful — a user message during a slow MCP call queues instead of colliding; step injection re-checks the flag and parks behind any active user turn.
4. **Completion**: render `outputs`, final `workflow_status`, DoneEvent, `desktop_notification` (mode-aware title branch, `team.py:512-519`), stamp `usage_totals`.

### 6.2 Step output capture

Every `StepRun` records its `turn_span` at injection; capture resolves **only within that span**:

- Phase 1 `agent` steps (lead-driven): (a) the final `team_handoff` artifact of the span, else (b) the lead's final assistant text. `output_schema`, if present, validates the parsed result and marks the attempt failed on mismatch (retry policy applies) — but cannot force schema-shaped output until Phase 2.
- Phase 2 direct steps: the `submit_result` tool call (pydantic-validated, error-round-trip retried, F6), injected via `Agent.run(injected_tools=…)` — a channel that exists for direct runs (F5) but not for lead-driven ones (F6 caveat).
- `tool` steps: the structured result (MCP `CallToolResult` content preserved).
- `fanout`: array of per-item outputs + statuses, joined per `join:`.

Step outputs are **DB-authoritative**: later steps template from the DB rows, never from lead context — so mid-run summarization/compaction can never corrupt data flow (§8 Compaction row).

### 6.3 Phase 2: direct member execution

`agent`/`fanout` steps gain `execution: direct` (default flips in Phase 3):

- Materialize the member via `rebuild_agent_from_disk(..., mode=team.mode)` (the spawn call, `team.py:1401-1408`); set `agent.max_iterations` on the instance; invoke `Agent.run()` with the F5 recipe (per-step tools, model, checkpointer on `member_session_id`, contextvar services from `member.py:1077-1139`).
- **Interrupt topology**: each step attempt (each fanout child) gets its own `asyncio.Event`. A small watcher task sets it when either (a) the child's `submit_result` is accepted (terminal-tool hook) or (b) the run-level cancel event fires. Sibling fanout children and subsequent steps are unaffected by one child's completion; "step finished" and "run cancelled" are never conflated.
- Fan-out = `asyncio.gather` bounded by `concurrency`; child sessions appear under the run session (`parent_session_id`) so member history endpoints and the monitor view work unchanged; streaming multiplexes onto the run session's stream key with the member label (`member.py:924-929` pattern).

### 6.4 Failure, interrupt, and cancel semantics

- Per step: `retry {attempts, backoff_s}` → `on_error: fail | continue | goto:<forward>`. `continue` yields `null` output; templates referencing it fail loudly unless guarded.
- **User interrupt** (the existing Stop button / `interrupt=true` on `/team/chat`, `team.py:756-763`): marks the current attempt `interrupted`, sets run status `interrupted` (a pause-like state), and the workflow branch refuses to advance past an interrupted turn. The interrupt's follow-up message (if any) runs as a normal user turn; the user then explicitly resumes, cancels, or force-fails the step via the run API/UI.
- **Cancel API**: sets the run-level cancel event (propagates into `Agent.run()` mid-stream) and finalizes status `cancelled`.
- Gate replies: per-choice `action: continue | fail | goto`. `on_timeout` fires via (a) an in-process timer while running and (b) a startup + periodic expiry sweep over `workflow_gates.expires_at` — so expiry works even across downtime.
- Watchdogs: `step_timeout_s` is enforced by a runner-side task per activation (interrupts the turn, marks attempt failed); `max_run_duration_s` and `max_tokens` (§7.4) checked at every boundary.

### 6.5 Durability and crash recovery — at-least-once, stated honestly

- All transitions are DB-first. On startup (next to scheduler startup, `app.py:91-94`) `runner.rehydrate()`:
  - `waiting_gate` → re-arm from the `workflow_gates` row (expired ones apply `on_timeout` immediately).
  - `running` → the in-flight attempt is marked `interrupted`. **Default policy: steps whose toolset intersects the destructive set PARK the run (`interrupted`) for explicit operator resume; non-destructive steps may auto-retry only if the step opts in (`retry.on_interrupted: retry`).** This is deliberately conservative: a crash after a side effect (PR opened, shell run) but before the output write means a retry re-executes it — MCP offers no idempotency mechanism (F8), so at-least-once is the truth and the docs say so.
  - Runs whose session row was deleted are marked `failed` and skipped.
- Team idle eviction stays as-is; rehydration + lazy team re-boot (F4 cache key `workflow:{run.id}`) handle resurrection. Gates parked for days hold no team in memory.
- **Run monitoring after restart** (F12): the run API and DB-derived `workflow_status` hydration are the UI's source of truth; the in-memory SSE store contributes only live deltas.

---

## 7. Enterprise readiness

### 7.1 Webhook trigger (net-new, hardened)

- `POST /api/webhooks/workflows/{name}` on a dedicated router:
  - **Secret is mandatory** whenever `webhook.enabled: true` (schema validation refuses otherwise). The route is exempt from desktop-token auth *only because* the HMAC is the auth — no secret, no exemption.
  - HMAC-SHA256 over the raw body, constant-time compare. **Honest replay posture**: GitHub-style signatures cover only the body (no timestamp/nonce), and Jira Cloud webhooks lack native signing — so for those providers the dedup table (`workflow_webhook_deliveries`, keyed by delivery id or body hash, retention-swept) is *redelivery hygiene, not replay defense*. Replay within the retention window is mitigated by run-level effects (dedup key includes body hash → identical replays collapse) and by the destructive-gate rule below. Custom senders SHOULD sign a timestamp+nonce envelope; the docs specify the recommended scheme.
  - Rate limit: token bucket per definition, default **6 runs/min** (run-creating endpoints deserve a conservative default), payload cap 256 KB, bounded pending-run queue (over-cap → 429).
  - Raw payload spilled to the run artifact dir for forensics (pointer in `trigger_meta`).
  - `bind:` failures on required inputs → 422, no run row.
  - Definitions with unattended triggers must pass the **path-sensitive destructive-gate analysis** (§4.4) — every path to a destructive step passes a human gate that fails on timeout and cannot be `goto`-bypassed.
- Deployment: localhost-first product; webhook use assumes a reverse proxy/tunnel that path-restricts exposure to `/api/webhooks/workflows/` only (documented).

### 7.2 Audit trail and observability

- `workflow_step_runs` + `workflow_runs.control_log` are the audit trail: per-attempt status/timestamps/prompt-hash/output/usage, plus every control action (pause/resume/cancel/force-fail/gate reply/permission override) with actor and timestamp.
- **Undo on run sessions is disabled** (409 with reason): checkpoint restores would delete the conversational evidence backing step outputs. (Worktree isolation is the sanctioned rollback for automated changes.)
- Per-step usage from existing `usage` events → `StepRun.usage`; run totals → `usage_totals`. Export bundle: `GET /api/workflows/runs/{id}/export` (run + steps + gates + control log + approval manifest + definition snapshot).
- Telemetry: counters/durations via the observability route. **Diagnostics** (`app/api/routes/diagnostics.py`) gains a workflows section: active runs, pending/expired gates, last rehydration result, invalid/unapproved definitions — the first place an operator looks.

### 7.3 Trust model and permission policy (server-enforced from Phase 1)

1. **Per-hash approval is a Phase 1 hard gate** on every trigger path (manual, slash, scheduler, agent tool, webhook). Saving or discovering a definition computes its **capability manifest**: resolved tools, MCP servers, skills (with their content hashes — workspace skills shadow global ones, F11, so the manifest pins what was reviewed), agent blueprints, env references, destructive-tool presence, webhook exposure. Approval (UI or pre-approval via config for headless installs) records `(hash, provenance, manifest)`. Any file edit → new hash → re-approval. The approval UI displays provenance (root + path) to defeat name-shadowing from cloned repos. This is backend enforcement — the CodingSidebar trust dialog is UI-only and is NOT relied on.
2. `permission_mode: bypass` is forbidden in definitions. Unapproved workspace-root definitions are inert (listed with an "approve to enable" state).
3. **Unattended runs never park on invisible futures**: for webhook/schedule/agent triggers with `permission_mode: ask`, permission requests auto-escalate to workflow gates (DB-backed, notifying, expiring) instead of in-memory permission futures.
4. `PATCH /sessions/{id}/permission-mode` on a run session is rejected while a run is non-terminal unless accompanied by an explicit override flag, which is recorded in `control_log` and voids the "runs as approved" property for that run (surfaced in the UI and export).
5. Tool allowlists are mechanical (`injected_tools`/`excluded_tools`), not prompt-level. `tool` steps may only name registry tools or ready `mcp_<server>_<tool>` names (`manager.py:368-381`).
6. Secrets: literal → `.env` + `${VAR}` conversion in the UI (MCP settings precedent, `routes/mcp.py:129-205`); template `env` allowlist lives in global settings; every env reference appears in the manifest; interpolation restrictions per §4.3.

### 7.4 Operational and cost controls

- Concurrency: `WORKFLOW_MAX_CONCURRENT_RUNS` (default 3), `WORKFLOW_MAX_CONCURRENT_STEPS_PER_RUN` (default 4), `WORKFLOW_MAX_FANOUT` (default 25), bounded pending FIFO.
- **Token budgets**: `defaults.max_tokens` per run (aggregated from usage events at step boundaries; exceeding → status `budget_exceeded`, notification); optional per-definition daily budget for unattended triggers; global `WORKFLOWS_ENABLED` kill switch.
- Pause/resume/cancel/re-run per run; `POST …/runs/{id}/steps/{step_id}/force-fail` admin action for stuck steps; staleness surfaced from `started_at` on the run API.
- Retention with **explicit cascade**: cleanup (default 90 days / last 200 per definition) deletes runs **and** their run-session trees (run session + member child sessions + messages), artifact spill dirs, gate rows, and dedup rows; `chat_sessions.workflow_run_id` consistency maintained by deleting sessions in the same transaction. `DELETE /api/team/sessions/{id}` on a session with a non-terminal run returns 409 (cancel first); terminal-run sessions delete normally and mark the run's `session_id` NULL (run rows remain as audit).
- Startup is fail-safe like MCP: a broken definition never blocks boot; it surfaces in diagnostics with triggers disabled.

### 7.5 Versioning and reproducibility

- `schema_version` with in-major backward compatibility; every run stores `definition_snapshot` + `definition_hash`; "re-run with same inputs" replays the snapshot (subject to current approval state). Builtin examples are read-only (builtin-skill guard precedent); "duplicate to edit" in the UI.

### 7.6 Operator runbook (shipped as docs with Phase 1)

Symptoms → diagnosis → action, e.g.: *run stuck `running`* → check diagnostics staleness + step `started_at` → `force-fail` step or `cancel` run; *run `interrupted` after crash* → inspect last attempt's spilled prompt/output → `resume` (retries per policy) or `cancel`; *gate never fired* → check `workflow_gates.expires_at` + notification log; *definition missing* → check approval state + validation errors in diagnostics.

---

## 8. Integration matrix — every existing feature

| Subsystem | Integration |
|---|---|
| **Forge (normal) mode** | `mode: normal` runs; **optional** workspace binding mirroring the session opt-in (F10) — stamped on the run session like `PUT /{sid}/workspace` does; without it, the per-session sandbox dir applies. Default team via `get_or_start_team()`. Sidebar badges runs (pattern of the `sched` badge, `Sidebar.tsx:989,1031-1035`). |
| **Coding mode** | Workspace-pinned run sessions (409 contract preserved); coding roster for `agent:`; code-graph tools per step allowlists; `CodingSidebar` groups runs under workspace/project focus with a "Runs" filter. |
| **Projects (multi-repo)** | `project_id` binding → primary repo + `extra_workspace_paths` (`chat.py:236-247`; direct runs get `MultiRepoContextHook`, `member.py:966-975`). Fanout over repo lists enables per-repo steps. |
| **Worktrees** | `isolation: worktree` per run (service path of `worktrees.py:292-359`), registered `kind='worktree'`; merge-or-discard is a final gate+tool pair. The sanctioned rollback for automated changes (undo is disabled on run sessions, §7.2). |
| **Scheduler** | Two-way: `ScheduledTask.workflow`/`workflow_inputs` → `_fire_task` calls `runner.start()`; workflow UI can create the task for `triggers.schedule: true`. Shared mode/workspace validation. |
| **`/loop`** | Untouched for interactive sessions; **rejected (422) on run sessions**. Workflow branch sits before the loop branch in `_try_emit_done` (§6.1). A `loop:` step kind supersedes it inside workflows (Phase 3). |
| **Slash commands** | `/workflow run|cancel|status` parsed server-side (`parse_slash_invocation`), gated by approval state; composer menu next to the `/loop` family. |
| **Queued messages** | Run sessions: no mid-turn splicing (hook suppressed, F13); messages land at step boundaries after output capture, taking priority over the next step (§6.1). Human steering with clean audit. |
| **Interrupt / Stop button** | Defined semantics (§6.4): current attempt `interrupted`, run pauses, no phantom advancement; follow-up message becomes a normal user turn. |
| **Attachments / @mentions** | **Not supported in v1** for workflow inputs/steps (typed scalar inputs only). Workaround: reference workspace file paths in prompts. `file` input type + mention expansion at activation time (reusing `collect_mention_attachments`, `chat.py:353-360`) is a Phase 3 item. Interactive user turns on run sessions keep full attachment support (they're normal turns). |
| **Shell dispatch (`!`/shell)** | Allowed on run sessions — it bypasses the turn machinery (`chat.py:309-333`) and doesn't touch the step barrier; noted in docs. |
| **Background tasks (`bg`)** | Hazard documented: bg processes outlive turns, so a step can "succeed" while its processes still mutate the workspace. Steps with `bg` in the allowlist get a boundary policy: `bg_wait: true` (default for steps followed by gates/worktree merges) waits-or-kills outstanding bg tasks before the attempt is marked succeeded. |
| **Skills** | Per-step `skills:` preload via `SkillPreloadHook` (`loader.py:570-575`); skill content hashes pinned in the capability manifest (§7.3). |
| **Commands** | Command bodies may contain `/workflow run …` (composition for free). |
| **Snippets** | Unaffected: composer-side insertion works on run sessions as anywhere; the `workflows/` root sits beside `snippets/` in workspace init. |
| **MCP** | `tool` steps via `call_app_tool` (structured, F8); per-step `mcp:` grants (merge pattern `loader.py:484-505`); readiness via `get_tools_for_server`/`wait_until_ready` with `auth_required` failing the step and naming the server. |
| **Permissions / plan mode / ask_user** | §7.3. Gate steps reuse ask_user UI; unattended `ask` escalates to DB-backed gates; permission-mode PATCH guarded on run sessions. |
| **Tier policy** | Step `tools:` allowlists are the workflow-native analogue; the same destructive-set constants drive the static gate analysis (§4.4). |
| **Memory / wiki / dream** | `WikiInjectionHook` unchanged (both modes, `member.py:945-948`). Memory extraction fires on run sessions as usual. **Dream**: orthogonal — run sessions are eligible for dream ingestion like any session; the runner's concurrency caps do not model dream's own load (documented; both are bounded independently). |
| **Code graph** | Coding-bound runs extend the watcher on trigger (as session resolve does, `chat.py:868-878`); `CodeOverviewHook` per its tool-presence rule. |
| **Compaction / summarization** | Step outputs are DB-authoritative (§6.2), so auto-summarization mid-run cannot corrupt data flow. `compact`/`continue` commands: allowed between steps, 409 mid-step. Optional `compact_between_steps: true` for long pipelines. |
| **Undo/redo** | **Disabled on run sessions** (409; §7.2). Snapshots still record (harmless); worktree isolation is the rollback story. |
| **Chapters** | Runner writes a `SessionChapter` per step (`chapter.py:14-37` write path) → `TaskProgressPill` shows step progress free; the run monitor is the richer view. |
| **Title generation** | Titles set at creation (`"{name} · run #N"`); `TitleGenerationHook` gains a `workflow_run_id` skip (F13) — file listed in §13. |
| **Thinking levels / fast mode** | Per-step `thinking_level` and `fast` fields (§4.2) carried through injection extras (Phase 1 — the same per-message extras user turns use, `team.py:874-947`) and `RunConfig` for direct runs (Phase 2). |
| **Model registry / providers** | Save-time model validation (§4.4); run-time provider-unconfigured errors name the provider. |
| **Browser automation** | Direct steps key `BrowserSession` state by `member_session_id` (the tool's existing per-session keying); the run timeline links to the existing BrowserViewer/screencast for that session. Run cancel/eviction/rehydration closes live browser sessions for the run's session tree (cleanup registered with the runner). |
| **Session deletion** | 409 on sessions with non-terminal runs; retention cascades (§7.4); rehydration marks session-less runs failed. |
| **Desktop notifications** | Completion/failure/gate-waiting/budget-exceeded push `desktop_notification` (existing pipeline); gate notifications deep-link to the run. |
| **Sidebar / session lists** | `workflow_run_id` badges in both sidebars (FK column beats the `[Scheduled Task:` title-prefix hack); "Runs" filter in CodingSidebar. |
| **Stream/SSE** | `workflow_status` pushed on every transition (F12 push recipe); **hydration from DB rows** via the run API (F12 caveat) — the monitor is correct after restart/eviction. |
| **Plugins** | Tool hooks fire inside steps as everywhere; new `workflow.step.before/after` plugin events (`plugins/events.py`) for org guardrails. |
| **Agents CRUD / drift** | Blueprint references validated at save (roster listed on error); drift refresh applies at step boundaries for direct runs. |
| **Diagnostics / health** | Workflows section in diagnostics (§7.2): active runs, stuck-step staleness, pending gates, rehydration result, invalid/unapproved definitions. |
| **Telemetry UI** | Run/step metrics on `/telemetry`. |
| **Desktop (Tauri)** | Tray label precedence gains `Workflow: <name> (step 3/5)` (`TeamChatView/index.tsx:659-670` pattern); tray menu item opens `/workflows`. |
| **Mobile** | Gate reply banner, `WorkflowStatusPill`, and run status list are mobile-capable (reuse existing `isMobile` branches); the YAML/form editor is desktop-only with a mobile fallback of read-only list + manual trigger. |

---

## 9. API surface

`/api/workflows` (new router):

```
GET    /api/workflows                          # definitions + validation + approval state + manifest
GET    /api/workflows/{name}                   # detail (raw YAML + parsed + provenance)
PUT    /api/workflows/{name}                   # create/update (global root; ?workspace= for repo root)
DELETE /api/workflows/{name}
POST   /api/workflows/{name}/approve           # approve current hash (manifest ack)

POST   /api/workflows/{name}/runs              # trigger {inputs, workspace?, project_id?, isolation?}
GET    /api/workflows/runs?definition=&status=&cursor=
GET    /api/workflows/runs/{id}                # run + step runs + gates + control log
POST   /api/workflows/runs/{id}/cancel | /pause | /resume | /rerun
POST   /api/workflows/runs/{id}/steps/{step_id}/force-fail
GET    /api/workflows/runs/{id}/export

POST   /api/workflows/gates/{gate_id}/reply    # {choice, comment?}
POST   /api/webhooks/workflows/{name}          # §7.1, separate router/hardening
```

Lead tool `workflow_run` (lead-only, injected like `schedule_task`, `loader.py:452-459`) with `_mode`/`_workspace` InjectedArgs — same anti-cross-scope contract as `schedule.py:243-249`; can only trigger **approved** definitions in its own scope.

---

## 10. Frontend plan

| Piece | Approach |
|---|---|
| **Workflows screen** | Top-level route `/workflows` (precedent `/scheduler`, `router.ts:72-76`). List + editor cloned from `settings.skills.tsx`; form view (step cards) + Monaco YAML view; zod schema per `settings/schema.ts` style; agent/tool/MCP pickers from `AgentForm.tsx` MultiSelect. Capability manifest + approve flow on save; provenance shown for workspace-root definitions. Desktop-only editor; mobile gets read-only list + trigger. |
| **Run monitor** | `WorkflowStatusPill` (clone `LoopStatusPill`); step timeline panel (new `CodingWorkspacePanel` tab for coding; right panel in forge) rendering from the run API + live `workflow_status` deltas — DB hydration first, SSE second (F12). Sub-agent rows link to the agent monitor and BrowserViewer where applicable. |
| **Gate UI** | Reuse ask_user question components; `GateBanner` on the run session; desktop notification deep-link; mobile-capable. |
| **Store/SSE** | `workflow_status` reducer case; `activeWorkflowRun` store field; hydration from `GET /runs/{id}` on session load; `workflow_runs` cache-invalidation kind + bridge mapping. |
| **Sidebar / composer** | Badges + Runs filter; `/workflow` slash family with approval-state gating and disabled-reasons. |
| **Queries** | `useWorkflowsQuery`, `useWorkflowRunsQuery` (cursor pagination per `useSessionsQuery.ts`), `useWorkflowRunQuery` with SSE-driven invalidation. |

---

## 11. Phasing and milestones

### Phase 1 — Deterministic sequencing, lead-driven steps (MVP)

Backend: `workflows_fs` + registry + validation (incl. destructive-gate static analysis + model validation); migration (all five tables — approvals and webhook-deliveries included so the trust model ships day one); runner with `tool`/`agent`/`gate`/`switch` (no fanout), lead-driven activation; **DB-backed gates with park/expiry sweep**; **per-hash approval enforcement on all triggers**; run-session turn discipline (queued-hook suppression, inline-step busy flag, interrupt semantics, title-hook skip, undo/PATCH/delete guards); manual + slash triggers; `workflow_status` SSE with DB hydration; runs API incl. cancel/force-fail/export; rehydration; token budget enforcement.
Frontend: `/workflows` list + YAML editor + approval flow; `WorkflowStatusPill`; run timeline; gate banner; sidebar badges.
Tests: schema/static-analysis suite; runner state-machine unit tests incl. kill-and-rehydrate and gate-expiry-across-restart; API tests per `tests/api/routes/test_team_*` fixtures; e2e: a 4-step workflow (with a gate) completes; the same run **restarted while parked at the gate** resumes correctly; a run restarted mid-agent-step parks as `interrupted` when the step is destructive.
Exit criteria (testable): (1) `bug-triage` (sequential explorer→debate variant) runs end-to-end on a real repo; (2) restart during the gate park and during a non-destructive step both recover per policy; (3) every step attempt has a `StepRun` row with status, timestamps, prompt hash, and output/error; (4) an unapproved repo-root definition cannot be triggered by any path.

### Phase 2 — True determinism and enterprise surface

`fanout` + direct `Agent.run()` execution (per-attempt interrupt topology §6.3) + `output_schema`/`submit_result` + per-step tool allowlists enforced mechanically; webhook trigger (§7.1) with dedup/rate-limit/payload spill; scheduler two-way integration; unattended-`ask`→gate escalation; per-step usage/cost attribution + daily budgets; form-view editor; browser-session cleanup wiring.

### Phase 3 — Hardening and depth

`execution: direct` by default; `tool_choice` plumbing per provider for hard schema guarantees; `loop:` step kind; `file` inputs + @mention expansion; `compact_between_steps`; retention/cleanup task with cascades; pause/resume polish; plugin `workflow.step.*` events; builtin workflow library.

### Phase 4 — Visual builder

React Flow canvas as an alternate renderer of the same YAML; run-timeline overlay.

---

## 12. Risks and open questions

| Risk | Mitigation |
|---|---|
| Phase-1 lead-driven steps are agentic inside (lead may not follow the step directive precisely) | By design for MVP; per-step directive prompts; Phase 2 direct execution closes it. Documented expectation. |
| Schema outputs are probabilistic without `tool_choice` (F6) | Bounded retry then `on_error`; Phase 3 provider forcing. Outputs are validated-or-failed, never partially trusted. |
| At-least-once side effects on crash recovery | Destructive steps park for operator resume by default (§6.5); worktree isolation; honest docs. No idempotency claims that MCP cannot honor. |
| Malicious YAML in cloned repos (name shadowing, capability drift via skills/blueprints) | Server-enforced per-hash approval with provenance from Phase 1; manifest pins skill/blueprint hashes; templated agent/tool names rejected for unattended triggers (§7.3). |
| Webhook replay (providers without signed timestamps) | Honest posture (§7.1): dedup = redelivery hygiene; body-hash collapse; destructive-gate rule; conservative rate default. |
| Runaway cost on unattended triggers | Run token budget + daily caps + kill switch (§7.4). |
| Gate parked while user chats on the run session | Gates hold no team (eviction + rehydration); user turns interleave at boundaries by the queue discipline (§6.1). |
| Long outputs bloating the DB | Size caps + artifact spill (§5); retention cascades (§7.4). |
| Open question | Per-definition environment pinning (model registry versions) for strict reproducibility — deferred; `definition_snapshot` records model names. |
| Open question | Should `switch` support expression conditions beyond equality-on-template-values in v1? Proposal: equality + `in` only. |

---

## 13. File-by-file change list (Phase 1)

Backend (new): `app/workflow/{__init__,models,registry,runner,steps,template,gates,triggers,policy}.py`, `app/services/workflows_fs.py`, `app/api/routes/workflows.py`, `app/api/schemas/workflows.py`, `app/agent/builtin_workflows/…`, migration `000000XX_create_workflows.py` (5 tables + `chat_sessions.workflow_run_id`).
Backend (edits):
- `app/agent/mode/team/team.py` — workflow branch in `_try_emit_done` (before `_activate_loop_message`); `/workflow` slash parse + `/loop` rejection on run sessions; run-session skip in `_try_activate_queued_after_lead_turn`; active-turn flag accessors for inline steps (~60 lines).
- `app/agent/mode/team/member.py` — suppress `QueuedMessageInjectionHook` on run sessions; run-aware title-hook attachment (~15 lines).
- `app/agent/hooks/title_generation.py` — `workflow_run_id` skip (~5 lines).
- `app/models/chat.py` — `workflow_run_id` column.
- `app/api/routes/team/chat.py` — undo/permission-PATCH/delete guards for run sessions (~25 lines).
- `app/api/app.py` — router mounts, runner start/stop, rehydrate, gate-expiry sweep.
- `app/core/{workspace_init,config}.py` — workflows root; `WORKFLOWS_DIR`, caps, kill switch.
- `app/services/stream_envelope.py` — `workflow_status` event.
- `app/agent/loader.py` — `workflow_run` lead tool (optional in Phase 1).
Frontend (new): `web/src/routes/workflows.tsx`, `web/src/components/workflow/{WorkflowList,WorkflowEditor,ApprovalDialog,RunTimeline,WorkflowStatusPill,GateBanner}.tsx`, `web/src/queries/useWorkflowsQuery.ts`, `web/src/api/client/workflows.ts`.
Frontend (edits): `router.ts`, `sse-reducer.ts`, `useTeamStore/{index,types}.ts`, `cache-invalidation-bridge.ts`, `Sidebar.tsx`/`CodingSidebar.tsx`, `TeamChatView/index.tsx`, `useTeamCommands.ts`.
Tests: `tests/workflow/…`, `tests/api/routes/test_workflows.py`, extend `tests/agent/mode/team/test_team.py` (branch ordering, queued discipline, interrupt semantics).

---

## Appendix A — Review provenance

v2 incorporates a three-lens adversarial review (2026-07-08) that verified all file:line citations and surfaced: 3 correctness majors (queued-message splicing, missing lead-side tool-injection channel, shared-event interrupt conflation), 7 completeness majors (output capture vs queueing, interrupt semantics, attachments, browser sessions, session deletion, permission durability/PATCH, compaction), and 2 enterprise blockers (trust model phasing, webhook replay/unsigned access) plus cost controls, approval-hash loopholes, gate-rule bypasses, at-least-once honesty, and post-restart monitoring. All are addressed in the sections above.
