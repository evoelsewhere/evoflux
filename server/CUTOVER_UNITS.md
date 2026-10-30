# Cutover units

Every FastAPI route prefix and every lifespan background service is in exactly
one unit. A unit flips between `python`, `shadow` and `rust` as a whole, in one
`server/routing.toml` change, together with `EVOFLUX_DISABLE_SERVICES` for its
services (design §3.1). Routes that share in-memory state with code that stays
in Python must be in the same unit, because Rust never calls Python (design §3).

`server/routing.toml` is the source of truth for the assignment.
`scripts/migration/check_board.py` fails when this file and `routing.toml`
disagree, when a route FastAPI registers has no unit, or when a service is
missing or listed twice.

Evidence below comes from reading `app/api/app.py`, `app/api/routes/` and the
`app/services/` modules they call, at v3.1.1. "Shared" means a module-level
dict, lock, cache or manager object that another part of the sidecar also uses
in-process (agent tools, hooks, the team manager, the stream store).

## Units

| unit | phase | what it holds |
|---|---|---|
| `edge-stateless` | 1 | routes that read files or compute and keep no in-process state |
| `observability` | 1 | observability reads over the OpenTelemetry JSONL files, plus their retention job |
| `import` | 2 | importing conversations from other tools into the database |
| `remote-access` | 2 | remote use: embedded tailnet node and the single-device claim |
| `agent-runtime` | 3 | the agent loop and everything that shares its in-memory state |
| `platform-meta` | 4 | FastAPI's own docs, the Python process metrics and the packaged web UI mount |

