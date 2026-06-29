# Claude Code vs EvoFlux — Analysis & Improvement Plan

> Source: codeaashu/claude-code (leaked Anthropic source, 2026-03-31)  
> Date: 2026-06-29

---

## 1. Architecture Comparison

| Dimension | Claude Code | EvoFlux |
|---|---|---|
| **Delivery** | CLI binary (single process) | Tauri desktop shell + FastAPI sidecar + React web UI |
| **Language** | TypeScript (strict), Bun runtime | Python 3.12 backend, TypeScript 5.9 frontend |
| **UI Layer** | React + Ink (terminal rendering) | React 19 + Tailwind v4 (real browser UI) |
| **Core Engine** | `QueryEngine.ts` (~46K lines) monolith | `Agent` class + modular hook pipeline |
| **Tool count** | ~40 tools | ~30 builtin tools |
| **Skills** | 16 bundled | **40+ builtin skills** ✅ |
| **Multi-agent** | Coordinator + Teams + InProcessTeammate | Team manager (multi-agent with roles) ✅ |
| **Code intelligence** | LSPTool (live lang server) | **Code knowledge graph** (tree-sitter + semantic) ✅ |
| **Memory** | CLAUDE.md hierarchy (project/user/team) | Wiki + memory_vector + dream scheduler |
| **Context compression** | `/compact` (user-triggered) | `SummarizationHook` (auto at token threshold) |
| **Permission system** | Wildcard rules + plan mode + ML auto-mode | Wildcard rules (ask/allow/deny) |
| **Background tasks** | 6 task types (shell, agent, remote, dream…) | Dream scheduler + team_manager |
| **Scheduling** | `CronCreateTool` + `ScheduleCronTool` | `schedule.py` tool + DreamScheduler ✅ |
| **MCP** | Client + **Server mode** (exposes itself as MCP server) | Client only |
| **Diagnostics** | `/doctor` command (env health) | ❌ missing |
| **Cost tracking** | `/cost` per-session display | provider_usage service (DB only) |
| **Git worktree tools** | `EnterWorktreeTool` / `ExitWorktreeTool` | CodingWorkspace model (no agent tools) |
| **IDE bridge** | Bridge system (VS Code, JetBrains) | IS the desktop UI — no bridge needed |

---

## 2. What Claude Code Does Better

### 2.1 Plan Mode — Safest UX pattern for destructive tasks
Claude Code's `EnterPlanModeTool`/`ExitPlanModeTool` lets the agent explicitly enter a "no-execution" planning phase, list every planned step with expected file/shell changes, get **batch user approval once**, then execute. This dramatically reduces accidental overwrites.

EvoFlux has the permission `ask` action but no concept of **agent-initiated plan mode** — the agent either proceeds or waits for individual confirmations.

### 2.2 LSP Integration
`LSPTool` queries a running language server for live diagnostics:
- go-to-definition, find-references, hover types
- real-time error/warning list (not stale parsed AST)
- semantic rename via language server

EvoFlux's code graph is better for *codebase-wide* topology queries (call graphs, class hierarchies) but lacks **live, per-edit diagnostics**.

### 2.3 Concurrency Safety Declaration on Tools
Every Claude Code tool implements:
```typescript
isConcurrencySafe(input): boolean  // can run in parallel with other tools
isReadOnly(input): boolean         // non-destructive, skip permission prompt
```

EvoFlux's `tool_dispatch.py` runs all tool calls in parallel via `asyncio.gather` with no per-tool safety flag. This can cause races (e.g. two parallel `edit` calls on the same file).

### 2.4 Structured Background Task System
Claude Code has 6 distinct task types (LocalShellTask, LocalAgentTask, RemoteAgentTask, InProcessTeammateTask, DreamTask, LocalMainSessionTask) with a full CRUD API (`TaskCreateTool`, `TaskGetTool`, `TaskListTool`, `TaskOutputTool`, `TaskStopTool`).

EvoFlux has `todo_manage` (planning list) and `schedule_task` (cron) but no way for the agent to **spawn a background shell command** and poll its result while continuing with other work.

### 2.5 User-Triggered Context Compact
Claude Code's `/compact` command explicitly compresses conversation history, shows the summary to the user, and awaits confirmation. EvoFlux's `SummarizationHook` fires silently at a token threshold — users can't tell it happened and can't trigger it proactively.

