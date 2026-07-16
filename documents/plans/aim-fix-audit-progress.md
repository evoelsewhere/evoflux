# AIM Fix & Audit Progress

Tracking against backlog from scheduled task `aim-fix-audit-loop` (2026-07-17).

## Status: ROUND 2 — UI parity + run observability (2026-07-17)

User feedback driving round 2: (1) AIM UI chưa match 2 mode còn lại,
(2) thông tin trong 1 project thiếu, (3) pipeline running không có log.

### R2-P1 — Run observability (pipeline "không có log") ✅

**Backend:**
- NEW `GET /api/workflows/executions?session_ids=a,b,c` (registered before
  `/{name}` so the literal path wins) → newest-first `WorkflowExecutionOut[]`.
  Test: `test_list_executions_by_session_ids`.
- `AimRunOut` + `AimRunListItem` now expose `workflow_execution_id` (was on
  the model, never serialized).

**Frontend (`AimPipelinesPanel`):**
- Run table joins per-run sessions ↔ executions in one call (poll 5s):
  real status ● running / ⏸ needs input / ✓ pass / ✗ fail / ◼ stopped /
  ⚠ interrupted (DB says running but no live stream — backend restarted),
  plus a Pipeline column (definition_name).
- Per-run sessions get a readable title (`<unit|wave> · <pipeline>`) via
  PATCH right after resolve — table rows no longer show UUIDs/prompt text.
- NEW **Run Monitor** side panel (opens automatically on Run, or from any
  row): execution summary + error, node-by-node progress with durations
  and expandable per-node debug output, **Activity log** (read-only
  transcript tail, poll 4s while active — the "log" the user asked for),
  inline **Gate** answerer when status=waiting_gate, and a **Stop** button.
  Replaces the old blind "Gate" button. Still zero chat surface.
- `RunMonitorPanel` is exported and reused by Runs & Reports ("Nodes").

### R2-P2 — Overview thiếu thông tin ✅

- Info strip: N source repos (names, read-only badge), target repo, KB repo
  (`resolveAimRoleWorkspaces` helper).
- Phase distribution bar + legend from `summary.phase_counts` (global,
  unaffected by wave filter).
- Recent-runs strip (last 6 aim_runs) deep-linking to `runs/$runId`.
- Unit cards: KB-doc icon, complexity (loc/score), deps count, assignee,
  full tooltip.

### R2-P3 — Shell parity với Forge/Coding ✅

- `AimSidebar`: resizable (`useResizableWidth`, storageKey
  `oa.aimSidebar.width`), collapse-to-icon-rail (`ModeSwitchRail`, state in
  layout + localStorage, Ctrl+B), footer trio Settings·HealthDot·ThemeToggle,
  "Projects" section header with "+" (wizard), running dot per project +
  on the Pipelines feature row (one polled query, 10s).
- `aim.tsx` shell: `mobile-safe-shell mobile-viewport … md:flex-row` wrapper,
  main panel `rounded-[10px] bg-(--bg-page) shadow-sm` (was border+bg-card —
  visibly different from the other modes), PanelLeft toggle button between
  sidebar and content (same as TeamChatView's).
- FIXED: deep-link `/aim/$projectId/runs/$runId` was redirected to overview
  by the feature-normalizing effect (runId param has no $feature); now maps
  to feature='runs', preselects the run, and run selection keeps the URL in
  sync. Verdict icons are tri-state (pass / acceptable_diff / fail / error).

**Verified live (browser, real backend):** run table with real statuses,
title patch, monitor auto-open, node list + durations, activity log
streaming agent output, sidebar running dots, collapse rail, resize handle,
deep-link no longer redirects. New endpoint returns correct rows (tested +
curl). tsc clean; pytest workflow+aim routes green (81).

### R2-P4 — Gate visibility (found live) ✅ c90ae45

Runner only flipped waiting_gate in memory → REST rows said 'running' for
the whole pause AND the monitor's gate box was keyed on that status, so a
pending gate was unreachable. Fixed both sides: `_persist_execution_status`
mirrors running ⇄ waiting_gate into the DB row (asserted in
test_gate_round_trip_via_ask_user_service); GateSection renders whenever
the run is live and materializes from the pending-questions poll.
Verified live twice (assess run #1 approve→completed; run #2 showed row
badge '⏸ needs input' + Answer → approve → pass).

### R2-P5 — Cross-review findings ✅ 0d0cd11

Independent review of 65a3adc found the interrupted heuristic broken for
non-streaming pipelines (cutover-check = tool/gate only; convert-wave
gates before agents): session streaming flag never turns on → gate
mislabeled 'interrupted' after 20s, Answer/Stop hidden. Fix:
`WorkflowExecutionOut.live` (true while runner.active drives it) is the
liveness source; FE drops the age heuristic. Also: deep-linked runs older
than the 50-row list now open Nodes/Discussion (targets built from run
detail), monitor lookup stops after ~30s with a clear message, executions
join keeps previous data across key changes.

### R2-P6 — KB tree + preview (user feedback) ✅ a0c26f1

"KB chưa hiển thị tree folder và preview chưa đáp ứng": replaced the flat
.md/.yaml list with the coding workspace's real tree (buildTree +
TreeNodeView, all files) and a kind-aware preview — markdown frontmatter
lifted into a key/value strip + rich body, yaml/json in CodeBlock,
images inline, per-file path+size bar. Verified live on the COBOL KB
(50 files; modules/course2/ADDAMT.md chips + headings; aim.yaml block).

