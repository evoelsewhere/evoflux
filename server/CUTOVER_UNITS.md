# Cutover units

The route and service assignments reflect v3.1.1 state. Python owns every unit until its owner-approved cutover. Longest matching route prefix wins; narrower unit routes carve out from broader prefixes. The SPA catch-all does not own API paths.

## Units

| unit | phase | pin_breaker | reverse_deps | adapter_call_sites | what it holds / pin rationale |
|---|---|---|---|---|---|
| `edge-stateless` | 1 | none | - | - | Pure responses and file discovery; no shared in-process pin. |
| `observability` | 1 | none | - | - | OpenTelemetry JSONL readers and retention; writers remain file based. |
| `import` | 2 | none | - | - | Database-backed import jobs and session records; no shared process cache identified. |
| `remote-access` | 2 | `adapter:remote-access` | desktop authentication claim and embedded tailnet manager | `app/core/desktop_auth.py`, `app/services/remote_use_service.py` | Tailnet manager and desktop claim must share ownership through the adapter. |
| `settings-providers` | 2 | `adapter:settings-providers` | model_registry and provider plugin registry caches | `app/core/runtime_settings.py`, `app/agent/providers/**`, `app/plugin_platform/registry.py` | Provider and settings consumers switch through the adapter; cached registry data must revalidate. |
| `agents-skills` | 2 | `adapter:agents-skills` | team_manager skill cache and agent settings cache | `app/services/team_manager.py`, `app/services/skills_service.py`, `app/core/agent_settings.py`, `app/core/skill_settings.py`, `app/agent/skills/**` | Skill writes currently invalidate team_manager; replace invalidation with versioned reads or a Rust event stream. |
| `plugins-mcp` | 2 | `adapter:plugins-mcp` | plugin_mcp_runtime, MCP connections and team_manager skill cache | `app/plugin_platform/runtime.py`, `app/agent/mcp/**`, `app/services/team_manager.py`, `app/api/routes/plugins.py` | Plugin writes refresh plugin_mcp_runtime and invalidate skill caches; MCP tool access needs the adapter and revalidation. |
| `git-coding` | 2 | `adapter:git-coding`, `file-lock:git-repo` | change_set_service and problems_service caches | `app/agent/tools/builtin/pr.py`, `app/agent/tools/builtin/worktree.py`, `app/agent/tools/builtin/code_reviews.py`, `app/agent/hooks/problem_capture.py`, `app/agent/hooks/post_edit_diagnostics.py`, `app/api/routes/team/git_ai.py`, `app/services/git_ops.py`, `app/services/coding_*`, `app/services/change_set_service.py`, `app/services/problems_service.py` | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `terminal-processes` | 2 | `adapter:terminal-processes` | terminal, process and preview registries; active stream watchers | `app/agent/tools/**`, `app/services/terminal_service.py`, `app/services/process_manager.py`, `app/services/workspace_file_watcher.py`, `app/services/memory_stream_store.py` | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `memory-search` | 2 | `adapter:memory-search`, `file-lock:wiki` | memory hooks and wiki readers | `app/agent/hooks/**`, `app/agent/tools/**`, `app/services/wiki.py`, `app/services/memory*.py` | Wiki writes require a cross-process file lock and Python memory consumers must revalidate Rust writes. |
| `documents-preview` | 2 | `adapter:documents-preview` | stream_store and motion review pending state | `app/agent/tools/**`, `app/services/memory_stream_store.py`, `app/services/motion_review_service.py`, `app/services/office_runtime.py` | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `workspace-files` | 2 | `adapter:workspace-files`, `file-lock:snapshot` | snapshot, LSP and session activity caches | `app/agent/tools/**`, `app/services/snapshot_service.py`, `app/services/lsp*.py`, `app/services/chat_service.py`, `app/services/shell_service.py`, `app/services/memory_stream_store.py` | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `webbridge-browser` | 2 | `adapter:webbridge-browser` | webbridge policy cache, extension connections and direct bridge sockets | `app/services/webbridge_service.py`, `app/api/routes/settings.py`, `app/api/routes/team/webbridge.py`, `app/agent/tools/builtin/webbridge_tool.py`, `app/agent/tools/builtin/browser_use_tool.py`, `app/agent/tools/builtin/computer_app_tool.py`, `app/services/memory_stream_store.py` | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `conductor` | 2 | `adapter:conductor` | conductor managed-agent state and telemetry | `app/conductor/**`, `app/agent/loader.py`, `app/agent/hooks/**`, `app/services/skills_service.py` | Conductor consumers must use the adapter for shared managed-agent state. |
| `health-diagnostics` | 2 | `adapter:health-diagnostics` | team_manager active-turn and MCP status | `app/services/team_manager.py`, `app/agent/mcp/**` | Readiness and diagnostics depend on live state; provide equivalent Rust-backed reads through the adapter. |
| `agent-runtime` | 3 | - | - | - | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `platform-meta` | 4 | none | - | - | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; |