### 2.6 Environment Diagnostics (`/doctor`)
Runs a comprehensive health check: API connectivity, model availability, MCP server status, permissions, disk space, tool dependencies. EvoFlux has no equivalent. Users debugging "why won't the agent use tool X" have no guided diagnostic path.

### 2.7 MCP Server Mode
Claude Code can expose its own tools as an MCP server (`src/entrypoints/mcp.ts`), meaning other agents or Claude Desktop can call EvoFlux tools directly. EvoFlux is MCP-client-only — it can't be orchestrated by external agents.

### 2.8 Per-Session Cost Visibility
`/cost` shows exact token counts and dollar cost for the current conversation turn and session total. EvoFlux stores `provider_usage` in the DB but there's no session-level cost panel in the UI.

---

## 3. Where EvoFlux Leads

| Area | EvoFlux Advantage |
|---|---|
| **Skills library** | 40+ curated skills vs 16 in Claude Code |
| **Code knowledge graph** | Semantic code search, call-graph traversal, incremental indexing — not in Claude Code |
| **Desktop UI** | Full browser-quality UI, file diff viewer, workspace panel — vs terminal text only |
| **Multi-provider** | Supports Anthropic, Google, OpenAI, Ollama, etc. |
| **Wiki / long-term memory** | Dream scheduler consolidates sessions into semantic wiki |
| **REST API** | Full HTTP API for programmatic integration — Claude Code is CLI-only |
| **Browser agent** | `browser_use` tool for real browser automation |
| **Multi-modal** | Document intake (PDF, DOCX, images) with markitdown |
| **Agent config as `.md` files** | Human-readable, versionable agent definitions |

---

## 4. Improvement Plan (Prioritised)

### P0 — High impact, small scope

#### P0.1: Tool concurrency safety flags
**Problem:** `tool_dispatch.py` runs all tool calls from one LLM turn in parallel regardless of type. Two parallel `edit` calls on the same file will race.

**Plan:**
- Add `concurrency_safe: bool = False` and `read_only: bool = False` fields to `Tool` in `app/agent/tools/registry.py`.
- Update `tool_dispatch.py` to partition tools: run `concurrency_safe=True` calls in parallel; serialise `concurrency_safe=False` calls sequentially (or run them all serial for safety-first default).
- Tag all existing builtin tools appropriately (`read`/`grep`/`glob`/`ls`/`date`/`web_fetch`/`web_search`/`memory_search`/`code_*` → concurrency_safe=True; `edit`/`write`/`patch`/`rm`/`shell`/`python` → False).

#### P0.2: Per-session cost panel in UI
**Problem:** Users have no visibility into token spend per conversation.

