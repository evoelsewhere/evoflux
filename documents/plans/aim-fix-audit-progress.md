# AIM Fix & Audit Progress

Tracking against backlog from scheduled task `aim-fix-audit-loop` (2026-07-17).

## Status: IN PROGRESS

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

**Next:** Wait for aim-assess to complete, then verify units in KB and aim_units table.

---

## P5 — Global audit ⏳ PENDING (after P4 complete)

---

## Questions / Blockers

None currently. P4 step 6 is awaiting workflow completion (agent doing real work).