`adapter_call_sites` lists the Python paths a cutover branch may change. The adapter is `app/core/rust_bridge/<unit>.py` (hyphens become underscores); each cutover must prove its tool path through Rust. The entries are planning boundaries, not evidence that an adapter already exists. Stateless units have reserved adapter names to keep the cutover contract uniform.

Reverse dependencies must use read-through or Rust version/ETag revalidation, or subscribe to a Rust event stream, as ADR 0001 rule 7 requires. Each lane NOTES must inventory these dependencies and prove the proposed lock and adapter boundaries before cutover.

## Route prefixes

| route | unit | pinned by |
|---|---|---|
| `/api/health/live/**` | edge-stateless | Pure responses and file discovery; no shared in-process pin. The adapter is a reserved cutover boundary. |
| `/api/quote/**` | edge-stateless | Pure responses and file discovery; no shared in-process pin. The adapter is a reserved cutover boundary. |
| `/api/commands/**` | edge-stateless | Pure responses and file discovery; no shared in-process pin. The adapter is a reserved cutover boundary. |
| `/api/snippets/**` | edge-stateless | Pure responses and file discovery; no shared in-process pin. The adapter is a reserved cutover boundary. |
| `/api/observability/**` | observability | OpenTelemetry JSONL readers and retention; writers remain file based. |
| `/api/import/**` | import | Database-backed import jobs and session records; no shared process cache identified. |
| `/api/remote-use/**` | remote-access | Tailnet manager and desktop claim must share ownership through the adapter. |
| `/api/settings/**` | settings-providers | Provider and settings consumers switch through the adapter; cached registry data must revalidate. |
| `/api/auth/**` | settings-providers | Provider and settings consumers switch through the adapter; cached registry data must revalidate. |
| `/api/agents/**` | agents-skills | Skill writes currently invalidate team_manager; replace invalidation with versioned reads or a Rust event stream. |
| `/api/skills/**` | agents-skills | Skill writes currently invalidate team_manager; replace invalidation with versioned reads or a Rust event stream. |
| `/api/plugins/**` | plugins-mcp | Plugin writes refresh plugin_mcp_runtime and invalidate skill caches; MCP tool access needs the adapter and revalidation. |
| `/api/mcp/**` | plugins-mcp | Plugin writes refresh plugin_mcp_runtime and invalidate skill caches; MCP tool access needs the adapter and revalidation. |
| `/api/team/workspace/git/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/workspace/worktrees/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/reviews/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/projects/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/workspace/change-sets/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/workspace/problems/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/workspace/editor/**` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `/api/team/{session_id}/terminal/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/team/{session_id}/terminals/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/team/processes/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/team/preview/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/team/workspace/watch/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/team/{session_id}/files/watch/**` | terminal-processes | The tools and watcher consumers must use one Rust-owned process registry via the adapter. |
| `/api/wiki/**` | memory-search | Wiki writes require a cross-process file lock and Python memory consumers must revalidate Rust writes. |
| `/api/team/workspace/search-everywhere/**` | memory-search | Wiki writes require a cross-process file lock and Python memory consumers must revalidate Rust writes. |
| `/api/team/search-app/**` | memory-search | Wiki writes require a cross-process file lock and Python memory consumers must revalidate Rust writes. |
| `/api/team/{session_id}/document-preview/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/{session_id}/office-preview/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/{session_id}/document-versions/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/{session_id}/motion-review/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/{session_id}/media/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/office-runtime/**` | documents-preview | Document preview, motion review and office tools use shared in-memory services and stream notifications. |
| `/api/team/workspace/files/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/status/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/git-diff/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/lsp/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/language-servers/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/browse/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/tree/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/workspace/validate/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/{session_id}/files/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/{session_id}/workspace/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/{session_id}/uploads/**` | workspace-files | File and LSP consumers need adapter-owned state; snapshot locks must work across processes. |
| `/api/team/webbridge/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/team/browser/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/team/{session_id}/browser/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/team/{session_id}/computer/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/settings/webbridge/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/settings/computer-app/**` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `/api/settings/conductor/**` | conductor | Conductor consumers must use the adapter for shared managed-agent state. |
| `/api/health/**` | health-diagnostics | Readiness and diagnostics depend on live state; provide equivalent Rust-backed reads through the adapter. |
| `/api/diagnostics/**` | health-diagnostics | Readiness and diagnostics depend on live state; provide equivalent Rust-backed reads through the adapter. |
| `/api/scheduler/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/dream/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/chat/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/leads/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/agents/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/commands/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/sessions/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/session-folders/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/suggested-tasks/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/history/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/side-chat/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/stream/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/goal/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/permissions/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/{session_id}/questions/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/api/team/**` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `/metrics` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/openapi.json` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/docs` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/docs/oauth2-redirect` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/redoc` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/**` | platform-meta | Python-generated docs and metrics plus the packaged UI stay Python-owned until gateway equivalents are ready; adapter reserved for cutover. |
| `/api/team/webbridge/sessions/**` | agent-runtime | WebBridge session messages and streams invoke Python chat and the in-memory stream store; Rust cannot call Python. |
| `/api/team/webbridge/interactions/**` | agent-runtime | WebBridge interactions can submit messages to the Python agent loop; Rust cannot call Python. |
| `/api/team/workspace/git/ai/**` | agent-runtime | Git AI obtains a live Python team provider and calls it in-process, so it moves with the agent loop. |

## Lifespan services

| service | unit | pinned by |
|---|---|---|
| `otel_retention` | observability | OpenTelemetry JSONL readers and retention; writers remain file based. |
| `agents_validation` | agents-skills | Skill writes currently invalidate team_manager; replace invalidation with versioned reads or a Rust event stream. |
| `mcp` | plugins-mcp | Plugin writes refresh plugin_mcp_runtime and invalidate skill caches; MCP tool access needs the adapter and revalidation. |
| `plugin_mcp` | plugins-mcp | Plugin writes refresh plugin_mcp_runtime and invalidate skill caches; MCP tool access needs the adapter and revalidation. |
| `standalone_coding_purge` | git-coding | Git locks, coding workspace, change sets and diagnostics need adapter-owned state; repository locks must also work across processes. |
| `memory_backfill` | memory-search | Wiki writes require a cross-process file lock and Python memory consumers must revalidate Rust writes. |
| `conductor` | conductor | Conductor consumers must use the adapter for shared managed-agent state. |
| `webbridge_cleanup` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `webbridge_artifact_cleanup` | webbridge-browser | Settings writes currently call reload_policy; use Rust version revalidation or a Python subscription to Rust events. |
| `model_registry_refresh` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `scheduler` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |
| `dream_scheduler` | agent-runtime | Chat and WebBridge session ingress, git AI provider calls, SSE, pending interaction futures, team_manager, scheduler and dream execute the Python agent loop. An adapter would need to run that loop or require Rust to call Python, so these remain together until the loop moves. |

## Split candidates

The previous settings, git and wiki candidates are now planned as independent units above. The remaining `agent-runtime` routes must move with the agent loop: ingress, streamed events, interaction futures, scheduler and dream directly manipulate its process-local state. Before a lane cuts over, its NOTES must verify the listed call sites and reverse dependencies against the then-current Python code. Cross-process locks for wiki, git and snapshots require their own parity and contention tests.