**Plan:**
- The backend already persists `provider_usage` per session. Add a `GET /api/sessions/{id}/cost` endpoint returning `{input_tokens, output_tokens, estimated_usd}`.
- Add a small cost badge to the session header in `TeamChatView` (similar to Claude Code's `/cost` display). Refresh after each turn via TanStack Query.

#### P0.3: Environment diagnostics page
**Problem:** No guided path for "why is X not working".

**Plan:**
- Add `GET /api/health/diagnostics` endpoint that checks: provider API reachability, MCP server connectivity, disk space (workspace + DB), code graph index state, embedding model availability.
- Add a `DiagnosticsPanel` reachable from settings or the header. Each check shows pass/fail/warn with a one-line fix hint.

---

### P1 — Medium impact, medium scope

#### P1.1: Plan Mode
**Problem:** The agent can execute destructive shell/file operations without the user seeing what's coming.

**Plan:**
- Add a `PlanState` to `AgentState` / session metadata: `{active: bool, planned_steps: list[str]}`.
- Add two tools: `enter_plan_mode` (sets flag, returns ack) and `exit_plan_mode` (clears flag).
- In `tool_executor.py`, when `plan_mode=True`, intercept `shell`/`edit`/`write`/`patch`/`rm` calls: record the call as a planned step in `PlanState` instead of executing it. Return `"[PLAN] Recorded"` as result.
- Add a hook `plan_approval.py` that, after `exit_plan_mode` is called, SSEs a `plan_approval_request` event to the frontend with all planned steps. Frontend shows a diff-preview modal with approve/reject. On approve, replays all planned calls.
- Add plan mode indicator to `TeamChatView` header.

#### P1.2: User-triggered `/compact`
**Problem:** Context compression happens silently; users can't trigger it proactively before a long task.

**Plan:**
- Add a `POST /api/sessions/{id}/compact` endpoint that triggers the `SummarizationHook` logic immediately, regardless of token count.
- Add a "Compact context" button to the session overflow menu.
- SSE a `summarization_start`/`summarization_end` event (these already exist in the hook schema) so the UI can show the summary inline in the chat as a collapsible message.

#### P1.3: Background shell task tool
**Problem:** Agent blocks on long-running commands (test suites, builds) and can't multi-task.

**Plan:**
- Add `shell_bg` tool: runs a command in a detached subprocess, stores PID + output path in session metadata, returns a `task_id`.
- Add `shell_bg_status` tool: returns `{running: bool, exit_code, tail: str}` for a given `task_id`.
- Add `shell_bg_wait` tool: blocks until the task completes (with timeout).
- Backend: reuse `shell_service.py` + a `BgTaskRegistry` similar to `IndexJobRegistry`.

#### P1.4: Git worktree agent tools
**Problem:** The agent works directly on `main`/working branch; risky changes can't be isolated.

**Plan:**
- Add `enter_worktree` tool: creates a new git worktree at a temp path, registers it in `coding_workspaces`, switches the agent's `workspace_root` to the new worktree, returns the worktree path.
- Add `exit_worktree` tool: optionally merges changes back (or just reports diff), removes worktree, restores original `workspace_root`.
- Reuse existing `CodingWorkspace` model (`kind="worktree"`, `managed=True`, `source_path=...`).

#### P1.5: LSP integration (live diagnostics)
**Problem:** Code graph gives structural analysis but can't surface real-time type errors or go-to-def.

**Plan:**
- Add `app/services/lsp/` package with `LspManager` that starts/stops language servers per workspace (pylsp for Python, ts-ls for TypeScript via node).
- Add `lsp_diagnostics` tool: returns current errors/warnings for a file from the running language server.
- Add `lsp_definition` tool: returns definition location(s) for a symbol at a given file:line:col.
- Add `lsp_references` tool: returns all reference locations.
- These complement (not replace) the code graph — graph for topology, LSP for live correctness.

---

### P2 — Larger scope / higher risk

#### P2.1: MCP Server Mode
**Problem:** EvoFlux tools can't be consumed by external agents (Claude Desktop, other EvoFlux instances, etc.).

**Plan:**
- Add `app/cli/mcp_server.py` (new entrypoint) that starts a stdio MCP server.
- Expose a configurable subset of agent tools as MCP tools (at minimum: `shell`, `read`, `edit`, `web_search`, `code_search`).
- Register in `app/cli/main.py` as `evoflux mcp-server`.
- Add to `seed/mcp.json` example so other agents can discover it.

#### P2.2: Auto-memory extraction from conversations
**Problem:** Dream scheduler does wiki consolidation but only runs on a schedule; interesting facts from a session aren't captured until the next dream run.

**Plan:**
- Add `extractMemories` service: after each session closes (or after N turns), run a small LLM pass over the last K messages to extract structured "facts" (user preferences, project conventions, decisions made).
- Write extracted facts to the appropriate wiki topic file immediately.
- Add a `MemoryExtractionHook` that fires at session end.

#### P2.3: Prompt suggestions after response
**Problem:** Users often need to continue the task but don't know what to ask next.

**Plan:**
- After each assistant message, run a secondary low-latency LLM call to generate 2-3 follow-up prompt suggestions.
- Stream them as a `prompt_suggestions` SSE event.
- Render as clickable chips below the last assistant message in the chat UI.

---

## 5. Summary Priority Matrix

| Item | Impact | Effort | Risk | When |
|---|---|---|---|---|
| P0.1 Tool concurrency flags | High | Low | Low | Now |
| P0.2 Cost panel UI | High | Low | Low | Now |
| P0.3 Diagnostics endpoint + panel | Medium | Medium | Low | Now |
| P1.1 Plan mode | High | Medium | Medium | Next sprint |
| P1.2 User-triggered compact | Medium | Low | Low | Next sprint |
| P1.3 Background shell tasks | High | Medium | Low | Next sprint |
| P1.4 Git worktree tools | Medium | Medium | Low | Next sprint |
| P1.5 LSP integration | High | High | Medium | Future |
| P2.1 MCP Server mode | Medium | Medium | Low | Future |
| P2.2 Auto memory extraction | High | Medium | Low | Future |
| P2.3 Prompt suggestions | Medium | Medium | Low | Future |

---