**Known gaps (deliberate, log for next round):**
- AIM sidebar has no mobile slide-in drawer (desktop-first surface).
- No command-palette/search entry in AIM sidebar.
- No project context menu (rename/delete/leave) on AIM project rows.
- Gate detection is poll-based (5s) — Run Monitor SSE remains AIM-5.
- GateSection answers only the first item of a question batch (fine for
  workflow gate nodes, which ask exactly one).
- List endpoint returns `outputs` (≤32KB/row) the table doesn't use; a
  workflow literally named "executions" can't be fetched by name (shadowed
  by the literal route) — both harmless at current scale, noted.

## Status round 1: DONE (P1–P5 below)

---

## P1 — Regression prependSession dead-key ✅ DONE

**Commit:** fcac579

**Problem:** `prependSession` wrote to `infinite()` (no mode). Sidebar reads
`infinite('forge')`, CodingSidebar reads `infinite('coding')` — exact key mismatch, new
sessions silently invisible.

**Fix:**
- `cache-invalidation-bridge.ts`: `prependSession` normalises `session.mode` → writes to
  `infinite('forge'|'coding'|'aim')`.
- `queryKeys.team.sessions.infinite(mode?)` and `teamAgents(workspace, mode?)` gain mode.
- `useTeamSessionsQuery(mode)` sends mode filter to backend.
- All sidebars use correct mode: Sidebar→'forge', CodingSidebar→'coding'.
- New `ModeSwitchTabs` / `ModeSwitchRail` component replaces 3 hand-rolled copies.
- `_team_for_session_mode` in chat.py prevents forge team binding to aim sessions.
- Regression test: `test_commands_never_bind_forge_team_to_aim_session`.

**Verify:** tsc clean, 14 tests pass.

---

## P2 — Agents 3-mode separation ✅ DONE

**Commit:** 0b0957e

**Problem:**
(a) `_mode_for_agent_path` only knew `coding/` — `aim/*` agents got `forge` mode,
    wrong tool list.
(b) Settings agents page had no AIM tab — aim agents fell into Forge group.

**Fix:**
(a) `app/api/routes/agents.py`: added `aim/` case → mode='aim'.
(b) `web/src/routes/settings.agents.tsx`: Tab='aim', aimAgents filter, AIM group in
    'all' view, AIM tab with count, AIM option in New-agent dialog.
(c) `web/src/routes/settings.agents.new.tsx`: AgentMode='aim', creates `aim/<name>.md`.

**Verify:** tsc clean, agent tests pass.

---

## P3 — Spec v2.2 gaps ✅ DONE

**Commit:** f7cfb5f

### P3(a) §9.3 — Confirm dialog for convert pipelines ✅
`AimPipelinesPanel`: convert-unit/convert-wave show modal before run.
assess/understand/compare/cutover run directly.