`agent-runtime` holds most of the API (see
[Split candidates](#split-candidates)). That is what the code requires today,
not a planning choice: the agent tools, hooks and the team manager run in the
Python process until the agent loop itself moves, and they import the same
service singletons the routes use.

## Route prefixes

The longest matching prefix wins. `/api/health/live/**` is carved out of
`/api/health/**`.

| route | unit | pinned by |
|---|---|---|
| `/api/health/live/**` | edge-stateless | nothing: `health.py` `live()` answers without touching `team_manager`, the database writer or any lock |
| `/api/quote/**` | edge-stateless | nothing: `quote_service.get_quote_of_the_day` is a pure function |
| `/api/commands/**` | edge-stateless | nothing shared: `services/commands.py` discovers command files through an mtime-keyed `lru_cache` that revalidates against the files, so a Python copy and a Rust copy cannot go stale against each other; the agent's `parse_slash_invocation` is a pure function |
| `/api/snippets/**` | edge-stateless | nothing shared: `services/snippets.py` uses the same mtime-keyed discovery cache |
| `/api/observability/**` | observability | files only: `observability_service` reads the JSONL written by `core/otel.py` through DuckDB. The writers (`_span_writer`, `_metric_writer`) stay in Python and are only read through files |
| `/api/import/**` | import | database only: `import_service` and `services/importers/*` write `ImportJob`, `ChatSession` and `SessionMessage` rows and keep no module state |
| `/api/remote-use/**` | remote-access | `remote_use_service._embedded_manager` (the tailnet child process) and the single-device `claim` lock that `core/desktop_auth.py` takes when a remote request arrives. Both must be owned by whoever authenticates remote requests |
| `/metrics` | platform-meta | the Prometheus registry of the Python process (`core/metrics.py`) |
| `/openapi.json` | platform-meta | FastAPI's generated schema of the whole Python route table |
| `/docs` | platform-meta | FastAPI Swagger UI, built from `/openapi.json` |
| `/docs/oauth2-redirect` | platform-meta | FastAPI Swagger UI helper |
| `/redoc` | platform-meta | FastAPI ReDoc, built from `/openapi.json` |
| `/**` | platform-meta | the packaged web UI: `static_web.mount_web_ui` adds a `Mount("/")` catch-all (SPA fallback to `index.html`) only when a `web/dist` bundle exists, after every router. The checks refuse to let it cover an `/api` route |
| `/api/team/**` | agent-runtime | `team_manager` (live teams, session-to-team map), `stream_store` (SSE frames per running session), `webbridge_manager` (extension connections, policy cache), `terminal_manager`, `lsp_manager`, `change_set_service._change_sets`, `problems_service._problems`, `motion_review_service._pending`, `office_runtime`, and the process and preview registries of the `process` and `preview` agent tools. Detail per route module below |
| `/api/health/**` | agent-runtime | `/ready` and `/diagnostics` read `team_manager.validate_agents_dir`, `team_manager.has_active_team_turn` and `mcp_manager.list_status`; `/diagnostics/actions/db_reclaim` checks for an active team turn |
| `/api/diagnostics/**` | agent-runtime | `team_manager.current_team` and `mcp_manager.server_names` |
| `/api/agents/**` | agent-runtime | `core/agent_settings.py` `lru_cache`, the tool registry, and `app.conductor.agent_runtime` managed-agent state |
| `/api/skills/**` | agent-runtime | `core/skill_settings.py` `lru_cache` and `team_manager.invalidate_skill_cache`, called by `skills_service` after every change |
| `/api/plugins/**` | agent-runtime | `plugin_mcp_runtime` (plugin-provided MCP servers) and `team_manager.invalidate_skill_cache` |
| `/api/mcp/**` | agent-runtime | `mcp_manager` (live MCP connections and their tools, used by the agent loop in-process) and `plugin_mcp_runtime` |
| `/api/settings/**` | agent-runtime | provider and model registries (`model_registry` `lru_cache`, `plugin_registry`), `conductor_service` (15 uses, `/api/settings/conductor/*`), `webbridge_manager.reload_policy` (`/api/settings/webbridge*`). The remaining settings files are read fresh each time and could split out later |
| `/api/auth/**` | agent-runtime | `plugin_registry.find_provider_plugin`: provider login flows come from loaded Python provider plugins |
| `/api/wiki/**` | agent-runtime | `services/wiki._thread_write_lock`, shared with the `note` tool, `memory_extraction` hook, `dream` and `memory`, which write the same wiki files in-process |
| `/api/scheduler/**` | agent-runtime | `task_scheduler`, which dispatches through `team_manager` (design §3.1) |
| `/api/dream/**` | agent-runtime | `dream_scheduler` (held in `app.state`) and `services/dream.py`, which builds an agent and provider in-process (design §3.1) |

### `/api/team` by route module

All of these answer under `/api/team/**`, so they are one unit. The column shows
what pins each module, so a later shared PR can see which could split.

| route module (`app/api/routes/team/`) | paths | pinned by |
|---|---|---|
| `chat.py` | `chat`, `leads`, `agents`, `commands`, `sessions`, `{session_id}/history`, `side-chat`, `stream`, `goal`, `workspace/browse`, `workspace/tree`, `workspace/validate` | `team_manager`, `stream_store`, `agent_service`, `goal_service`, `chat_service`: the ingress, the SSE stream and the agent loop (design §3.1) |
| `webbridge.py` | `webbridge/**` | `webbridge_manager` (44 uses), `stream_store`, the tool registry, `interactive_message_service` |
| `files.py` | `workspace/files`, `{session_id}/files`, `workspace/status`, `workspace/watch`, `workspace/lsp`, `workspace/git-diff`, previews, uploads, media | `stream_store.running_session_ids`, `lsp_manager`, `snapshot_service` (also used by `chat_service` and `shell_service`), `team_manager.current_team_for_session` |
| `git.py`, `git_ai.py`, `worktrees.py`, `reviews.py`, `projects.py` | `workspace/git`, `workspace/worktrees`, `reviews`, `projects` | `git_ops` per-repository `asyncio.Lock`s, also taken by the `pr` agent tool; `coding_workspace_service`, used by the `worktree`, `pr` and `code_reviews` tools; `change_set_service` |
| `change_sets.py`, `editor.py`, `problems.py` | `workspace/change-sets`, `workspace/editor`, `workspace/problems` | `change_set_service._change_sets`, `problems_service._problems`; the latter is written by the `problem_capture` and `post_edit_diagnostics` hooks |
| `terminal.py`, `processes.py`, `preview.py` | `{session_id}/terminal(s)`, `processes`, `preview` | `terminal_manager`; `process_manager`, which lists the `process` and `preview` tools' registries (`stop_all_processes`, `stop_all_servers`) |
| `browser.py`, `computer.py` | `browser`, `{session_id}/browser`, `{session_id}/computer` | `direct_browser_bridge` and `direct_computer_bridge` (live bridge sockets that the browser and computer tools use in-process) |
| `folders.py`, `suggested_tasks.py`, `todos.py`, `questions.py`, `permissions.py` | `session-folders`, `sessions/{session_id}/folder`, `suggested-tasks`, `todos`, `questions`, `permissions` | `stream_store.running_session_ids`; `team_manager.prewarm_session_team`; the `suggested_task` tool; the pending permission and question requests held per stream by `agent/permission.py` and `agent/ask_user.py` (`get_services_for_stream`) |
| `language_servers.py`, `search_everywhere.py`, `app_search.py`, `document_versions.py`, `motion_review.py`, `office_runtime.py` | `workspace/language-servers`, `workspace/search-everywhere`, `search-app`, `{session_id}/document-versions`, `motion-review`, `office-runtime` | `lsp_manager` (also used by the `lsp` tool); `problems_service`; `memory_stream_store`; `motion_review_service._pending` (also used by the `visualize` tool); `office_runtime` (also used by the `shell` tool) |

## Lifespan services

The twelve names `EVOFLUX_DISABLE_SERVICES` accepts (Phase 0 plan, Task 6),
started in `app/api/app.py` `lifespan()` and `_start_optional_services()`.
Scheduler and dream are in the agent-runtime unit (design §3.1).

| service | unit | pinned by |
|---|---|---|
| `otel_retention` | observability | deletes aged OpenTelemetry files that `/api/observability` reads; no in-process state shared with the agent |
| `model_registry_refresh` | agent-runtime | refreshes the `lru_cache`d `model_registry` that provider code and `/api/settings/providers` read in-process |
| `mcp` | agent-runtime | `mcp_manager`: owns the `mcp.json` watcher and live connections; the agent loop reads its tools in-process |
| `plugin_mcp` | agent-runtime | `plugin_mcp_runtime`: starts MCP servers declared by installed plugins, shares tools with `mcp_manager` |
| `conductor` | agent-runtime | `conductor_service`: imported by `agent/loader.py`, `mode/team`, the telemetry hook and `skills_service` |
| `agents_validation` | agent-runtime | `team_manager.validate_agents_dir`, which validates the agent files the team manager loads |
| `standalone_coding_purge` | agent-runtime | removes standalone Coding sessions and tasks (`snapshot_service`, terminals) and must finish before the scheduler can fire |
| `scheduler` | agent-runtime | `task_scheduler.start`, which dispatches through `team_manager` |
| `memory_backfill` | agent-runtime | `scoped_memory`, which the memory hooks and tools use in-process |
| `dream_scheduler` | agent-runtime | `DreamScheduler`, whose run builds an agent and provider in-process |
| `webbridge_cleanup` | agent-runtime | `webbridge_manager.run_cleanup_loop`: cleans the in-memory extension connections |
| `webbridge_artifact_cleanup` | agent-runtime | `run_artifact_cleanup_loop` over the WebBridge artifact store used by the browser tools |

## Split candidates

Splits need a shared PR (owner-reviewed) that changes `routing.toml` and this
file, and a lane `NOTES.md` that proves the new unit shares nothing with Python
code that stays behind. Starting points found while reading:

- **`/api/settings` file-backed sections** (sandbox, context, version control,
  follow-up, background tasks, response style) read through `runtime_settings`
  and `sandbox_config`, which have no process cache. Providers, conductor and
  WebBridge stay in agent-runtime. Verify each section before splitting.
- **Git and worktrees** are pinned mostly by `git_ops`'s in-process locks and
  `coding_workspace_service`. If the `pr`, `worktree` and `code_reviews` tools
  were reached over a process-level lock instead, git could be its own unit.
- **`/api/health/ready` and `/diagnostics`** need the team manager's state. A
  gateway-owned readiness check could replace them, but that changes behaviour
  and needs a `KNOWN_DIFFERENCES.md` entry.
- **`/api/wiki`** could join `observability` if wiki writes from the `note` tool,
  the memory hooks and dream went through a cross-process lock.
