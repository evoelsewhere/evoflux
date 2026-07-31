# EvoFlux Workflows — Design & Implementation Plan

> Status: PROPOSED (v5 — implementation audit: every mechanism the design leans on was traced to its exact function in the codebase by three parallel deep-dives; contradictions found in v4's self-audit are fixed; the doc now specifies integration points at function level, FE and BE, so it can be handed to an implementer as-is)
> Date: 2026-07-09 (v5, v4, v3); 2026-07-08 (v2)
> Scope: A visual node-graph builder for repeatable agent pipelines ("workflows"), scoped to `work` (usable from any work session) or `coding` (bound to a workspace/project), triggered by `/workflow` in chat, executed **inline in the current session**.
> Companion: `documents/analysis/claude-code-vs-evoflux.md`

---

## 1. Executive summary

Today, multi-step work in EvoFlux is decomposed by the **lead LLM at its own discretion** (via `team_delegate`). There is no way to save a repeatable shape for that decomposition — e.g. "analyze with the explorer + a debate second opinion, pause for my approval, then the coder fixes it" — and replay it with one command.

This plan introduces **Workflows**: a visual, node-based editor (React Flow canvas) for building a small pipeline out of pieces EvoFlux already has — agent turns with a delegation roster, direct tool/code calls, human-approval gates, branches — saved as a YAML file, and run with `/workflow` **inside whatever chat you're already in**. Execution plays out as ordinary turns in that session; there is no separate "run" screen, session, or durable run entity.

Design maxim: **the canvas configures what the lead would otherwise improvise; execution still looks like a normal conversation.**

### Goals

- Canvas-first authoring; YAML file is the source of truth (git-trackable, agent-editable); canvas and a raw-YAML Monaco view are two editors of the same file.
- Node kinds mirror existing capabilities only. Phase 1 engine kinds: `agent` (a team turn with a per-node subagent roster), `tool` (direct registry/MCP call, incl. the "Code" preset for `python`/`shell`), `gate` (choice pause via `ask_user`), `switch` (branch on a templated value), `input` (free-text pause via `ask_user`), `notify` (desktop notification), `transform` (pure template reshape), `foreach` (sequential iteration). Phase 2 kinds, schema pinned from v1: `workflow` (sub-workflow call), `wait` (capped delay). Assignment table in §4.5.
- Two scopes: `work` (no target anywhere) and `coding` (target = the triggering session's pinned workspace/project, or picked explicitly when started from the Workflows screen).
- `/workflow` in the composer lists approved workflows for the current scope; picking one runs it in that session immediately.
- Light per-node execution log for debugging + approve-once-per-hash; deliberately **no** durable runs, crash recovery, webhooks, schedules, or cost subsystem (see Non-goals).

### Non-goals (unchanged from v4, restated for standalone reading)

- No durable `WorkflowRun`: restart mid-execution = the workflow stops, like any in-flight turn today. `workflow_executions` rows are a debug log, never read back to resume.
- No unattended triggers (webhook/schedule). Every trigger has a human present.
- No cost/budget subsystem, no retention cascades, no audit export, no operator runbook.
- No new scripting engine — the Code node runs through the existing sandboxed `python`/`shell` tools.
- No multi-tenant RBAC; no exactly-once claims.
- **No true parallel branches in Phase 1** (new, explicit — v4 was self-contradictory here): execution is one session's turn stream, so the graph executes **sequentially in topological order**; multiple outgoing edges mean "both branches will run, one after the other," not concurrently. Real concurrency arrives only with Phase 2 direct execution.
- **No per-node custom lead in Phase 1** (new, explicit): an injected turn is always handled by *the session's* lead (`mailbox.send(to=self.lead.name)`, F4) — a different lead per node would require rebooting the team. The canvas still shows the lead card on every Agent node (the user's mental model), but it is locked to the session lead; a per-node `lead:` unlocks with Phase 2 direct execution.

---

## 2. Verified mechanics — the implementation anchors

Every claim below was verified against the live codebase on 2026-07-09 (three parallel deep-dives: team mechanics, service/tool invocation, frontend plumbing). These are not background findings; they are the exact functions the implementation plugs into.

### 2.1 Turn injection and completion (backend core)

| # | Fact | file:line |
|---|---|---|
| F1 | Turn-completion barrier `_try_emit_done` fires from every member's `_run_activation` finally; "turn finished" = `_has_active_turn` is True AND lead + all live members are in `("idle","error")`. It resets the flag, then priority-chains: queued user messages → `/loop` → DoneEvent. | `app/agent/mode/team/team.py:455-486` |
| F2 | Synthetic-turn injection recipe (from `_activate_loop_message`): ① `stream_store.init_turn(session_id, keep_subscribers=True)` ② `save_message(db, session_uuid, HumanMessage(content=prompt))` — plain message, no `extra` ③ set `_has_active_turn = True` ④ SSE status + `queued_turn_start` (carries message ids) ⑤ `mailbox.send(to=self.lead.name, Message(from_agent="user", content=f"[user]: {prompt}"))`, which wakes the lead. | `team.py:621-689` (steps at 631, 643-645, 651, 652-677, 678-683) |
| F3 | **There is no turn id.** `SessionMessage` has only `id` (uuid7, time-ordered), `session_id`, `role`, `content`, `tool_calls`, `extra`, `created_at`. Output capture must use a **watermark**: record the last message id before injecting; afterwards query the lead session's messages with `created_at >` watermark. | `app/models/chat.py:188-244` |
| F4 | Handoff artifacts are **not persisted structurally**: the JSON artifact lives on a transient mailbox-message attribute and on the `handoff` SSE event; the DB row is only formatted text (`… FINAL HANDOFF: …`). To capture structured output the runner must listen to the stream in-process (`memory_stream_store.attach(session_id)` returns an AsyncGenerator any server code can consume); fallback is the lead's last assistant text after the watermark. | `app/agent/mode/team/handoff.py:359, 343, 373-405`; `member.py:796-828`; `app/services/memory_stream_store.py:404` |
| F5 | Members materialize **on demand**, not at boot: `AgentTeam.spawn(blueprint, *, instance_id=None)` is public, server-callable, roster-locked, and handles DB session creation, parenting, mailbox registration, and SSE itself. The lead's own path is the `team_manage` tool → `team.spawn()`. | `team.py:1336-1360` (spawn), `1366-1375` (`_spawn_locked`), `1401-1411` (rebuild+rename); `app/agent/mode/team/manage.py:37-95` |
| F6 | `team_delegate`/`team_message`/`team_handoff`/`team_reject` all resolve recipients through one choke point, `AgentTeam.resolve_recipient` — live instances only, **no auto-spawn** (delegating to a non-live blueprint returns an error telling the lead to spawn first). **No allowlist mechanism exists**; the smallest insertion is a team field checked in `resolve_recipient` + `_spawn_locked`, with the error text in `_recipient_error`. | `team.py:1662-1688`; `app/agent/mode/team/tools.py:126-145, 148-166` |
| F7 | Queued user messages are `SessionMessage` rows with `extra.queue_status="queued"`, appended by `save_queued_user_message` (chat route does this under `team_obj.user_message_lock` when `has_active_user_turn()` is True), drained FIFO by `_activate_queued_user_messages` from the F1 chain. **Do not put workflow starts in this queue** — `QueuedMessageInjectionHook` drains the same queue mid-turn, which would splice a workflow start into a running turn. | `app/services/chat_service.py:649-665, 694-716`; `app/api/routes/team/chat.py:374, 426-439`; `team.py:471, 569-619` |
| F8 | `QueuedMessageInjectionHook` reads only its constructor args at fire time (no team reference), **but hooks are rebuilt on every activation** — so suppressing it per-activation with a flag check at the attach site is sufficient and cheap. | `app/agent/hooks/queued_injection.py:39-103`; attach site `member.py:946-953` (rebuild loop 911-953) |
| F9 | User interrupt (Stop button) arrives as `interrupt=true` on `/team/chat` and is applied inside `handle_user_message`. | `team.py:756-765` |

### 2.2 Direct service/tool invocation (no LLM)

| # | Fact | file:line |
|---|---|---|
| F10 | `AskUserService(session_id, *, stream_session_id=None)` is callable from arbitrary server code: `await svc.ask(questions: list[QuestionSpec]) -> list[str]` pushes a `QuestionAskedEvent` to the stream store and awaits an `asyncio.Future`. `QuestionSpec` is `{question: str, options: list[str]}` — **no separate title/body**, so a gate node flattens `title\n\nbody` into `question`. The reply endpoint (`POST /{session_id}/questions/{request_id}/reply`) locates the service via a module-global registry keyed by session_id — the runner must call `set_ask_user_service(svc)` before asking and `reset_ask_user_service(...)` after. Plan approval works identically. | `app/agent/ask_user.py:59, 66, 41, 80-100, 108-118, 143-152`; `app/agent/tools/builtin/ask_user.py:16-27`; `app/api/routes/team/questions.py:13-39`; `app/agent/plan.py:97-156` |
| F11 | Registry tools are invocable directly: the name→Tool map is `_default_tool_registry()` (`"python"`, `"shell"` keys), and `await tool.arun(**kwargs)` runs pydantic validation (`ToolArgumentError` on mismatch) then the function, wrapping failures in `ToolExecutionError`. | `app/agent/loader.py:268-360` (keys at 332-333); `app/agent/tools/registry.py:218, 239-245, 274-277` |
| F12 | `python` tool params: `code` (required), `description=""`, `timeout_seconds` (default 120). `shell` tool params: `command` (required), `workdir=None` (relative anchored at sandbox root), `timeout_seconds` (default 60), `background=False`, plus a deny-scan via `sandbox.check_command()`. Both resolve cwd from the `_sandbox_ctx` contextvar, which **falls back to a default sandbox if unset** — the only required setup is `set_sandbox(SandboxConfig(workspace=...))` for coding scope. | `app/agent/tools/builtin/python.py:38, 54-89, 102, 207`; `shell.py:62, 236-249, 267-320, 337`; `app/agent/sandbox.py:56-66` |
| F13 | The full contextvar recipe a team member sets before running (the superset a runner may need): `set_sandbox` → `set_permission_service` → `set_plan_mode_service` → `set_ask_user_service` → `set_role`, all reset in `finally`. Dream proves the minimal case (sandbox only). | `member.py:1065-1099, 1123-1127`; `app/services/dream.py:1168` |
| F14 | MCP: `await mcp_manager.call_app_tool(server, tool, args) -> CallToolResult`. Errors: `KeyError` (unknown server), `RuntimeError` (state ≠ ready — covers `auth_required`), `ValueError` (tool not advertised; names compared **without** the `mcp_{server}_` prefix). Result `.content` is typed blocks; existing code flattens only `TextContent` — there is **no structured-json fast path**, so the tool-node output rule (§6.4) must define one. | `app/agent/mcp/manager.py:391-412` (errors 397-404), state 632/644/656; `app/agent/mcp/tools.py:138-144, 264-278` |
| F15 | File-based content: `discover_commands()` (four roots, first-source-wins, mtime cache) is the discovery precedent; `render_command` (`$ARGUMENTS`) the templating seed; **CRUD lives in the skills routes** (atomic write, create/update/delete) — commands.py has no CRUD. `parse_slash_invocation` exists for slash parsing. | `app/services/commands.py:66-296` (discovery; note: *not* CRUD), `198`, `299-312`; `app/api/routes/skills.py:85-100, 240, 262, 302` |

### 2.3 Frontend plumbing

| # | Fact | file:line |
|---|---|---|
| F16 | Dynamic slash commands: `GET /api/commands?workspace=` → `listCommands()` → `useCommandsQuery` → merged **client-side** into a literal `slashCommands` array in `TeamChatView` (builtins, then coding-only `/loop` entries, then user commands with `keepInputOpen: true`). The `SlashCommand` interface supports `description`/`category`/`displayName`/`insertText`/`isSeparator` — **no `disabled` field**; gating is by omission. | `app/api/routes/commands.py:37-48`; `web/src/api/client/agents.ts:107-114`; `web/src/queries/useCommandsQuery.ts:8-15`; `web/src/components/TeamChatView/index.tsx:683-713, 1442`; `web/src/components/InputBar.tsx:23-53` |
| F17 | `/loop` path: the FE intercepts in `onSubmit` (`tryHandleBuiltinLoopCommand` → store `sendLoopCommand`, optimistic state, then POSTs the raw text); the server re-parses in `handle_user_message`. User commands are different: FE calls `POST /api/commands/{name}/render` and sends the expanded body as an ordinary message — **the chat route never sees the slash text**, so "put `/workflow` in a command body" does NOT compose for free (v4's claim; dropped). | `TeamChatView/index.tsx:1424-1438, 814-849, 853-888`; `web/src/stores/useTeamStore/index.ts:559-659`; `app/api/routes/team/chat.py:300-312`; `team.py:104-124, 769-871` |
| F18 | `LoopStatusPill` pattern (the pill recipe to clone): SSE `loop_status` → case in `sse-reducer.ts:489-501` → `activeLoop` field (`types.ts:102`) → rendered in `TeamChatView` (desktop 1162-1168, mobile 1604); hydration on load via `GET /api/team/{sid}/history` (`loop_status` field at `chat.py:1143`) applied at `useTeamStore/index.ts:801`. Server emits with `StreamEnvelope.from_parts("loop_status", payload)` — **no typed event model needed**. | cited inline; emitter `team.py:652-663`; `StreamEnvelope.from_parts` `app/services/stream_envelope.py:109` |
| F19 | Session scope in FE: `mode` is route-derived (`forcedMode` prop, default `'work'`); workspace/projectId live in `useTeamStore` (`_workspace`, `projectId`), synced from URL/session (`work.tsx:39, 149-160`; `index.ts:794`). | `web/src/routes/work.tsx:17-21, 310-311`; `TeamChatView/index.tsx:117, 274` |
| F20 | Cache invalidation from SSE goes through the `cacheInvalidations` queue → `applyCacheInvalidations` bridge. | `web/src/stores/cache-invalidation-bridge.ts:12`; wired `work.tsx:242-250` |

---

## 3. Concepts and terminology

| Term | Definition |
|---|---|
| **WorkflowDefinition** | A YAML file: `scope`, `inputs`, `nodes`, `edges`, `outputs`, `ui`. Identified by `name` per discovery root; identified for approval by content hash (sha256 of file bytes). |
| **Node** | v1 engine kinds: `kind ∈ {agent, tool, gate, switch, input, notify, transform, foreach}`; Phase 2 adds `{workflow, wait}` (§4.5). Output referenced downstream as `{{nodes.<id>.output}}`. Only `gate`/`switch` have conditional (`when:`) outgoing edges. |
| **Edge** | `{from, to, when?}`. Determines order and (with `when`) conditional firing. Execution is sequential-topological in Phase 1 (§6.3). |
| **Roster** (of an `agent` node) | The subagent blueprints (`role: member`) the session lead may spawn/delegate to during that node's turn. The lead card on the canvas is the session lead, locked in Phase 1. Tool access is each blueprint's own configuration (Agents settings) — never a node-level choice; only `tool` nodes pick a tool. |
| **Scope** | `work` or `coding` (§6.2). |
| **Execution** | One inline run inside a specific session. In-memory state drives it; two DB tables log it. One active execution per session, enforced with 409. |
| **Approval** | Per-content-hash acknowledgment of the manifest (agents, tools, MCP servers, env refs) before a definition is runnable. |

---

## 4. Workflow definition format

### 4.1 Storage and discovery

Same roots/precedence as skills/commands/snippets (F15):

1. `{workspace}/.evoflux/workflows/*.yaml` — per-repo. Shadows global names; needs its own approval regardless (§7).
2. `{EVOFLUX_CONFIG_DIR}/workflows/*.yaml` — global.
3. `app/agent/builtin_workflows/*.yaml` — bundled read-only examples.

Implementation: `app/services/workflows_fs.py` — discovery/mtime-cache cloned from `commands.py:66-296`; atomic write + create/update/delete cloned from `routes/skills.py:85-100, 240-302` (commands.py has no CRUD to clone — F15).

### 4.2 Schema (v1)

```yaml
# .evoflux/workflows/bug-triage.yaml
schema_version: 1
name: bug-triage
description: Triage a bug and open a fix PR
scope: coding                      # work | coding

inputs:
  - name: ticket_id
    type: string                   # string | number | boolean | enum
    required: true
    # enum adds: options: [a, b, c]

nodes:
  - id: fetch
    kind: tool
    tool: mcp_jira_get_issue       # registry tool or mcp_<server>_<tool>
    args: { key: "{{inputs.ticket_id}}" }

  - id: analyze
    kind: agent
    subagents: [debate]            # role:member blueprints; pre-spawned and
                                   # allowlisted for this node's turn (§6.4).
                                   # NOTE: no `lead:` field in v1 — the turn
                                   # is handled by the session lead (F2/F6);
                                   # the canvas shows the lead card locked.
                                   # NOTE: no `tools:` field either — each
                                   # agent uses its blueprint's own configured
                                   # tools (Agents settings). There is no
                                   # per-turn tool channel for lead-driven
                                   # turns anyway; tool choice on a node
                                   # exists only on `tool` nodes.
    prompt: |
      Analyze this bug. Delegate to `debate` for a second opinion if useful.
      Ticket: {{nodes.fetch.output.summary}}
      Description: {{nodes.fetch.output.description}}
    timeout_s: 900                 # optional; default from settings

  - id: approve
    kind: gate
    title: "Approve fix plan for {{inputs.ticket_id}}"
    body: "{{nodes.analyze.output.text | truncate:2000}}"
    choices: [approve, reject]     # rendered via ask_user (F10): question =
                                   # title + "\n\n" + body, options = choices

  - id: fix
    kind: agent
    subagents: []                  # empty roster = the lead works solo
    prompt: |
      Implement the approved fix plan. Verify with tests before finishing.
      Plan: {{nodes.analyze.output.text}}

  - id: run_tests
    kind: tool                     # the canvas "Code" node — same kind,
    tool: python                   # tool: python | shell
    args:
      code: |
        import subprocess
        r = subprocess.run(["pytest", "-q"], capture_output=True, text=True)
        print(r.stdout[-4000:])

edges:
  - { from: fetch,    to: analyze }
  - { from: analyze,  to: approve }
  - { from: approve,  to: fix,       when: approve }   # gate answer routing
  - { from: fix,      to: run_tests }
  # `when: reject` has no edge → reaching approve with "reject" ends the
  # workflow gracefully (§6.3: no fired outgoing edge = flow ends there).

outputs:
  verdict: "{{nodes.analyze.output.text}}"
  tests: "{{nodes.run_tests.output.text}}"

ui:                                # canvas layout only; engine ignores it;
  nodes:                           # preserved verbatim on round-trip. Missing
    fetch:    { x: 0,   y: 80 }    # (e.g. agent-authored YAML) → auto-layout
    analyze:  { x: 240, y: 80 }    # (simple layered columns by topo depth —
    approve:  { x: 480, y: 80 }    # no extra dependency).
    fix:      { x: 720, y: 80 }
    run_tests:{ x: 960, y: 80 }
```

`switch` nodes: `kind: switch, value: "{{nodes.analyze.output.severity}}"`; outgoing edges carry `when: critical` / `when: normal`. Equality and `in` (comma list) only in v1.

Compact specs for the remaining kinds (all first-class in v1 except where marked Phase 2):

```yaml
- id: ask_env
  kind: input                      # free-text question mid-flow (gates are
  question: "Deploy to which env?"  # choice-only). Output: {"text": "<answer>"}.
                                   # No conditional edges — route with a
                                   # switch on {{nodes.ask_env.output.text}}.

- id: ping
  kind: notify                     # desktop notification, non-blocking
  title: "bug-triage"              # optional; defaults to the workflow name
  message: "Analysis done — approval gate is next."

- id: shape
  kind: transform                  # pure template render — no sandbox, no LLM
  set:
    summary: "{{nodes.fetch.output.summary}}"
    files: "{{nodes.analyze.output.affected_files | json}}"
  # output = the rendered `set` object

- id: per_repo
  kind: foreach                    # SEQUENTIAL in Phase 1 (§6.3)
  items: "{{nodes.plan.output.repos}}"   # must render to a JSON array
  body:                            # exactly ONE inline node spec in v1 —
    kind: tool                     # allowed body kinds: tool | transform |
    tool: shell                    # notify | agent
    args: { command: "git -C {{item.path}} status --short" }
  # body templates additionally see {{item}}, {{item.<field>}}, {{index}}
  # output: {"items": [<body outputs>...], "count": N}

# ── Phase 2 kinds — schema pinned and validated from v1 so files don't churn:
- id: triage_sub
  kind: workflow                   # run another approved workflow inline
  workflow: bug-triage
  inputs: { ticket_id: "{{item.key}}" }

- id: cool_down
  kind: wait
  seconds: 120                     # hard cap 600 (no durability → no long waits)
```

### 4.3 Templating

- `{{ ... }}` over `inputs.*`, `nodes.<id>.output(.dotted.path)`, `env.<ALLOWLISTED>`. Filters: `json`, `truncate:N`. No expressions.
- **Node output shape rule** (needed because MCP results have no structured fast path, F14): every node's output is a JSON object. `tool` nodes: if the result has MCP `structuredContent`, use it; else if the flattened text parses as JSON, use that; else `{"text": <flattened text>}`. `python`/`shell`: `{"text": stdout, "exit_code": n}`. `agent` nodes: the handoff artifact JSON if captured (F4), else `{"text": <lead's final assistant text>}`. `gate`: `{"choice": <answer>}`. `input`: `{"text": <answer>}`. `notify`: `{"sent": true}`. `transform`: the rendered `set` object. `foreach`: `{"items": [<body outputs>], "count": N}`. `workflow` (P2): the child's `outputs` object. `wait` (P2): `{"waited_s": N}`. A dotted path that doesn't resolve → the node **fails loudly** at render time.
- Inside a `foreach` body, the template scope additionally binds `{{item}}`, `{{item.<field>}}`, `{{index}}`; outer `{{nodes.*}}`/`{{inputs.*}}` remain visible.
- `env.*` refused into anything persisted in `workflow_node_runs` and into remote-egress content (remote-MCP tool args, agent prompts) unless the reference is in the approved manifest — same bar for both egress channels.
- Implementation: `app/workflow/template.py` (~150 lines; generalizes `render_command`'s discipline, `commands.py:299-312`, to dotted paths + filters).

### 4.4 Validation (save time)

Pydantic models in `app/workflow/models.py` (definition) + `app/api/schemas/workflows.py` (API DTOs):

- DAG: unique node ids; every edge endpoint resolves; cycle detection; every node reachable from an entry node (in-degree 0). At least one entry node.
- `agent` nodes: each `subagents[]` entry must resolve to a `role: member` blueprint in the current roster registry — unknown name → save error naming the available roster. A `lead:` key, if present, is **rejected in v1** with "custom leads require direct execution (Phase 2)".
- `tool` nodes: `tool` must be a registry name (`_default_tool_registry()` keys, F11) or a ready-form `mcp_<server>_<tool>` name; `args` keys are not validated against the tool schema at save (runtime `arun` validation covers it, F11) except for `python`/`shell` where `code`/`command` presence is checked.
- `gate` nodes: non-empty `choices`; every outgoing edge's `when` ∈ `choices`.
- `switch` nodes: every outgoing edge has `when`; at most one default (`when: "*"`).
- `input` nodes: non-empty `question`. No conditional outgoing edges (only `gate`/`switch` route).
- `notify` nodes: non-empty `message`; `title` optional (defaults to the workflow name).
- `transform` nodes: `set` is a non-empty map of key → template string.
- `foreach` nodes: `items` template present; `body` is exactly one inline node spec of kind `tool | transform | notify | agent` (no `gate`/`input`/`switch`/nested `foreach` in v1); `concurrency` rejected in v1 (Phase 2). The destructive lint counts the body's effective tools.
- `workflow` nodes (Phase 2 kind, validated from v1 so files don't churn): target must exist; approval + scope checked again at run time (a `work`-scope target is callable from any workflow; a `coding`-scope target only from a `coding` workflow); static cross-definition cycle check at save; runtime depth cap 3. Phase 1 **runs** reject definitions containing one (422 "sub-workflows arrive in Phase 2") while still validating them.
- `wait` nodes (Phase 2 kind, same treatment): integer `seconds` in 1..600.
- Destructive-path lint (advisory): entry→node paths whose **effective tools** intersect `{edit, write, patch, rm, shell, python, bg}` (`app/agent/agent_loop/tool_executor.py:38-41`) without an intervening gate get a builder-UI warning. Effective tools: for a `tool` node, the named tool; for an `agent` node, the union of the session lead's and roster blueprints' configured tools, resolved from blueprint files at save time (agent nodes have no `tools:` field of their own — a `tools:` key on an agent node is rejected with "tools are configured on the agent blueprint, not the node"). Advisory because all triggers are human-present.
- Inputs: names unique; `enum` requires `options`.
- Content hash (sha256 of canonical file bytes) + manifest (§7) computed at save and returned to the client.

### 4.5 Full node palette — phase assignment

All three tiers are **committed scope** (user direction), not a wishlist. Grounded in the builtin-tool inventory (`app/agent/tools/builtin/` — `web`, `browser_use_tool`, `memory_search`, `wiki_search`, `pr`, `worktree`, `date`, `lsp`, `preview`, `code_graph`, `todo`, plus the four anchors) and in patterns proven by n8n/Dify/ComfyUI-class builders.

| Tier | Node | `kind` | Phase | Cost / feasibility anchor |
|---|---|---|---|---|
| A | Start / End | — (pseudo) | 1 (M6) | Pure FE render of `inputs[]`/`outputs:`; engine unchanged |
| A | Note | — (`ui:` only) | 1 (M6) | Never appears in `nodes[]` |
| A | If | `switch` preset | 1 (M6) | Palette sugar, two fixed handles |
| A | Web / Browser / Knowledge / PR / Worktree presets | `tool` presets | 1 (M6) | Palette metadata over existing registry tools (F11) |
| B | Input | `input` | 1 (M3/M4) | `ask_user` free-text is native — `QuestionSpec.options` optional, UI always shows a free-text field (`app/agent/tools/builtin/ask_user.py:16-28`); = gate handler with `options: []` |
| B | Notify | `notify` | 1 (M3) | Existing `desktop_notification` push (`team.py:525, 970`) |
| B | Transform | `transform` | 1 (M3) | `template.py` only; no sandbox, no LLM, zero destructive surface |
| B | For-each | `foreach` | 1 (M4) | Sequential per-item body run — matches §6.3 exactly; single-node inline body in v1 |
| C | Sub-workflow | `workflow` | 2 | Inline child run in the same `ExecutionState` stack; static cross-definition cycle check + depth cap 3; scope rule in §4.4. Sanctioned replacement for the dropped command-body composition (F17) |
| C | Wait | `wait` | 2 | `asyncio.sleep`, cancellable by stop, hard cap 600 s (no durability → no long waits) |
| C | Parallel | — (not a kind) | 2 | Concurrency is an **execution upgrade**, not a node: branches run concurrently + `foreach.concurrency: N`, unlocked by direct execution; §6.3 semantics are already branch-safe |

Considered and rejected: a dedicated HTTP node (use Code/MCP/`web` tool — no new capability), webhook-in/schedule nodes (non-goal: unattended), attachment/file nodes (v1 inputs are scalars only).

---

## 5. Data model and migration

Migration `00000020_create_workflows.py` (next in the existing 8-digit sequence; bump if more migrations land first). Two tables, no `chat_sessions` change:

```
workflow_approvals
  definition_hash  str PK
  name             str
  root             str            -- "workspace" | "global" | "builtin" + path
  manifest         JSON           -- {agents:[], tools:[], mcp_servers:[], env_refs:[]}
  approved_at      datetime

workflow_executions
  id               UUID PK (uuid7)
  definition_name  str, indexed
  definition_hash  str
  session_id       UUID, indexed  -- ordinary session it ran in; no FK (FK
                                  -- enforcement is off anyway, app/core/db.py:56-71)
  status           str            -- running|waiting_gate|completed|failed|stopped
                                  -- waiting_gate covers ANY human pause
                                  -- (gate or input node)
  error            str NULL
  started_at / ended_at

workflow_node_runs
  id               UUID PK (uuid7)
  execution_id     UUID, indexed
  node_id          str
  iteration        int NULL       -- foreach item index (NULL for non-foreach)
  status           str            -- running|succeeded|failed|skipped
  output / error   JSON NULL      -- capped 32 KB (debug log, not artifact store)
  started_at / ended_at
```

Rows are written best-effort as execution progresses and are **never read to resume anything**. All live state is the in-memory `ExecutionState` (§6.1).

---

## 6. Execution engine

New package `app/workflow/`: `models.py`, `graph.py`, `registry.py`, `runner.py`, `nodes.py`, `template.py`, `policy.py`.

### 6.1 Runner service and team wiring

`WorkflowRunner` is a process singleton holding `active: dict[session_id, ExecutionState]`.

```python
@dataclass
class ExecutionState:
    execution_id: UUID
    definition: WorkflowDefinition        # parsed snapshot
    session_id: str
    scope_workspace: str | None           # resolved coding target (None for work)
    node_outputs: dict[str, dict]         # templating source of truth (in-memory)
    node_status: dict[str, str]
    fired_edges: set[tuple[str, str]]
    pending_node: str | None              # agent node whose turn is in flight
    watermark: str | None                 # last SessionMessage id before injection (F3)
    captured_artifact: dict | None        # from the in-process handoff listener (F4)
    allowlist_token: object | None        # for restoring team.turn_allowed_blueprints
    interrupted: bool
    stop_requested: bool
```

**Team wiring — two hook points in `_try_emit_done`** (avoiding a circular import: `team.py` gets module-level `set_workflow_hooks(capture_cb, advance_cb)` called from `app/api/app.py` startup):

1. **Top of the barrier, before `_activate_queued_user_messages`**: `capture_cb(session_id)` — if this session has an execution with `pending_node` set, capture that node's output now (§6.4), persist the node run, clear `pending_node`. This runs unconditionally so a queued user message can never be mis-captured as node output.
2. **After the queued-message branch declines (nothing queued), before the `/loop` branch**: `advance_cb(session_id) -> bool` — if an execution is active and not waiting on a gate, advance the graph (§6.3): run inline nodes until the next `agent` node, inject its turn, return True (consumed). Returns False when idle → the chain falls through to `/loop`/DoneEvent as today.

**Interrupt visibility**: one line added where `interrupt=true` is applied (`team.py:756-765` region) calls `runner.notify_interrupt(session_id)` → sets `ExecutionState.interrupted`; the next `capture_cb` marks the node run `failed("interrupted")` and the execution `stopped` instead of advancing.

**Busy-flag for inline stretches**: while the runner is executing `tool`/`gate`/`switch` nodes (no team turn active), it sets `_has_active_turn` via a small team accessor so user messages queue (F7 path at `chat.py:374`) instead of colliding; before injecting the next agent turn it checks the queue — if non-empty, it releases the boundary to the normal chain (user turn runs; the runner resumes at that turn's completion via `advance_cb`).

**Queued-injection suppression**: at the hook-attach site (`member.py:946-953`, rebuilt every activation per F8), skip attaching `QueuedMessageInjectionHook` when `runner.is_driving(session_id)` — user messages then land at node boundaries only.

### 6.2 Trigger paths and scope resolution

- **`/workflow` in a session** (§9/§10 detail the FE side): FE POSTs `POST /api/workflows/{name}/run {session_id, inputs}`. Server: 403 if the definition's current hash is unapproved; 409 if the session already has an active execution; 422 on input mismatch. Scope: `work` definitions run in any session; `coding` definitions require the session to be a coding session — its pinned workspace/project **is** the target (no picker). A `coding` definition triggered from a work session → 422 with "open it in a coding session or run from the Workflows screen".
- **Workflows screen, no session**: FE resolves/creates a session first using the existing session-resolve endpoint (the same one the app uses on navigation), for `coding` scope after prompting for workspace/project, then calls the same `/run` with that `session_id` and navigates to the session. The runner itself never creates sessions.
- If the session has an active user turn at `/run` time, the runner stores the execution in `active` with nothing pending; the next `advance_cb` at the natural boundary starts node 1. (Workflow starts never enter the user-message queue — F7 caveat.)

### 6.3 Graph semantics (Phase 1: sequential)

- At validation, compute a topological order. At runtime, maintain `fired_edges`.
- A node is **ready** when every incoming edge is *resolved* (fired, or dead because its `from` node was skipped/its `when` didn't match) and ≥1 incoming edge fired (entry nodes: ready at start). A node all of whose incoming edges are dead is marked `skipped`, and all its outgoing edges are dead.
- The runner always executes **one node at a time**, picking the first ready node in topological order. Multiple outgoing branches therefore interleave sequentially and deterministically. (Phase 2 direct execution may run branches concurrently; the semantics above are already branch-safe.)
- Edge firing: unconditional edges fire when `from` succeeds. `when:`-edges fire when `from` is a gate whose answer equals `when`, or a switch whose value matches (`*` = default). A gate/switch whose answer matches **no** outgoing edge ends the flow gracefully at that node (`completed`, with a note in the node run). All other kinds (`agent`/`tool`/`input`/`notify`/`transform`/`foreach`/`workflow`/`wait`) fire their unconditional edges on success — routing on an input's free-text answer is done by following it with a `switch`.
- `foreach` bodies are **inline specs**, not top-level nodes — they never participate in the top-level topological order; the foreach node itself is one unit in the walk.
- Node failure: the execution is marked `failed`, remaining nodes `skipped`, marker cleared, `workflow_progress(failed)` emitted. No `on_error`/retry in v1 (kept out deliberately; the transcript already shows agent-node failures, and the node-run log shows tool-node errors).
- Flow end: when no node is ready and none pending → render `outputs` (into the execution row + final SSE), status `completed`, clear the marker.

### 6.4 Node handlers (`app/workflow/nodes.py`)

**`agent`** —
1. Pre-spawn each roster blueprint with no live instance: `await team.spawn(bp)` (F5 — server-callable; delegate does not auto-spawn, F6).
2. Set the per-turn allowlist: `team.turn_allowed_blueprints = {node.subagents...}` — enforced by the new checks in `resolve_recipient` (`team.py:1662-1688`) and `_spawn_locked` (`team.py:1366-1375`), with error text in `_recipient_error` (`tools.py:148-166`). Cleared at capture.
3. Record `watermark` = last message id of the lead session (F3). Start an in-process `attach(session_id)` listener task filtering for `handoff` events (F4) into `captured_artifact`.
4. Inject the turn with the rendered prompt via the F2 recipe. Set `pending_node`.
5. On `capture_cb`: stop the listener; output = `captured_artifact` if set, else `{"text": last assistant message with created_at > watermark}`; persist node run; clear allowlist.
6. Per-node `timeout_s` (default from `settings.WORKFLOW_NODE_TIMEOUT_S`, 900): a runner-side timer that, on expiry, triggers the same interrupt path as F9 and marks the node failed.

**`tool`** —
1. Set contextvars (F12/F13): `set_sandbox(SandboxConfig(workspace=scope_workspace or default))`; nothing else needed for `python`/`shell` (permission enforcement is a hook-layer concern that direct calls bypass — acceptable here because the manifest was explicitly approved, §7).
2. Registry tools: `await _default_tool_registry()[name].arun(**rendered_args)` (F11). MCP tools: `await mcp_manager.call_app_tool(server, bare_tool, rendered_args)` (F14; catch its `KeyError/RuntimeError/ValueError` into a node error naming the server).
3. Output per the §4.3 shape rule. `background: true` on shell is rejected at validation (a workflow node must end when it ends).

**`gate`** —
1. `svc = AskUserService(session_id)`; `set_ask_user_service(svc)`; execution status → `waiting_gate`; emit `workflow_progress`.
2. `answers = await svc.ask([QuestionSpec(question=f"{title}\n\n{body}", options=choices)])` (F10). The FE renders this through the **existing** question UI (event-driven; verify early in M4 that it renders with no turn active — fallback: a small `GateBanner` fed by `workflow_progress`, §10).
3. Output `{"choice": answers[0]}`; fire the matching edge; `reset_ask_user_service`. Stop during a gate: `POST /executions/{id}/stop` cancels the awaited future (`CancelledError` cleanup exists, F10).

**`switch`** — render `value`, match edges, fire one. Pure function, no I/O.

**`input`** — the gate handler with `options: []` (free-text answer field is native to the question UI, §4.5); execution status `waiting_gate` while pending; output `{"text": answers[0]}`. Same service registration, reply endpoint, and stop-cancellation as gates.

**`notify`** — push the existing `desktop_notification` envelope (the `team.py:525` payload shape) with rendered `title`/`message`; instant; output `{"sent": true}`.

**`transform`** — render every value in `set` (dotted paths + filters); output is the rendered object. Pure function like `switch`; the safe alternative to a Code node for data plumbing.

**`foreach`** — render `items` (must yield a JSON array, else the node fails); for each item run the inline `body` spec through its kind's handler with `{{item}}`/`{{index}}` bound into the template scope; **sequential in Phase 1** (an `agent` body injects one turn per item, each waiting for its boundary); one `workflow_node_runs` row per iteration (the `iteration` column); a failing iteration fails the whole node (remaining items skipped — no partial-continue in v1). Output `{"items": [...], "count": N}`.

**Phase 2 — `workflow`**: resolve target + re-check approval/scope, then run the child definition inline within the same `ExecutionState` stack (depth cap 3); child node runs recorded with `sub.<child_node_id>` ids in the same execution. Output = the child's rendered `outputs`. **`wait`**: `asyncio.sleep(seconds)`, cancellable by stop; output `{"waited_s": N}`.

### 6.5 Stop / failure / SSE

- **Stop**: the Stop button works during agent-node turns (F9 → `notify_interrupt`). During inline nodes/gates there is no turn, so the pill has an ✕ calling `POST /api/workflows/executions/{id}/stop` → cancels the current awaitable (gate future / tool task), marks execution `stopped`, clears the marker. (This is the one control endpoint v4 said it wouldn't need; gates/tools made it necessary.)
- **SSE**: `workflow_progress`, emitted via `StreamEnvelope.from_parts` like `loop_status` (F18 — no typed model): `{type, session_id, execution_id, definition_name, status, node_id, node_index, total_nodes, error?}` on every transition.
- **Hydration**: `GET /api/team/{sid}/history` gains a `workflow_execution` field (sibling of `loop_status` at `chat.py:1143`) read from `runner.active` — live-state semantics, gone after restart, consistent with the no-durability posture and with the loop precedent.

---

## 7. Trust and safety (lightweight)

1. **Approve once per hash.** Manifest = union over nodes of: subagent blueprint names (agent nodes — their tools are the blueprints' own config and are shown informationally in the dialog by resolving the blueprints at display time), tool/MCP names (`tool` nodes only), MCP server names, `env.*` references. Shown in an `ApprovalDialog`; `POST /approve {hash}` records it (409 if the file changed since — hash mismatch). Unapproved definitions are listed but not runnable and omitted from the slash menu (F16: gating by omission is the existing pattern). Workspace-root definitions never inherit a global name's approval.
2. Direct tool-node calls bypass the permission-hook layer by construction (they don't go through an agent) — this is exactly what the manifest approval covers, and why it is mandatory rather than cosmetic.
3. Destructive-path lint (§4.4), advisory.
4. Per-node timeouts (§6.4) so a hung call can't wedge a session.

---

## 8. API surface (contracts)

Router `app/api/routes/workflows.py`, mounted in `app/api/app.py` (next to `commands` at `:181`).

```
GET  /api/workflows?workspace=
  → {workflows: [{name, description, scope, inputs[], hash, root, source_path,
                  approved: bool, valid: bool, errors: [str], node_count}]}

GET  /api/workflows/{name}?workspace=
  → {raw_yaml, graph: {nodes[], edges[], ui}, hash, root, approved, manifest,
     errors: []}

PUT  /api/workflows/{name}            body: {graph} | {raw_yaml}; ?workspace= targets
  → same as GET detail; 422 with per-field errors     the repo root
DELETE /api/workflows/{name}
POST /api/workflows/{name}/approve    body: {hash}    → 204 | 409 hash-mismatch

POST /api/workflows/{name}/run        body: {session_id, inputs: {...}}
  → {execution_id, session_id}
  errors: 403 unapproved | 404 unknown | 409 execution-already-active
          | 422 inputs/scope invalid
POST /api/workflows/executions/{id}/stop → 204
GET  /api/workflows/executions?definition=&cursor=   → debug-log list
GET  /api/workflows/executions/{id}                  → {execution, node_runs[]}
```

Plus the `workflow_execution` field added to the existing team-history response (§6.5).

---

## 9. Frontend plan

### 9.1 Trigger surface (chat)

- **Client**: `web/src/api/client/workflows.ts` — `listWorkflows`, `getWorkflow`, `saveWorkflow`, `deleteWorkflow`, `approveWorkflow`, `runWorkflow`, `stopExecution`, `listExecutions`, `getExecution`. Types in `web/src/api/types.ts`.
- **Query**: `useWorkflowsQuery(workspace)` cloning `useCommandsQuery` (F16).
- **Slash menu**: in the `slashCommands` merge (`TeamChatView/index.tsx:683-713`), append one entry **per approved workflow** matching the current scope (`mode` prop + `_workspace`, F19): `displayName: "/workflow <name>"`, `insertText: "workflow <name>"`, `category: 'workflow'`, `description`, `keepInputOpen: true` (args may follow). Work sessions list `scope: work` only; coding sessions list both. Unapproved/invalid → omitted (F16).
- **Submit intercept**: new `tryHandleWorkflowCommand` in `onSubmit` beside the `/loop` check (`index.tsx:1424-1438`, F17), backed by `web/src/lib/parseWorkflowCommand.ts` (clone of `parseLoopCommand.ts`): parses `/workflow <name> [arg1 arg2 …]`, maps positional args onto declared inputs (coerced by type), and if required inputs are still missing opens **`RunInputsDialog`** (small form generated from `inputs[]`). Then `runWorkflow(...)` — the raw slash text is **never sent as a chat message** (unlike `/loop`; no server-side slash parse exists or is needed).
- **Progress pill**: `WorkflowProgressPill` cloning `LoopStatusPill` exactly (F18): SSE case `'workflow_progress'` in `sse-reducer.ts` (beside `loop_status` at `:489`), store field `activeWorkflowExecution` in `useTeamStore/types.ts`, hydration line beside `index.ts:801` from the new history field, rendered with the chat status controls. Pill shows `"<name>: <node_id> (i/n)"`, a red state with the error on failure, and an ✕ → `stopExecution`.
- **Gate rendering**: expected to reuse the existing question UI (it's a real `QuestionAskedEvent`, F10). Verified early in M4; fallback is a `GateBanner` component fed by `workflow_progress(waiting_gate)` + `getExecution`.

### 9.2 Builder (Workflows screen)

- Route `/workflows` in `router.ts` (precedent `/scheduler`); screen layout: definition list (left) + editor (right).
- **Canvas**: new dependency `@xyflow/react` (nothing suitable exists — `RepoGraphSpatial.tsx` is force-directed physics, not a node/port editor; Monaco is already present for the YAML view). `WorkflowCanvas.tsx` registers custom node types:
  - `AgentNode` — header card = session lead (locked, tooltip "custom lead comes with direct execution"); subagent chips, added via a combobox cloned from `AgentForm.tsx`'s pattern and filtered to `role: member` blueprints (the `role` field at `AgentForm.tsx:407-418`); prompt edited in the side panel. **No tools picker** — each agent's tools come from its blueprint config; the side panel shows them read-only with a link to Agents settings.
  - `ToolNode` — tool combobox (registry + ready MCP names from the manifest endpoint); args as a JSON/form editor.
  - `CodeNode` — a `ToolNode` preset: language select `python | shell` (label notes JS runs via `shell` + `node`/`bun` — honest, F12) + a Monaco snippet editor bound to `args.code`/`args.command`.
  - `GateNode` — title/body/choices; each choice materializes a labeled output handle (edge `when`).
  - `SwitchNode` — value template; labeled output handles per case + default.
  - `InputNode` — question template; single output handle (no routing — pair with a Switch).
  - `NotifyNode` — title/message templates; pass-through handle.
  - `TransformNode` — key→template rows (add/remove row UI); pass-through handle.
  - `ForEachNode` — an xyflow **container** (body rendered as a child node with `parentId` + `extent: 'parent'`, one slot in v1); `items` template on the frame; "runs sequentially" hint badge (Phase 1).
  - Phase 2: `SubWorkflowNode` (workflow picker + inputs mapping), `WaitNode` (seconds, capped) — components land with Phase 2 but the YAML view already round-trips them from v1 (§4.4).
- `NodePalette` (drag sources), `NodeSidePanel` (full editing form for the selected node), `EdgeLabel` (shows/edits `when`).
- Tier-A additions from §4.5 ship with this milestone at near-zero cost: `StartNode`/`EndNode` (pseudo-nodes rendering `inputs[]`/`outputs:`), `NoteNode` (`ui:`-only sticky), the `If` preset, and tool presets (Web/Browser/Knowledge/PR/Worktree) as palette metadata over `ToolNode`.
- **Save flow**: explicit Save → `PUT` with `{graph}` (positions included under `ui`); server validates, returns canonical detail or 422 field errors → rendered as red badges on the offending nodes. **YAML toggle** shows `raw_yaml` in Monaco; saving from YAML sends `{raw_yaml}`; switching back re-renders the canvas from the parsed graph (auto-layout fills missing `ui` positions).
- **Approval**: after save, if unapproved, `ApprovalDialog` lists the manifest → `approveWorkflow(hash)`.
- Mobile: read-only list + Run button; no canvas.

---

## 10. Integration matrix (touched surfaces only)

| Subsystem | Integration |
|---|---|
| Work / Coding modes | Scope rules per §6.2; mode comes from the route (F19). |
| Projects | A coding session bound to a project already carries `extra_workspace_paths` into its turns; tool nodes get the workspace via `set_sandbox` (F12). |
| `/loop` | Untouched; the workflow `advance_cb` sits before the loop branch in the F1 chain. Both can't drive the same boundary: an active execution consumes it first. |
| Slash commands | One new FE-intercepted family (§9.1). No server-side slash parse. Command-body composition does **not** work (F17) — dropped from claims. |
| Queued messages | Suppressed mid-node via the attach-site skip (F8); land at node boundaries (§6.1). |
| Stop button | Works as-is for agent nodes (F9); pill ✕ covers inline nodes/gates (§6.5). |
| ask_user / plan mode | Gates are literal `ask_user` calls (F10). |
| MCP | `call_app_tool` with mapped errors (F14). |
| Skills/commands/snippets | Sibling file root (F15); no behavior change. |
| Sidebar / notifications / undo / compaction / attachments | Deliberately untouched — no run entity, no run session, nothing to badge or guard. |

---

## 11. Phasing and build order

### Phase 1 (MVP) — six milestones, each independently verifiable

- **M1 — Definition layer** (backend, no server changes): `workflows_fs.py`, `workflow/models.py`, `graph.py` (DAG + topo + edge semantics as pure functions), `template.py`, `policy.py` (hash + manifest + lint), builtin examples. *Done when*: unit tests validate/reject a corpus of YAMLs and the graph semantics table in §6.3 is covered by tests.
- **M2 — API CRUD + approval**: `routes/workflows.py` (all but `/run`/`/stop`), migration `00000020`, `workflow_approvals` wiring. *Done when*: API tests cover list/get/put/delete/approve incl. hash-mismatch 409 and workspace-root shadowing.
- **M3 — Runner core (headless nodes)**: `runner.py` + `nodes.py` for `tool`/`switch`/`transform`/`notify`, `ExecutionState`, execution/node-run rows, `workflow_progress` SSE, `/run` + `/stop` endpoints, busy-flag accessor. *Done when*: a tool→transform→switch→notify workflow runs to completion via `POST /run` against a live session — rows, SSE, and the desktop notification all verified.
- **M4 — Human + team nodes (`agent`/`gate`/`input`/`foreach`)**: `_try_emit_done` hook points + `set_workflow_hooks`, allowlist checks in `resolve_recipient`/`_spawn_locked`, pre-spawn, watermark capture + handoff listener, `QueuedMessageInjectionHook` skip, interrupt notify, gate + input via `AskUserService` (**first task: verify the question UI renders turn-less** — both choice and free-text; else `GateBanner`), `foreach` with per-iteration rows over both `tool` and `agent` bodies, per-node timeout. *Done when*: sequential `bug-triage` runs e2e in a live coding session; a mid-node user message lands at the boundary; Stop works during an agent node AND during a gate; an input node's free-text answer routes through a following switch; a 3-item foreach yields 3 iteration rows and an aggregated output.
- **M5 — FE trigger surface**: client + queries, slash-menu entries, `parseWorkflowCommand` + `onSubmit` branch, `RunInputsDialog`, `WorkflowProgressPill` + reducer case + hydration field (BE: history field lands here too). *Done when*: `/workflow bug-triage TICKET-1` from the composer runs with live pill progress and ✕ works during a gate.
- **M6 — FE canvas**: `@xyflow/react` dep, `WorkflowCanvas` + all Phase-1 node components (incl. the ForEach container and the Tier-A set: Start/End/Note/If/tool-presets) + side panel, `ui:` persistence + auto-layout, YAML toggle, `ApprovalDialog`, `/workflows` route/screen. *Done when*: build the §4.2 example on the canvas from scratch, save, approve, and run it; a foreach container round-trips canvas ⇄ YAML; a hand-written YAML with no `ui:` opens with sane auto-layout.

Exit criteria (Phase 1 overall): the four from v4 (canvas round-trip; inline run with no new session; unapproved not triggerable; coding-scope target prompt) **plus**: agent-node output capture demonstrably excludes a user message queued mid-node.

### Phase 2 — Execution quality + Tier C
`execution: direct` per agent node via `Agent.run()` (unlocks per-node `lead:`, true parallel branches + `foreach.concurrency`, schema-enforced `submit_result` output); the two pinned Tier-C kinds — `workflow` (sub-workflow, §6.4) and `wait` — plus their canvas components; richer switch conditions; scheduler trigger (maybe).

### Phase 3 — Unplanned / backlog
Webhook trigger, durable runs, budgets — considered and deliberately not built.

---

## 12. Risks and open questions

| Risk | Mitigation / honest limitation |
|---|---|
| Handoff capture depends on an in-process SSE listener (F4) | Fallback is always available (last assistant text after watermark); the listener is an optimization for structured output, not a correctness dependency. |
| Question UI may assume an active turn (gate rendering) | Flagged as the first thing M4 verifies; `GateBanner` fallback specified (§9.1). |
| No per-node lead in Phase 1 | Locked lead card keeps the canvas mental model intact; honest tooltip; Phase 2 unlocks it. |
| Sequential-only branches may surprise users who drew "parallel" fan-outs | Canvas renders branches with an ordering hint ("runs sequentially in Phase 1"); semantics are already branch-safe for Phase 2 concurrency. |
| MCP output shapes vary wildly | §4.3 shape rule (structuredContent → JSON-parse → `{"text": …}`) + fail-loudly dotted paths. |
| No crash recovery / gate lost on restart | Stated cut; same posture as `ask_user` today (F10). |
| Direct tool calls bypass the permission hook | By design, covered by mandatory manifest approval (§7.2). |
| Blueprint tool config can change after approval | The manifest pins blueprint *names*, not their tool lists — editing a blueprint in Agents settings changes what an approved workflow's agent nodes can do without re-approval. Accepted for now (human-present triggers; the same person owns both settings); revisit if unattended triggers ever land. |
| Open question | `switch`: equality + `in` only in v1 — revisit if real workflows need more. |
| Open question | Should the slash menu show unapproved workflows greyed-out? Needs a `disabled` field added to `SlashCommand` (F16 — doesn't exist); deferred, omission is the existing pattern. |

---

## 13. File-by-file change list (Phase 1)

**Backend — new**
- `app/workflow/__init__.py`, `models.py` (definition pydantic incl. all ten kinds — Phase 2 kinds validate but refuse to run, §4.4), `graph.py` (DAG/topo/edge semantics), `registry.py` (discovery + hash + manifest), `runner.py` (`WorkflowRunner`, `ExecutionState`, hooks, stop/interrupt), `nodes.py` (eight v1 handlers per §6.4: agent, tool, gate, switch, input, notify, transform, foreach), `template.py` (incl. `item`/`index` scope), `policy.py` (manifest, lint, approval check).
- `app/services/workflows_fs.py` (discovery per `commands.py:66-296`; atomic CRUD per `routes/skills.py:85-100,240-302`).
- `app/api/routes/workflows.py`, `app/api/schemas/workflows.py`.
- `app/agent/builtin_workflows/` (2 examples).
- `app/migrations/versions/00000020_create_workflows.py`.

**Backend — edits (function-level)**
- `app/agent/mode/team/team.py` — ① two hook call sites in `_try_emit_done` (capture before `_activate_queued_user_messages` at ~`:471`; advance after the queued branch, before `_activate_loop_message`) + module-level `set_workflow_hooks`; ② `turn_allowed_blueprints` field + check in `resolve_recipient` (`:1662-1688`); ③ same check in `_spawn_locked` (`:1366-1375`); ④ `runner.notify_interrupt` call in the interrupt path (`:756-765`); ⑤ small public accessor to set/clear `_has_active_turn` for inline-node stretches. (~50 lines.)
- `app/agent/mode/team/tools.py` — allowlist-aware message in `_recipient_error` (`:148-166`). (~5 lines.)
- `app/agent/mode/team/member.py` — conditional skip of `QueuedMessageInjectionHook` at `:946-953` when `runner.is_driving(session_id)`. (~3 lines.)
- `app/api/routes/team/chat.py` — `workflow_execution` field in the history response (beside `loop_status` at `:1143`). (~5 lines.)
- `app/api/app.py` — mount router (beside `:181`); `set_workflow_hooks(...)` at startup.
- `app/core/workspace_init.py` / `app/core/config.py` — workflows root; `WORKFLOWS_DIR`, `WORKFLOW_NODE_TIMEOUT_S`.

**Frontend — new**
- `web/src/api/client/workflows.ts`; types in `web/src/api/types.ts`.
- `web/src/queries/useWorkflowsQuery.ts` (+ `useWorkflowQuery`, `useExecutionsQuery`).
- `web/src/lib/parseWorkflowCommand.ts` (clone `parseLoopCommand.ts`).
- `web/src/routes/workflows.tsx`; `web/src/components/workflow/{WorkflowCanvas,NodePalette,NodeSidePanel,ApprovalDialog,RunInputsDialog,WorkflowProgressPill,GateBanner}.tsx` + `nodes/{AgentNode,ToolNode,CodeNode,GateNode,SwitchNode,InputNode,NotifyNode,TransformNode,ForEachNode,StartNode,EndNode,NoteNode}.tsx` (If + Web/Browser/Knowledge/PR/Worktree are palette presets, not components).
- Dependency: `@xyflow/react` (via bun — `bun.lock` is the only lockfile).

**Frontend — edits (function-level)**
- `web/src/components/TeamChatView/index.tsx` — ① workflow entries in the `slashCommands` merge (`:683-713`); ② `tryHandleWorkflowCommand` branch in `onSubmit` (`:1424-1438`); ③ progress pill rendering in the chat status controls.
- `web/src/stores/useTeamStore/sse-reducer.ts` — `case 'workflow_progress'` (beside `loop_status` at `:489`).
- `web/src/stores/useTeamStore/types.ts` — `activeWorkflowExecution` field (beside `activeLoop` at `:102`).
- `web/src/stores/useTeamStore/index.ts` — hydration from `history.workflow_execution` (beside `:801`).
- `web/src/router.ts` — `/workflows` route.

**Tests**
- `tests/workflow/` — models/graph/template/policy units (M1); runner state machine incl. boundary/queued ordering, allowlist, watermark capture, stop/interrupt (M3/M4).
- `tests/api/routes/test_workflows.py` — CRUD/approve/run/stop contracts (M2/M3).
- Extend `tests/agent/mode/team/test_team.py` — hook ordering in `_try_emit_done`, `resolve_recipient` allowlist, spawn allowlist.

---

## Appendix A — Review provenance

v2 (2026-07-08): three-lens adversarial review of the original durable-run design.
v3 (2026-07-09): all citations re-verified after a same-day mode rename; six design gaps closed. Technically solid, but solving the wrong product per the user.
v4 (2026-07-09): re-scope to the user's actual intent — canvas-first builder, inline in-chat execution, minimal footprint; enterprise apparatus cut on the user's explicit choice.

**v5 (2026-07-09)** is the implementation audit of v4. Three parallel code deep-dives (team mechanics; direct service/tool invocation; frontend plumbing) traced every mechanism v4 assumed to its exact function and returned a feasible verdict with these corrections now baked in: **(1)** there is no turn id — agent-node output capture uses a message-id watermark, and structured handoff output requires an in-process stream listener because artifacts are never persisted structurally; **(2)** `team_delegate` does not auto-spawn — the runner pre-spawns each node's roster via the public `team.spawn()` and a new `turn_allowed_blueprints` check lands at the single recipient-resolution choke point plus the spawn lock; **(3)** a per-node `lead:` is not implementable inline (turns always go to the session lead) — the field is rejected in v1 and the canvas lead card is locked; **(4)** v4's "parallel outgoing edges" contradicted one-session-one-turn execution — Phase 1 is now explicitly sequential-topological with precise edge/join/skip semantics; **(5)** `/workflow` is FE-intercepted with a dedicated run endpoint (the `/loop` posts-raw-text pattern is unnecessary here), which also falsifies v4's "command-body composition for free" claim — dropped; **(6)** gates flatten title/body into `ask_user`'s `{question, options}` shape, and the runner must register the service in the module-global registry for the reply endpoint to find it; **(7)** MCP results have no structured fast path — a node-output shape rule (structuredContent → JSON-parse → text) was added; **(8)** one `stop` endpoint returned (v4 claimed none needed; gates and tool nodes have no turn for the Stop button to interrupt); **(9)** canvas positions now persist under an engine-ignored `ui:` block with auto-layout for hand-written files; **(10)** trigger-time input collection is specified (positional slash args + a generated form dialog). The v4 claim that `commands.py` provides CRUD was also corrected (discovery only; CRUD precedent is the skills routes). The plan now names function-level integration points on both sides and a six-milestone build order with per-milestone done-when criteria.

Post-v5 additions: a tiered node palette (§4.5) grounded in the builtin-tool inventory, then — per user direction — **all three tiers committed into scope**: Tier A (Start/End/Note/If/tool-presets) ships with M6 as FE-only sugar; Tier B became four first-class v1 engine kinds (`input`/`notify`/`transform`/`foreach` — feasibility-checked, notably `ask_user`'s native free-text answers making `input` the gate handler with empty options, and `foreach` fitting Phase 1's sequential semantics exactly, incl. a per-iteration `iteration` column on node runs); Tier C (`workflow`, `wait`) is pinned in the v1 schema (validated at save, refused at run until Phase 2) so definitions don't churn, with parallel confirmed as an execution upgrade rather than a node kind. Also folded in per user direction: **agent nodes carry no `tools:` field** — tools are each blueprint's own configuration (Agents settings), and node-level tool choice exists only on `tool`/MCP nodes. This matches the user's model and simultaneously removed a v5 latent gap: the schema had a `tools:` field on agent nodes that nothing in §6.4 could enforce (lead-driven turns have no per-turn tool channel until Phase 2 direct execution). The destructive lint now resolves agent-node effective tools from blueprint files at save time, and the manifest pins blueprint names with tools shown informationally.