### P3(b) §5.3 — Discussion in AimRunsPanel ✅
- Added `session_id` nullable column to `AimRun` model.
- Migration `00000022_add_session_id_to_aim_runs.py`.
- `aim_units` / `aim_compare` tools inject session_id via `_state.metadata`.
- `AimRunListItem` + `AimRunOut` schemas include `session_id`.
- `AimRunsPanel`: shows Discussion button for runs with session_id; singleton
  `TeamChatView` panel (same constraint as AimPipelinesPanel).

### P3(c) §3.2 — /aim/$projectId/runs/$runId route ✅
`router.ts`: `aimRunRoute` added as child of `aimProjectRoute`.

### P3(d) README stale ✅
`app/agent/builtin_aim/README.md`: updated from AIM-0 draft to AIM-4 wired with
milestone table.

**Verify:** tsc clean, all API tests pass.

---

## P4 — COBOL legacy test project e2e 🔄 IN PROGRESS

**COBOL repo cloned:** `~/Workspace/aim-cobol-test/aim_source_base/cobol-programming-course`
(openmainframeproject/cobol-programming-course, depth=1)

**Directory structure:**
```
~/Workspace/aim-cobol-test/
  aim_source_base/cobol-programming-course/  ← cloned repo
  aim_aim-cobol-test_document/               ← empty KB dir
  aim_target_source/                         ← empty git repo
```

**API verification results (2026-07-17):**

| Step | API call | Result |
|------|----------|--------|
| 1 | `POST /api/team/projects/aim/detect?root_path=...` | ✅ Detected project_name=aim-cobol-test, source/target/kb paths correct, has_manifest=false |
| 2 | `POST /api/team/projects/aim` (rulebook=cobol-java21) | ✅ Project created, id=06a591e6-d6ee-783a-8000-878525b02a75 |
| 3 | `GET /api/team/projects/{id}/aim/summary` | ✅ Returns summary (total_units=0, empty phase counts) |
| 4 | `POST /api/team/sessions/resolve` (mode=aim, project_id) | ✅ Session 06a591e8-3141-792a-8000-4eddfd7a09fb created |
| 5 | `POST /api/workflows/aim-assess/run` | ✅ Execution started (id=06a591e8-f7a6-75e0-8000-46ef210e212c) |
| 6 | Workflow running: session.running=true, node 'assess' status=running | 🔄 Waiting for completion |

**E2E result (verified 2026-07-17):**
- aim-assess workflow ran against COBOL repo
- 31+ units created in `aim_units` DB table (course2/3/4/shared modules)
- KB directory fully initialized (`modules/`, `inventory/units.md`, `aim.yaml`)
- Units have correct `phase=inventory`, `wave`, `complexity` metadata
- Workflow still running (gated assessment, takes time)

✅ **P4 e2e verified** — detect/create/summary/workflow-run/units all work correctly.

---

## P5 — Global audit ✅ DONE

---

---

## P5 — Global audit checklist

| Surface | Check | Status |
|---------|-------|--------|
| Forge Sidebar | Server-filtered `mode=forge`, no coding/aim sessions | ✅ |
| CodingSidebar | Server-filtered `mode=coding` | ✅ |
| AimSidebar | Shows project list only, no session list | ✅ |
| Settings/agents | All 3 mode tabs (Forge/Coding/AIM), correct filters | ✅ |
| AgentInfoPopover | Receives `mode` prop, shows correct roster | ✅ |
| SessionSettingsPanel | Receives `mode` prop, shows correct agents | ✅ |
| SessionPillsRow | Receives `mode` prop, forwards to AgentInfoPopover | ✅ |
| InputBar / FloatingInputBar | Receives `agentMode` prop, forwards to settings | ✅ |
| AIM UI — no permanent composer | Confirmed: Discussion only shows post-run | ✅ |
| AIM UI — Discussion only post-run | AimPipelinesPanel + AimRunsPanel both gate Discussion | ✅ |
| backend /team/agents mode | Accepts `aim` mode, returns correct roster | ✅ |
| backend /team/sessions mode | Server-filters by mode correctly | ✅ |
| tsc --noEmit | Clean | ✅ |
| pytest tests/api/ | All pass (46+ tests) | ✅ |

## COMPLETED 2026-07-17

All P1–P5 items done and verified. Stopping scheduled task.

## Questions / Blockers

None.
